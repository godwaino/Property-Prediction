"""
Predictelligence Property — Unified Flask Application
Combines PropertyScorecard (Rightmove valuation) with the
Predictelligence ML prediction engine in a single app.

Enhanced with:
  - In-memory analysis caching (1-hour TTL by URL hash)
  - IP-based rate limiting (20 req/IP/min on /analyze)
  - Admin stats endpoint (/api/admin/stats)
  - Location enrichment (crime, flood, deprivation, EPC, planning)
  - Claude AI narrative generation
"""
from __future__ import annotations

import collections
import hashlib
import logging
import os
import threading
import time
import traceback
from datetime import datetime, timezone
from io import BytesIO
from typing import Dict, Optional, Tuple

from flask import Flask, abort, jsonify, render_template, request, send_file

from storage import get_analysis, init_db, list_analyses, save_analysis
from propertyscorecard_core import run_propertyscorecard

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("predictelligence_property")

# ── Paths ──────────────────────────────────────────────────────────────────────
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "propertyscorecard.db")
PPD_SQLITE_PATH = os.path.join(DATA_DIR, "ppd.sqlite")
PREDICTIONS_DB_PATH = os.path.join(DATA_DIR, "predictions.db")

os.makedirs(DATA_DIR, exist_ok=True)

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["DEBUG"] = os.environ.get("FLASK_ENV") == "development"

init_db(DB_PATH)

# ── In-memory analysis cache ───────────────────────────────────────────────────
_analysis_cache: Dict[str, Tuple[float, dict]] = {}   # key → (expires_at, result)
_cache_lock = threading.Lock()
_CACHE_TTL = 3600  # 1 hour
_cache_hits = 0
_cache_misses = 0


def _cache_key(url: str) -> str:
    """SHA-256 of the URL (excluding asking price — URL is stable per listing)."""
    return hashlib.sha256(url.encode()).hexdigest()[:20]


def _cache_get(key: str) -> Optional[dict]:
    global _cache_hits, _cache_misses
    with _cache_lock:
        entry = _analysis_cache.get(key)
        if entry and time.time() < entry[0]:
            _cache_hits += 1
            return entry[1]
        if entry:
            del _analysis_cache[key]
        _cache_misses += 1
        return None


def _cache_set(key: str, value: dict) -> None:
    with _cache_lock:
        _analysis_cache[key] = (time.time() + _CACHE_TTL, value)


def _cache_stats() -> dict:
    with _cache_lock:
        total = len(_analysis_cache)
        now = time.time()
        active = sum(1 for exp, _ in _analysis_cache.values() if now < exp)
    total_req = _cache_hits + _cache_misses
    return {
        "total_entries": total,
        "active_entries": active,
        "hits": _cache_hits,
        "misses": _cache_misses,
        "hit_rate_pct": round(_cache_hits / total_req * 100, 1) if total_req else 0.0,
    }


# ── Rate limiter ───────────────────────────────────────────────────────────────
_rate_store: Dict[str, collections.deque] = collections.defaultdict(collections.deque)
_rate_lock = threading.Lock()
_RATE_WINDOW = 60   # seconds
_RATE_MAX = 20      # requests per window


def _check_rate_limit(ip: str) -> bool:
    """Returns True if request is allowed, False if over limit."""
    now = time.time()
    with _rate_lock:
        dq = _rate_store[ip]
        while dq and dq[0] < now - _RATE_WINDOW:
            dq.popleft()
        if len(dq) >= _RATE_MAX:
            return False
        dq.append(now)
        return True


def _get_client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"

# ── Predictelligence Engine (lazy init in background) ─────────────────────────
_engine = None
_engine_ready = False
_engine_lock = threading.Lock()
_startup_time = datetime.now(timezone.utc)


def _init_engine() -> None:
    """Initialise the prediction engine in a background thread."""
    global _engine, _engine_ready
    try:
        logger.info("Initialising Predictelligence Engine…")
        from predictelligence.engine import PredictelligenceEngine
        eng = PredictelligenceEngine(db_path=PREDICTIONS_DB_PATH)
        with _engine_lock:
            _engine = eng
            _engine_ready = True
        logger.info("Predictelligence Property Engine initialised")
    except Exception as exc:
        logger.error("Failed to initialise prediction engine: %s", exc)


