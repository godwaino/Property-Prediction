"""
PredictelligenceEngine — main entry point for the prediction engine.
Manages the pipeline, warm-up, and clean output serialisation.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from predictelligence.pipeline import PropertyPipeline
from predictelligence.db_manager import DbManager

logger = logging.getLogger("predictelligence.engine")

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(_APP_DIR, "data", "predictions.db")


class PredictelligenceEngine:
    """
    Unified interface for the Predictelligence prediction engine.

    Usage:
        engine = PredictelligenceEngine()
        result = engine.analyse("SW1A1AA", 450_000, 420_000, "investor")
    """

    WARMUP_CYCLES = 3

    def __init__(self, db_path: Optional[str] = None) -> None:
        resolved_db = db_path or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(resolved_db), exist_ok=True)

        self.pipeline = PropertyPipeline(db_path=resolved_db)
        self.db = DbManager(db_path=resolved_db)
        self._startup_time = datetime.now(timezone.utc)
        self._warm_up()

    # Historical UK macro snapshots used for warm-up (no API calls needed)
    _WARMUP_MACRO_HISTORY = [
        # (boe_rate, inflation, temp, season_factor, uk_avg_price, season)
        (5.25, 4.6, 15.0, 1.0, 285_000, "Spring"),    # 2023 Q2
        (5.25, 3.9, 19.0, 1.0, 288_000, "Summer"),    # 2023 Q3
        (5.25, 3.2,  9.0, 0.8, 282_000, "Autumn"),    # 2023 Q4
        (5.25, 2.8,  4.0, 0.6, 278_000, "Winter"),    # 2024 Q1
        (5.00, 2.3, 13.0, 1.0, 281_000, "Spring"),    # 2024 Q2
        (4.75, 2.0, 20.0, 1.0, 284_000, "Summer"),    # 2024 Q3
        (4.75, 2.3,  8.0, 0.8, 287_000, "Autumn"),    # 2024 Q4
        (4.50, 3.8,  5.0, 0.6, 285_000, "Winter"),    # 2025 Q1
    ]

    _WARMUP_PROPERTIES = [
        ("SW1A1AA", 450_000.0, 420_000.0, "investor"),
        ("EC1A1BB", 320_000.0, 310_000.0, "first_time_buyer"),
        ("M11AE",   195_000.0, 200_000.0, "home_mover"),
        ("LS11AA",  250_000.0, 245_000.0, "investor"),
        ("B11AA",   175_000.0, 180_000.0, "investor"),
        ("EH11BB",  220_000.0, 215_000.0, "investor"),
        ("CF101AA", 160_000.0, 165_000.0, "first_time_buyer"),
        ("BS11AA",  280_000.0, 275_000.0, "home_mover"),
    ]

    def _warm_up(self) -> None:
        """
        Warm up using historical UK macro snapshots — no API calls needed.
        Injects varied feature vectors so StandardScaler has real variance
        and SGDRegressor learns meaningful weights from the start.
        """
        from predictelligence.agents.data_agent import DataAgent

        logger.info("Predictelligence Engine warming up with historical macro data…")
        n = len(self._WARMUP_MACRO_HISTORY)

        # Temporarily patch DataAgent.run to inject historical data
        orig_run = DataAgent.run

        macro_idx = [0]

        def _inject_run(self_agent, state):
            idx = macro_idx[0] % n
            macro_idx[0] += 1
            boe, infl, temp, season_factor, avg_price, season = \
                PredictelligenceEngine._WARMUP_MACRO_HISTORY[idx]
            state.raw_data = {
                "boe_rate": boe,
                "inflation_rate": infl,
                "avg_temp": temp,
                "season_factor": season_factor,
                "uk_avg_price": avg_price,
                "boe_direction": "HOLDING",
                "inflation_trend": "STABLE" if infl < 3.0 else "ELEVATED",
                "season": season,
            }
            return state

        DataAgent.run = _inject_run

        try:
            cycles = max(self.WARMUP_CYCLES, n)
            for i in range(cycles):
                scenario = self._WARMUP_PROPERTIES[i % len(self._WARMUP_PROPERTIES)]
                postcode, val, comp, utype = scenario
                try:
                    self.pipeline.run(
                        postcode=postcode,
                        current_valuation=val,
                        comparable_average=comp,
                        user_type=utype,
                    )
                except Exception as exc:
                    logger.warning("Warm-up cycle %d failed: %s", i + 1, exc)
        finally:
            DataAgent.run = orig_run

        logger.info(
            "Warm-up complete. Model has seen %d training examples.",
            self.pipeline.model_agent._n_trained,
        )

    def analyse(
        self,
        postcode: str,
        current_valuation: float,
        comparable_average: float,
        user_type: str = "investor",
    ) -> Dict[str, Any]:
        """
        Run the full pipeline and return a clean result dict.
        Never raises — returns an error dict on failure.
        """
        try:
            state = self.pipeline.run(
                postcode=postcode,
                current_valuation=current_valuation,
                comparable_average=comparable_average,
                user_type=user_type,
            )

            return {
                "postcode": state.postcode,
                "current_valuation": state.current_valuation,
                "predicted_value": round(state.prediction, 0),
                "direction": state.direction,
                "predicted_change_pct": state.predicted_change_pct,
                "confidence": round(state.confidence, 1),
                "investment_signal": state.investment_signal,
                "composite_score": state.composite_score,
                "macro_signals": state.macro_signals,
                "user_insights": state.user_insights,
                "model_cycles": state.cycle,
                "model_ready": state.model_ready,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pipeline_errors": state.pipeline_errors,
            }

        except Exception as exc:
            logger.exception("Engine.analyse failed for postcode=%s: %s", postcode, exc)
            return {
                "postcode": postcode,
                "error": str(exc),
                "model_ready": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def get_history(self, postcode: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Return last N predictions for a postcode."""
        return self.db.prediction_history(postcode, limit=limit)

    def warm_up_complete(self) -> bool:
        """True if the model has completed at least WARMUP_CYCLES training runs."""
        return self.pipeline.model_agent._n_trained >= self.WARMUP_CYCLES

    def health(self) -> Dict[str, Any]:
        """Return engine health status."""
        uptime = datetime.now(timezone.utc) - self._startup_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return {
            "status": "ok",
            "model_cycles": self.pipeline.model_agent._n_trained,
            "model_ready": self.warm_up_complete(),
            "uptime": f"{hours:02d}:{minutes:02d}:{seconds:02d}",
        }
