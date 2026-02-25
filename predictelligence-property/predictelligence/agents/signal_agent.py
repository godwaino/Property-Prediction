from __future__ import annotations

from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState


class SignalAgent(BaseAgent):
    def __init__(self):
        super().__init__("SignalAgent")

    def run(self, state: PipelineState) -> PipelineState:
        direction_map = {"UP": 1.0, "SIDEWAYS": 0.5, "DOWN": 0.0}
        price_direction = direction_map.get(state.direction, 0.5)
        growth_score = max(0.0, min(state.predicted_change_pct / 10, 1.0))
        boe = float(state.raw_data.get("boe_rate", 5.25))
        infl = float(state.raw_data.get("inflation_rate", 3.8))
        aff_trend = max(0.0, min((10 - boe) / 10, 1.0))
        inflation_stability = max(0.0, min(1 - infl / 10, 1.0))
        season_factor = float(state.raw_data.get("season_factor", 0.8))
        valuation_discount = max(0.0, min((state.comparable_average - state.current_valuation) / max(state.comparable_average, 1), 1.0))

        composite = (
            price_direction * 0.25
            + growth_score * 0.20
            + aff_trend * 0.20
            + inflation_stability * 0.15
            + season_factor * 0.10
            + valuation_discount * 0.10
        )
        state.composite_score = round(composite, 4)

        if composite >= 0.65:
            state.investment_signal = "BUY"
        elif composite >= 0.45:
            state.investment_signal = "HOLD"
        else:
            state.investment_signal = "SELL"

        inflation_trend = "ELEVATED" if infl > 4.0 else "STABLE"
        boe_direction = "HOLDING"
        if boe < 4.5:
            boe_direction = "FALLING"
        elif boe > 5.5:
            boe_direction = "RISING"

        state.macro_signals = {
            "boe_rate": boe,
            "boe_direction": boe_direction,
            "inflation_rate": infl,
            "inflation_trend": inflation_trend,
            "season": state.raw_data.get("season", "Autumn"),
            "affordability": "IMPROVING" if aff_trend >= 0.45 else "PRESSURED",
        }

        self._insights(state)
        return state

    def _insights(self, state: PipelineState) -> None:
        ut = state.user_type
        if ut == "investor":
            state.user_insights = {
                "headline": f"{state.investment_signal} signal based on current macro-property alignment.",
                "roi_estimate": round(state.predicted_change_pct + 4.5, 2),
                "rental_yield_context": "Prime London yields remain compression-sensitive to rates.",
                "hold_period_suggestion": "12-24 months",
            }
        elif ut == "first_time_buyer":
            state.user_insights = {
                "headline": "Entry conditions are stabilising in your target segment.",
                "affordability_outlook": "Mortgage pressure eases as rates normalise.",
                "best_time_to_buy": "Monitor next 1-2 BoE updates for improved confidence.",
            }
        else:
            state.user_insights = {
                "headline": "Timing is balanced; negotiation edge matters more than speed.",
                "market_timing": "Prefer chains with motivated sellers this quarter.",
                "negotiation_context": "Use macro uncertainty to seek 2-4% price flexibility.",
            }
