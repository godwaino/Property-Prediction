from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

import schedule
from flask import Flask, jsonify, render_template, request

from ppd_sqlite import init_db
from predictelligence import PredictelligenceEngine
from propertyscorecard_core import estimate_property_value, serialize_result

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("predictelligence-property")

app = Flask(__name__)
init_db()
start_time = datetime.utcnow()
engine = PredictelligenceEngine()


def warmup_thread():
    try:
        engine._warm_up()
    except Exception as exc:
        logger.exception("Warm-up failed: %s", exc)


def scheduled_learning():
    def tick():
        engine.pipeline.run("SW1A1AA", 285000, 285000, "investor")

    schedule.every(60).seconds.do(tick)
    while True:
        schedule.run_pending()
        time.sleep(1)


threading.Thread(target=warmup_thread, daemon=True).start()
threading.Thread(target=scheduled_learning, daemon=True).start()
logger.info("Predictelligence Property Engine initialised")


@app.get("/")
def home():
    return render_template("index.html", result=None)


@app.post("/analyze")
def analyze():
    postcode = request.form.get("postcode", "").strip()
    property_type = request.form.get("property_type", "semi-detached")
    bedrooms = int(request.form.get("bedrooms", 2) or 2)
    asking_price = float(request.form.get("asking_price", 0) or 0)
    user_type = request.form.get("user_type", "investor")

    valuation = estimate_property_value(postcode, property_type, bedrooms, asking_price, user_type)
    result = serialize_result(valuation)

    prediction = engine.analyse(
        postcode=postcode,
        current_valuation=valuation.estimated_value,
        comparable_average=valuation.comparable_average,
        user_type=user_type,
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
    result["prediction"] = engine.analyse(postcode, valuation.estimated_value, valuation.comparable_average, user_type)
    return jsonify(result)


@app.get("/api/prediction/predict")
def api_predict():
    postcode = request.args.get("postcode", "SW1A1AA")
    current_valuation = float(request.args.get("current_valuation", 285000))
    comparable_average = float(request.args.get("comparable_average", current_valuation))
    user_type = request.args.get("user_type", "investor")
    return jsonify(engine.analyse(postcode, current_valuation, comparable_average, user_type))


@app.get("/api/prediction/history")
def api_history():
    postcode = request.args.get("postcode", "SW1A1AA")
    limit = int(request.args.get("limit", 20))
    return jsonify(engine.get_history(postcode, limit))


@app.get("/api/prediction/health")
def api_health():
    latest = engine.db.latest_prediction("SW1A1AA")
    cycles = latest.get("cycle", 0) if latest else 0
    uptime = str(datetime.utcnow() - start_time)
    return jsonify({"status": "ok", "model_cycles": cycles, "model_ready": cycles >= 3, "uptime": uptime})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