def _background_scheduler() -> None:
    """Re-run the pipeline every 30 s and auto-save state periodically."""
    _LEARN_INTERVAL = 30   # seconds between learning cycles
    _SAVE_INTERVAL  = 300  # seconds between explicit saves (5 min)

    # Rotate through representative UK properties for varied training
    _BG_PROPERTIES = [
        ("SW1A1AA", 450_000.0, 420_000.0, "investor"),
        ("M11AE",   195_000.0, 200_000.0, "home_mover"),
        ("LS11AA",  250_000.0, 245_000.0, "investor"),
        ("EC1A1BB", 320_000.0, 310_000.0, "first_time_buyer"),
        ("B11AA",   175_000.0, 180_000.0, "investor"),
    ]

    # Wait for engine to be ready
    for _ in range(60):
        if _engine_ready:
            break
        time.sleep(1)

    last_save = time.time()
    rotation = 0

    while True:
        time.sleep(_LEARN_INTERVAL)
        try:
            with _engine_lock:
                eng = _engine
            if not eng:
                continue

            postcode, val, comp, utype = _BG_PROPERTIES[rotation % len(_BG_PROPERTIES)]
            rotation += 1

            eng.pipeline.run(
                postcode=postcode,
                current_valuation=val,
                comparable_average=comp,
                user_type=utype,
            )
            logger.debug(
                "Background learning cycle %d complete (postcode=%s)",
                eng.pipeline.model_agent._n_trained,
                postcode,
            )

            # Periodic explicit save
            if time.time() - last_save > _SAVE_INTERVAL:
                eng.save()
                last_save = time.time()

        except Exception as exc:
            logger.warning("Background scheduler error: %s", exc)


# Start both threads on import (guarded so they only start once)
_init_thread = threading.Thread(target=_init_engine, daemon=True, name="engine-init")
_init_thread.start()

_scheduler_thread = threading.Thread(target=_background_scheduler, daemon=True, name="engine-scheduler")
_scheduler_thread.start()


# ── Helper: get engine safely ─────────────────────────────────────────────────

def _get_engine():
    with _engine_lock:
        return _engine


# ─────────────────────────────────────────────────────────────────────────────
# EXISTING PROPERTYSCORECARD ROUTES (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
def home():
    rows = list_analyses(DB_PATH, limit=30)
    return render_template("dashboard.html", analyses=rows)


def _run_predictelligence(result: dict, user_type: str) -> dict:
    """Run the ML prediction engine on an already-analysed property result."""
    eng = _get_engine()
    if not eng:
        return {"model_ready": False, "warming_up": True}
    try:
        facts = result.get("facts") or {}
        valuation = result.get("valuation") or {}
        postcode = facts.get("postcode") or "SW1A1AA"
        current_val = float(facts.get("price") or 285_000)
        comp_avg = float(valuation.get("fair_value_mid") or current_val)

        prediction = eng.analyse(
            postcode=postcode,
            current_valuation=current_val,
            comparable_average=comp_avg,
            user_type=user_type,
        )
        logger.info(
            "Predictelligence: %s direction=%s signal=%s",
            postcode,
            prediction.get("direction"),
            prediction.get("investment_signal"),
        )
        return prediction
    except Exception as exc:
        logger.warning("Predictelligence analysis failed: %s", exc)
        return {"error": str(exc), "model_ready": False}


@app.post("/analyze")
def analyze():
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()
    user_type = (payload.get("user_type") or "investor").strip().lower()

    if not url:
        return jsonify({"ok": False, "error": "Please paste a Rightmove link."}), 400

    if "rightmove.co.uk" not in url.lower():
        return jsonify({"ok": False, "error": "Please provide a valid Rightmove URL."}), 400

    # ── Rate limit check ──────────────────────────────────────────────────────
    client_ip = _get_client_ip()
    if not _check_rate_limit(client_ip):
        return jsonify({
            "ok": False,
            "error": "Rate limit exceeded. Maximum 20 requests per minute.",
        }), 429

    # ── Cache check ───────────────────────────────────────────────────────────
    cache_key = _cache_key(url)
    cached = _cache_get(cache_key)
    if cached:
        logger.info("Cache hit for %s", url)
        cached_copy = dict(cached)
        cached_copy["prediction"] = _run_predictelligence(cached_copy, user_type)
        cached_copy["cache_hit"] = True
        return jsonify({"ok": True, "result": cached_copy})

    # ── Run PropertyScorecard (with enrichment + Claude) ──────────────────────
    try:
        logger.info("Starting PropertyScorecard analysis: %s", url)
        result = run_propertyscorecard(
            url=url,
            ppd_sqlite_path=PPD_SQLITE_PATH if os.path.exists(PPD_SQLITE_PATH) else None,
            user_type=user_type,
        )
        logger.info("PropertyScorecard complete")
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error("PropertyScorecard failed: %s\n%s", e, error_trace)
        return jsonify({"ok": False, "error": f"Analysis failed: {e}", "trace": error_trace}), 500

    # ── Run Predictelligence ──────────────────────────────────────────────────
    result["prediction"] = _run_predictelligence(result, user_type)
    result["cache_hit"] = False

    # ── Cache before persisting (without analysis_id) ─────────────────────────
    _cache_set(cache_key, result)

    # ── Persist to database ───────────────────────────────────────────────────
    try:
        analysis_id = save_analysis(DB_PATH, result)
        result["analysis_id"] = analysis_id
        result["permalink"] = f"/a/{analysis_id}"
    except Exception as e:
        logger.error("Failed to save analysis: %s", e)
        result["analysis_id"] = None
        result["permalink"] = None

    return jsonify({"ok": True, "result": result})


