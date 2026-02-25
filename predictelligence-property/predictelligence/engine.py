from __future__ import annotations

from datetime import datetime

from predictelligence.db_manager import DBManager
from predictelligence.pipeline import PropertyPipeline


class PredictelligenceEngine:
    def __init__(self):
        self.pipeline = PropertyPipeline()
        self.db = DBManager()
        self._warm_up_done = False
        self._warm_up()

    def _warm_up(self):
        for _ in range(3):
            self.pipeline.run("SW1A1AA", 285000, 285000, "investor", property_type="semi-detached", bedrooms=2)
        self._warm_up_done = True

    def analyse(self, postcode, current_valuation, comparable_average, user_type, property_type="semi-detached", bedrooms=2):
        state = self.pipeline.run(
            postcode,
            current_valuation,
            comparable_average,
            user_type,
            property_type=property_type,
            bedrooms=bedrooms,
        )
        return {
            "postcode": state.postcode,
            "property_type": state.property_type,
            "bedrooms": state.bedrooms,
            "current_valuation": float(current_valuation),
            "predicted_value": round(state.prediction, 2),
            "direction": state.direction,
            "predicted_change_pct": round(state.predicted_change_pct, 3),
            "confidence": round(state.confidence, 1),
            "investment_signal": state.investment_signal,
            "composite_score": state.composite_score,
            "macro_signals": state.macro_signals,
            "user_insights": state.user_insights,
            "model_cycles": state.cycle,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_history(self, postcode, limit=20):
        return self.db.prediction_history(postcode, limit)

    def warm_up_complete(self):
        latest = self.db.latest_prediction("SW1A1AA")
        return bool(latest and latest.get("cycle", 0) >= 3)
