from __future__ import annotations

import csv
import io
import logging
import os
import threading
import time
from datetime import datetime

import schedule
from flask import Flask, jsonify, redirect, render_template, request, url_for

from ppd_sqlite import ingest_comparable_rows, init_db
from predictelligence import PredictelligenceEngine
from propertyscorecard_core import estimate_property_value, serialize_result

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("predictelligence-property")

app = Flask(__name__)
init_db()
start_time = datetime.utcnow()
IS_SERVERLESS = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
_engine: PredictelligenceEngine | None = None


def get_engine() -> PredictelligenceEngine:
    global _engine
    if _engine is None:
        _engine = PredictelligenceEngine(enable_warmup=not IS_SERVERLESS)
    return _engine


def scheduled_learning():
    def tick():
        get_engine().pipeline.run("SW1A1AA", 285000, 285000, "investor", property_type="semi-detached", bedrooms=2)

    schedule.every(60).seconds.do(tick)
    while True:
        schedule.run_pending()
        time.sleep(1)


if not IS_SERVERLESS:
    get_engine()
    threading.Thread(target=scheduled_learning, daemon=True).start()
else:
    logger.info("Serverless mode detected: skipping background scheduler threads and eager warmup")

logger.info("Predictelligence Property Engine initialised")


@app.get("/")
def home():
    return render_template("index.html", result=None)


@app.get("/admin")
@app.get("/admin-dashboard")
@app.get("/dashboard/admin")
def admin_dashboard():
    uploaded = int(request.args.get("uploaded", 0) or 0)
    failed = int(request.args.get("failed", 0) or 0)
    return render_template("admin.html", uploaded=uploaded, failed=failed)


@app.post("/admin/upload-comparables")
def admin_upload_comparables():
    file = request.files.get("comparables_csv")
    if not file or not file.filename:
        return redirect(url_for("admin_dashboard", uploaded=0, failed=1))

    try:
        content = file.stream.read().decode("utf-8-sig", errors="ignore")
        reader = csv.DictReader(io.StringIO(content))
        inserted, failed = ingest_comparable_rows(reader)
        return redirect(url_for("admin_dashboard", uploaded=inserted, failed=failed))
    except Exception:
        return redirect(url_for("admin_dashboard", uploaded=0, failed=1))


@app.post("/analyze")
def analyze():
    postcode = request.form.get("postcode", "").strip()
    property_type = request.form.get("property_type", "semi-detached")
    bedrooms = int(request.form.get("bedrooms", 2) or 2)
    asking_price = float(request.form.get("asking_price", 0) or 0)
    user_type = request.form.get("user_type", "investor")

    valuation = estimate_property_value(postcode, property_type, bedrooms, asking_price, user_type)
    result = serialize_result(valuation)

    prediction = get_engine().analyse(
        postcode=postcode,
        current_valuation=valuation.estimated_value,
        comparable_average=valuation.comparable_average,
        user_type=user_type,
        property_type=property_type,
        bedrooms=bedrooms,
    )
    result["prediction"] = prediction
    result["user_type"] = user_type
    return render_template("index.html", result=result)


@app.get("/api/analyze")
def analyze_api():
    postcode = request.args.get("postcode", "SW1A1AA")
    property_type = request.args.get("property_type", "semi-detached")
    bedrooms = int(request.args.get("bedrooms", 2))
    asking_price = float(request.args.get("asking_price", 285000))
    user_type = request.args.get("user_type", "investor")

    valuation = estimate_property_value(postcode, property_type, bedrooms, asking_price, user_type)
    result = serialize_result(valuation)
    result["prediction"] = get_engine().analyse(
        postcode,
        valuation.estimated_value,
        valuation.comparable_average,
        user_type,
        property_type=property_type,
        bedrooms=bedrooms,
    )
    return jsonify(result)


@app.get("/api/prediction/predict")
def api_predict():
    postcode = request.args.get("postcode", "SW1A1AA")
    current_valuation = float(request.args.get("current_valuation", 285000))
    comparable_average = float(request.args.get("comparable_average", current_valuation))
    user_type = request.args.get("user_type", "investor")
    property_type = request.args.get("property_type", "semi-detached")
    bedrooms = int(request.args.get("bedrooms", 2))
    return jsonify(
        get_engine().analyse(
            postcode,
            current_valuation,
            comparable_average,
            user_type,
            property_type=property_type,
            bedrooms=bedrooms,
        )
    )


@app.get("/api/prediction/history")
def api_history():
    postcode = request.args.get("postcode", "SW1A1AA")
    limit = int(request.args.get("limit", 20))
    return jsonify(get_engine().get_history(postcode, limit))


@app.get("/api/prediction/health")
def api_health():
    latest = get_engine().db.latest_prediction("SW1A1AA")
    cycles = latest.get("cycle", 0) if latest else 0
    uptime = str(datetime.utcnow() - start_time)
    return jsonify({"status": "ok", "model_cycles": cycles, "model_ready": cycles >= 3, "uptime": uptime})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=not IS_SERVERLESS)