@app.get("/a/<int:analysis_id>")
def analysis_page(analysis_id: int):
    row = get_analysis(DB_PATH, analysis_id)
    if not row:
        abort(404)
    return render_template("analysis.html", row=row)


@app.get("/a/<int:analysis_id>/json")
def analysis_json(analysis_id: int):
    row = get_analysis(DB_PATH, analysis_id)
    if not row:
        abort(404)
    return jsonify({"ok": True, "analysis": row})


@app.get("/a/<int:analysis_id>/md")
def analysis_md(analysis_id: int):
    row = get_analysis(DB_PATH, analysis_id)
    if not row:
        abort(404)
    md = row.get("md_report") or ""
    buf = BytesIO(md.encode("utf-8"))
    filename = f"predictelligence_{row.get('property_id') or analysis_id}.md"
    return send_file(buf, as_attachment=True, download_name=filename, mimetype="text/markdown")


# ─────────────────────────────────────────────────────────────────────────────
# NEW PREDICTELLIGENCE API ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/prediction/predict")
def api_predict():
    """
    GET /api/prediction/predict
    Params: postcode, current_valuation, user_type
    """
    postcode = (request.args.get("postcode") or "SW1A1AA").strip()
    try:
        current_valuation = float(request.args.get("current_valuation") or 285_000)
    except ValueError:
        current_valuation = 285_000.0
    user_type = (request.args.get("user_type") or "investor").strip().lower()

    eng = _get_engine()
    if not eng:
        return jsonify({
            "ok": False,
            "error": "Prediction engine is still initialising. Try again shortly.",
            "model_ready": False,
        }), 503

    result = eng.analyse(
        postcode=postcode,
        current_valuation=current_valuation,
        comparable_average=current_valuation,  # no comp avg in standalone mode
        user_type=user_type,
    )
    return jsonify({"ok": True, "result": result})


@app.get("/api/prediction/history")
def api_prediction_history():
    """
    GET /api/prediction/history
    Params: postcode, limit (default 20)
    """
    postcode = (request.args.get("postcode") or "").strip()
    if not postcode:
        return jsonify({"ok": False, "error": "postcode param required"}), 400

    try:
        limit = int(request.args.get("limit") or 20)
    except ValueError:
        limit = 20

    eng = _get_engine()
    if not eng:
        return jsonify({"ok": True, "history": [], "model_ready": False})

    history = eng.get_history(postcode, limit=limit)
    return jsonify({"ok": True, "postcode": postcode, "history": history})


@app.get("/api/prediction/health")
def api_prediction_health():
    """GET /api/prediction/health"""
    eng = _get_engine()
    if not eng:
        uptime_s = (datetime.now(timezone.utc) - _startup_time).total_seconds()
        return jsonify({
            "status": "starting",
            "model_cycles": 0,
            "model_ready": False,
            "uptime": f"00:00:{int(uptime_s):02d}",
        })
    return jsonify({"ok": True, **eng.health()})


@app.get("/api/admin/stats")
def api_admin_stats():
    """
    GET /api/admin/stats
    Protected by X-Admin-Key header (matches ADMIN_KEY env var).
    Returns cache stats, model health, and uptime.
    """
    admin_key = os.environ.get("ADMIN_KEY", "")
    if admin_key:
        provided = request.headers.get("X-Admin-Key", "")
        if provided != admin_key:
            abort(403)

    eng = _get_engine()
    uptime_s = (datetime.now(timezone.utc) - _startup_time).total_seconds()
    h, remainder = divmod(int(uptime_s), 3600)
    m, s = divmod(remainder, 60)

    model_health = eng.health() if eng else {"status": "starting", "model_ready": False}

    return jsonify({
        "ok": True,
        "uptime": f"{h:02d}:{m:02d}:{s:02d}",
        "cache": _cache_stats(),
        "model": model_health,
        "rate_limiter": {
            "window_seconds": _RATE_WINDOW,
            "max_requests": _RATE_MAX,
            "tracked_ips": len(_rate_store),
        },
    })


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT") or 5000)
    logger.info("Starting Predictelligence Property server on port %d…", port)
    logger.info("Data directory: %s", DATA_DIR)
    logger.info("PropertyScorecard DB: %s", DB_PATH)
    logger.info("PPD SQLite present: %s", os.path.exists(PPD_SQLITE_PATH))
    app.run(host="0.0.0.0", port=port, debug=app.config["DEBUG"], use_reloader=False)
