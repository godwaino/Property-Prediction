from __future__ import annotations

import csv
import io
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for

from ppd_sqlite import ingest_comparable_rows, init_db
from propertyscorecard_core import estimate_property_value, serialize_result

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("predictelligence-property")

app = Flask(__name__)
init_db()
start_time = datetime.utcnow()
IS_SERVERLESS = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
_engine = None
_engine_error: str | None = None

# ── Root modules (enrichment + Claude AI) ─────────────────────────────────────
# Added to sys.path with append so local propertyscorecard_core stays cached.
_ROOT_DIR = Path(__file__).resolve().parents[1]
if str(_ROOT_DIR) not in sys.path:
    sys.path.append(str(_ROOT_DIR))

try:
    from location_enrichment import enrich_postcode as _enrich_postcode  # type: ignore[import]
    _HAS_ENRICHMENT = True
except ImportError:
    _HAS_ENRICHMENT = False

try:
    from claude_ai import generate_ai_narrative as _gen_narrative, is_claude_available  # type: ignore[import]
    _HAS_CLAUDE = True
except ImportError:
    _HAS_CLAUDE = False
    def is_claude_available() -> bool:  # type: ignore[misc]
        return False


# ── ML Engine ─────────────────────────────────────────────────────────────────

def get_engine():
    global _engine, _engine_error
    if _engine is not None:
        return _engine
    if _engine_error is not None:
        raise RuntimeError(_engine_error)
    try:
        from predictelligence import PredictelligenceEngine

        _engine = PredictelligenceEngine(enable_warmup=not IS_SERVERLESS)
        return _engine
    except Exception as exc:
        _engine_error = f"Engine initialization failed: {exc}"
        logger.exception(_engine_error)
        raise RuntimeError(_engine_error) from exc


def scheduled_learning():
    import schedule

    def tick():
        try:
            get_engine().pipeline.run("SW1A1AA", 285000, 285000, "investor", property_type="semi-detached", bedrooms=2)
        except Exception:
            logger.exception("Scheduled learning tick failed")

    schedule.every(60).seconds.do(tick)
    while True:
        schedule.run_pending()
        time.sleep(1)


if not IS_SERVERLESS:
    try:
        get_engine()
    except Exception:
        logger.exception("Non-serverless startup engine init failed")
    threading.Thread(target=scheduled_learning, daemon=True).start()
else:
    logger.info("Serverless mode detected: skipping background scheduler threads and eager warmup")

logger.info("Predictelligence Property Engine initialised")


# ── Result builder ─────────────────────────────────────────────────────────────

