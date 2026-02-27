"""
SignalAgent — converts model output into a weighted investment signal (BUY/HOLD/SELL)
and generates user-type-specific insights.
"""
from __future__ import annotations

from typing import Any, Dict

from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState

# ── Signal thresholds ──────────────────────────────────────────────────────────
BUY_THRESHOLD = 0.65
SELL_THRESHOLD = 0.45

# ── Weights for composite score ────────────────────────────────────────────────
W_PRICE_DIRECTION = 0.25
W_PREDICTED_GROWTH = 0.20
W_AFFORDABILITY = 0.20
W_INFLATION = 0.15
W_SEASON = 0.10
W_VALUATION_DISCOUNT = 0.10


class SignalAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("SignalAgent")

    def run(self, state: PipelineState) -> PipelineState:
        raw = state.raw_data
        boe_rate: float = float(raw.get("boe_rate", 5.25))
        inflation_rate: float = float(raw.get("inflation_rate", 3.8))
        season_factor: float = float(raw.get("season_factor", 0.8))

        # ── Component scores (each 0.0 – 1.0) ─────────────────────────────────

        # 1. Price direction
        dir_score = {"UP": 1.0, "SIDEWAYS": 0.5, "DOWN": 0.0}.get(state.direction, 0.5)

        # 2. Predicted growth (capped 0-1, where 10% growth = 1.0)
        growth_score = max(0.0, min(state.predicted_change_pct / 10.0, 1.0))

        # 3. Affordability trend (inverse of normalised BoE rate, scale 0-15%)
        affordability_score = max(0.0, min(1.0 - boe_rate / 15.0, 1.0))

        # 4. Inflation stability (inverse of normalised inflation, scale 0-10%)
        inflation_score = max(0.0, min(1.0 - inflation_rate / 10.0, 1.0))

        # 5. Season
        season_score = float(season_factor)

        # 6. Valuation discount (how much cheaper than comparables)
        comp_avg = state.comparable_average
        current = state.current_valuation
        if comp_avg > 0 and current > 0:
            discount = (comp_avg - current) / comp_avg
            discount_score = max(0.0, min(discount + 0.5, 1.0))  # 50% below = 1.0
        else:
            discount_score = 0.5

        # ── Weighted composite ────────────────────────────────────────────────
        composite = (
            W_PRICE_DIRECTION   * dir_score
            + W_PREDICTED_GROWTH  * growth_score
            + W_AFFORDABILITY     * affordability_score
            + W_INFLATION         * inflation_score
            + W_SEASON            * season_score
            + W_VALUATION_DISCOUNT * discount_score
        )
        composite = round(max(0.0, min(composite, 1.0)), 4)
        state.composite_score = composite

        # ── Investment signal ─────────────────────────────────────────────────
        if composite >= BUY_THRESHOLD:
            state.investment_signal = "BUY"
        elif composite >= SELL_THRESHOLD:
            state.investment_signal = "HOLD"
        else:
            state.investment_signal = "SELL"

        # ── Macro signals summary ─────────────────────────────────────────────
        state.macro_signals = {
            "boe_rate": boe_rate,
            "boe_direction": raw.get("boe_direction", "HOLDING"),
            "inflation_rate": inflation_rate,
            "inflation_trend": raw.get("inflation_trend", "ELEVATED"),
            "season": raw.get("season", "Autumn"),
            "affordability": "IMPROVING" if affordability_score > 0.6 else "PRESSURED",
            "season_factor": season_factor,
        }

        # ── User-type insights ────────────────────────────────────────────────
        state.user_insights = self._build_user_insights(state)

        self.logger.debug(
            "Signal: %s (composite=%.3f) dir=%s growth=%.2f%%",
            state.investment_signal,
            composite,
            state.direction,
            state.predicted_change_pct,
        )
        return state

    # ── User insight builders ──────────────────────────────────────────────────

    def _build_user_insights(self, state: PipelineState) -> Dict[str, Any]:
        user_type = state.user_type or "investor"
        boe_rate = float(state.raw_data.get("boe_rate", 5.25))
        inflation_rate = float(state.raw_data.get("inflation_rate", 3.8))
        season = state.raw_data.get("season", "Autumn")
        signal = state.investment_signal
        direction = state.direction
        pct = state.predicted_change_pct

        if user_type == "investor":
            return self._investor_insights(state, signal, direction, pct, boe_rate)
        elif user_type == "first_time_buyer":
            return self._ftb_insights(state, signal, direction, pct, boe_rate, inflation_rate, season)
        elif user_type == "home_mover":
            return self._mover_insights(state, signal, direction, pct, boe_rate, season)
        else:
            return self._investor_insights(state, signal, direction, pct, boe_rate)

    def _investor_insights(
        self, state: PipelineState, signal: str, direction: str, pct: float, boe_rate: float
    ) -> Dict[str, Any]:
        if signal == "BUY":
            headline = (
                f"Strong buy opportunity. Model projects {direction} trend "
                f"({'+'if pct>=0 else ''}{pct:.1f}%). Macro conditions support entry."
            )
        elif signal == "HOLD":
            headline = (
                f"Hold position. Market trending {direction} "
                f"({'+'if pct>=0 else ''}{pct:.1f}%). Monitor for rate changes."
            )
        else:
            headline = (
                f"Caution advised. Model projects {direction} pressure "
                f"({pct:.1f}%). Consider timing."
            )

        roi_estimate = round(pct + 4.5, 1)  # predicted capital + typical yield
        return {
            "headline": headline,
            "roi_estimate": roi_estimate,
            "rental_yield_context": (
                "Gross yields typically 4-6% in this market. "
                f"BoE rate at {boe_rate}% — BTL finance costs remain elevated."
            ),
            "hold_period_suggestion": (
                "5-7 year hold recommended for optimal capital growth cycle."
                if signal == "BUY"
                else "Wait for rate cycle to turn before committing capital."
            ),
        }

    def _ftb_insights(
        self, state: PipelineState, signal: str, direction: str,
        pct: float, boe_rate: float, inflation_rate: float, season: str
    ) -> Dict[str, Any]:
        if boe_rate > 5.0:
            affordability_outlook = (
                f"Mortgage affordability under pressure with BoE rate at {boe_rate}%. "
                "Consider fixed-rate products to lock in certainty."
            )
        else:
            affordability_outlook = (
                f"Affordability improving as BoE rate eases. "
                "Good time to explore mortgage options."
            )

        if direction == "UP":
            best_time = "Market trending up — acting sooner may save you money."
        elif direction == "DOWN":
            best_time = "Market showing softness — you may be able to negotiate."
        else:
            best_time = "Market stable — act when personally ready."

        return {
            "headline": (
                f"{'Market trending up — consider acting soon.' if direction == 'UP' else 'Stable conditions for first-time buyers.'}"
            ),
            "affordability_outlook": affordability_outlook,
            "best_time_to_buy": best_time,
            "stamp_duty_note": "First-time buyer relief may apply — consult a solicitor.",
        }

    def _mover_insights(
        self, state: PipelineState, signal: str, direction: str,
        pct: float, boe_rate: float, season: str
    ) -> Dict[str, Any]:
        if direction == "UP":
            market_timing = (
                "Your current property is likely appreciating too. "
                "Simultaneous move minimises timing risk."
            )
        elif direction == "DOWN":
            market_timing = (
                "A softening market means more negotiating power on purchases, "
                "but price your sale correctly."
            )
        else:
            market_timing = "Stable market — good conditions for a chain-free move."

        if signal == "BUY":
            negotiation = "Good time to buy. Make a confident first offer."
        else:
            negotiation = "Negotiate firmly — comparables support a lower entry."

        return {
            "headline": (
                f"Market is {direction.lower()}. "
                f"{'Now is a good time to act.' if signal == 'BUY' else 'Consider timing carefully.'}"
            ),
            "market_timing": market_timing,
            "negotiation_context": negotiation,
            "season_note": f"{season} market: {'active' if season in ('Spring','Summer') else 'slower — leverage buyer scarcity'}.",
        }
