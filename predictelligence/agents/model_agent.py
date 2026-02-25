"""
ModelAgent — incremental SGDRegressor for UK property price prediction.
Uses partial_fit for online learning; predicts once 3+ cycles have run.
"""
from __future__ import annotations

from sklearn.linear_model import SGDRegressor

from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState

# Direction thresholds
UP_THRESHOLD = 1.005    # predicted > current * 1.005 → UP
DOWN_THRESHOLD = 0.995  # predicted < current * 0.995 → DOWN

MIN_CYCLES_TO_PREDICT = 3


class ModelAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("ModelAgent")
        self._model = SGDRegressor(
            learning_rate="adaptive",
            eta0=0.01,
            max_iter=1,
            warm_start=True,
            tol=None,
            random_state=42,
        )
        self._n_trained: int = 0

    def run(self, state: PipelineState) -> PipelineState:
        if state.features is None:
            self.logger.warning("No features available — skipping model step")
            return state

        X = state.features
        y = [state.target]

        # ── Incremental training ──────────────────────────────────────────────
        self._model.partial_fit(X, y)
        self._n_trained += 1
        state.cycle = self._n_trained

        # ── Predict only after minimum training cycles ────────────────────────
        if self._n_trained < MIN_CYCLES_TO_PREDICT:
            state.model_ready = False
            state.prediction = state.current_valuation
            state.direction = "SIDEWAYS"
            state.confidence = 0.0
            state.predicted_change_pct = 0.0
            self.logger.debug("Model warming up (%d/%d cycles)", self._n_trained, MIN_CYCLES_TO_PREDICT)
            return state

        raw_prediction = float(self._model.predict(X)[0])

        # Guard against wild extrapolation — anchor within ±40% of target
        # This prevents cold-start divergence when features haven't varied yet
        target_anchor = state.target if state.target > 0 else 285_000
        prediction = max(raw_prediction, target_anchor * 0.60)
        prediction = min(prediction, target_anchor * 1.40)

        # Absolute floor / ceiling
        prediction = max(prediction, 50_000)
        prediction = min(prediction, 5_000_000)

        state.model_ready = True
        state.prediction = prediction

        # ── Direction ─────────────────────────────────────────────────────────
        current = state.current_valuation or state.target
        if current > 0:
            ratio = prediction / current
            if ratio > UP_THRESHOLD:
                state.direction = "UP"
            elif ratio < DOWN_THRESHOLD:
                state.direction = "DOWN"
            else:
                state.direction = "SIDEWAYS"
            state.predicted_change_pct = round((ratio - 1.0) * 100, 2)
        else:
            state.direction = "SIDEWAYS"
            state.predicted_change_pct = 0.0

        # ── Confidence grows with training data ───────────────────────────────
        state.confidence = min(70.0 + self._n_trained * 2.0, 95.0)

        # ── Error vs target ───────────────────────────────────────────────────
        state.error = abs(prediction - state.target)

        self.logger.debug(
            "Cycle %d: predicted=£%,.0f direction=%s confidence=%.1f%%",
            self._n_trained,
            prediction,
            state.direction,
            state.confidence,
        )
        return state