def _build_premium_result(
    valuation,
    prediction,
    postcode: str,
    property_type: str,
    bedrooms: int,
    asking_price: float,
    user_type: str,
    enrichment_data=None,
    ai_narrative: str = "",
) -> dict:
    """Map ValuationResult → premium JSON format consumed by the bento-grid JS."""
    verdict_adj = {"STRONG BUY": 15, "BUY": 8, "NEGOTIATE": 0, "AVOID": -15}
    score = min(100, max(0, round(
        valuation.confidence + verdict_adj.get(valuation.deal_verdict, 0)
    )))

    fv = valuation.estimated_value
    fair_low  = round(fv * 0.95)
    fair_mid  = round(fv)
    fair_high = round(fv * 1.05)

    pct_diff = (valuation.estimated_value - asking_price) / max(asking_price, 1) * 100
    anchor = round(min(asking_price, valuation.estimated_value) * 0.97)
    discount_pct = round(max(0.0, -pct_diff + 3.0), 1)

    red_flags = []
    for f in valuation.risk_flags:
        sev = "high" if (">10%" in f or valuation.deal_verdict == "AVOID") else "medium"
        red_flags.append({"flag": f, "severity": sev, "impact": None})

    return {
        "facts": {
            "postcode": postcode,
            "property_type": property_type,
            "bedrooms": bedrooms,
            "price": asking_price,
            "user_type": user_type,
        },
        "valuation": {
            "score": score,
            "label": valuation.deal_verdict,
            "notes": [valuation.negotiation_strategy] if valuation.negotiation_strategy else [],
            "red_flags": red_flags,
            "fair_value_low":  fair_low,
            "fair_value_mid":  fair_mid,
            "fair_value_high": fair_high,
            "comp_count": None,
            "comparable_average": round(valuation.comparable_average),
            "confidence": valuation.confidence,
            "strategy": {
                "anchor_offer":     anchor,
                "offer_range_low":  round(asking_price * 0.92),
                "offer_range_high": round(asking_price * 0.97),
                "tactic":           valuation.negotiation_strategy,
                "asking_discount_pct": discount_pct,
            },
        },
        "enrichment":   enrichment_data,
        "ai_narrative": ai_narrative,
        "prediction":   prediction,
        "comps":        [],
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def home():
    return render_template("index.html")


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
    # Accept JSON (from bento-grid JS) or form data (legacy fallback)
    if request.is_json:
        data = request.get_json(force=True) or {}
        postcode     = str(data.get("postcode", "SW1A1AA")).strip().upper().replace(" ", "")
        property_type = str(data.get("property_type", "Semi-detached"))
        bedrooms     = int(data.get("bedrooms", 2) or 2)
        asking_price = float(data.get("asking_price", 0) or 0)
        user_type    = str(data.get("user_type", "investor"))
    else:
        postcode     = request.form.get("postcode", "").strip().upper().replace(" ", "")
        property_type = request.form.get("property_type", "Semi-detached")
        bedrooms     = int(request.form.get("bedrooms", 2) or 2)
        asking_price = float(request.form.get("asking_price", 0) or 0)
        user_type    = request.form.get("user_type", "investor")

    if not postcode:
        if request.is_json:
            return jsonify({"ok": False, "error": "Postcode is required"}), 400
        return render_template("index.html")

    # ── Valuation ─────────────────────────────────────────────────────────────
    valuation = estimate_property_value(postcode, property_type, bedrooms, asking_price, user_type)

    # ── ML Prediction ─────────────────────────────────────────────────────────
    try:
        prediction = get_engine().analyse(
            postcode=postcode,
            current_valuation=valuation.estimated_value,
            comparable_average=valuation.comparable_average,
            user_type=user_type,
            property_type=property_type,
            bedrooms=bedrooms,
        )
    except Exception as exc:
        prediction = {"error": str(exc), "model_cycles": 0}

    # Legacy HTML path (form POST without JS)
    if not request.is_json:
        result = serialize_result(valuation)
        result["prediction"] = prediction
        result["user_type"] = user_type
        return render_template("index.html", result=result)

    # ── Location enrichment ───────────────────────────────────────────────────
    enrichment_data = None
    if _HAS_ENRICHMENT:
        try:
            raw = _enrich_postcode(postcode)
            enrichment_data = raw.to_dict() if hasattr(raw, "to_dict") else raw
        except Exception as exc:
            logger.warning("Enrichment failed: %s", exc)

    # ── Claude AI narrative ───────────────────────────────────────────────────
    ai_narrative = ""
    if _HAS_CLAUDE and is_claude_available():
        try:
            fv = valuation.estimated_value
            ai_narrative = _gen_narrative(
                facts={
                    "postcode": postcode,
                    "property_type": property_type,
                    "bedrooms": bedrooms,
                    "user_type": user_type,
                },
                valuation={
                    "fair_value_low":  round(fv * 0.95),
                    "fair_value_mid":  round(fv),
                    "fair_value_high": round(fv * 1.05),
                },
                comps=[],
                score_data={
                    "score": min(100, max(0, round(valuation.confidence))),
                    "fair_value_low":  round(fv * 0.95),
                    "fair_value_mid":  round(fv),
                    "fair_value_high": round(fv * 1.05),
                },
                strategy={},
                enrichment=enrichment_data or {},
                prediction=prediction,
            )
        except Exception as exc:
            logger.warning("Claude narrative failed: %s", exc)

    result = _build_premium_result(
        valuation=valuation,
        prediction=prediction,
        postcode=postcode,
        property_type=property_type,
        bedrooms=bedrooms,
        asking_price=asking_price,
        user_type=user_type,
        enrichment_data=enrichment_data,
        ai_narrative=ai_narrative,
    )
    return jsonify({"ok": True, "result": result})


@app.get("/api/analyze")
def analyze_api():
    postcode      = request.args.get("postcode", "SW1A1AA")
    property_type = request.args.get("property_type", "semi-detached")
    bedrooms      = int(request.args.get("bedrooms", 2))
    asking_price  = float(request.args.get("asking_price", 285000))
    user_type     = request.args.get("user_type", "investor")

    valuation = estimate_property_value(postcode, property_type, bedrooms, asking_price, user_type)
    result = serialize_result(valuation)
    try:
        result["prediction"] = get_engine().analyse(
            postcode,
            valuation.estimated_value,
            valuation.comparable_average,
            user_type,
            property_type=property_type,
            bedrooms=bedrooms,
        )
    except Exception as exc:
        result["prediction"] = {"error": str(exc), "model_cycles": 0}
    return jsonify(result)


@app.get("/api/prediction/predict")
def api_predict():
    postcode           = request.args.get("postcode", "SW1A1AA")
    current_valuation  = float(request.args.get("current_valuation", 285000))
    comparable_average = float(request.args.get("comparable_average", current_valuation))
    user_type          = request.args.get("user_type", "investor")
    property_type      = request.args.get("property_type", "semi-detached")
    bedrooms           = int(request.args.get("bedrooms", 2))
    try:
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
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503


@app.get("/api/prediction/history")
def api_history():
    postcode = request.args.get("postcode", "SW1A1AA")
    limit = int(request.args.get("limit", 20))
    try:
        return jsonify(get_engine().get_history(postcode, limit))
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc), "history": []}), 503


@app.get("/api/prediction/health")
def api_health():
    uptime = str(datetime.utcnow() - start_time)
    try:
        latest = get_engine().db.latest_prediction("SW1A1AA")
        cycles = latest.get("cycle", 0) if latest else 0
        return jsonify({"status": "ok", "model_cycles": cycles, "model_ready": cycles >= 3, "uptime": uptime})
    except Exception as exc:
        return jsonify({"status": "degraded", "message": str(exc), "model_cycles": 0, "model_ready": False, "uptime": uptime}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=not IS_SERVERLESS)
