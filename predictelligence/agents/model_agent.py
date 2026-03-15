"""
ModelAgent — incremental SGDRegressor with persistence.
Uses partial_fit for online learning; saves model to disk after each cycle.
"""
from __future__ import annotations

import os
import pickle
import logging
from typing import Optional

from sklearn.linear_model import SGDRegressor

from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState

logger = logging.getLogger("predictelligence.ModelAgent")

# Direction thresholds
UP_THRESHOLD = 1.005    # predicted > uk_avg * 1.005 → UP
DOWN_THRESHOLD = 0.995  # predicted < uk_avg * 0.995 → DOWN

MIN_CYCLES_TO_PREDICT = 3

# UK average price fallback and extrapolation guards
_DEFAULT_UK_AVG = 285_000
_CLAMP_LOWER_RATIO = 0.60   # model cannot predict below 60% of UK avg anchor
_CLAMP_UPPER_RATIO = 1.40   # model cannot predict above 140% of UK avg anchor
_MIN_PROPERTY_PRICE = 50_000
_MAX_PROPERTY_PRICE = 5_000_000


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

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str) -> bool:
        """Pickle model weights and cycle count to disk."""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                pickle.dump({"model": self._model, "n_trained": self._n_trained}, f)
            return True
        except Exception as exc:
            self.logger.warning("Could not save model: %s", exc)
            return False

    def load(self, path: str) -> bool:
        """Restore model weights and cycle count from disk."""
        if not os.path.exists(path):
            return False
        try:
            with open(path, "rb") as f:
                state = pickle.load(f)
            self._model = state["model"]
            self._n_trained = state["n_trained"]
            self.logger.info("Model restored from %s (cycles=%d)", path, self._n_trained)
            return True
        except Exception as exc:
            self.logger.warning("Could not load model from %s: %s", path, exc)
            return False

    # ── Training + prediction ─────────────────────────────────────────────────

    def run(self, state: PipelineState) -> PipelineState:
        if state.features is None:
            self.logger.warning("No features available — skipping model step")
            return state

        X = state.features
        y = [state.target]

        # Incremental training
        self._model.partial_fit(X, y)
        self._n_trained += 1
        state.cycle = self._n_trained

        # Predict only after minimum warm-up cycles
        if self._n_trained < MIN_CYCLES_TO_PREDICT:
            state.model_ready = False
            state.prediction = state.current_valuation
            state.direction = "SIDEWAYS"
            state.confidence = 0.0
            state.predicted_change_pct = 0.0
            self.logger.debug("Model warming up (%d/%d cycles)", self._n_trained, MIN_CYCLES_TO_PREDICT)
            return state

        raw_prediction = float(self._model.predict(X)[0])

        # The model predicts UK average price (state.target).
        # Clamp within ±40% of the UK average anchor to prevent wild extrapolation.
        uk_avg_anchor = state.target if state.target > 0 else _DEFAULT_UK_AVG
        uk_prediction = max(raw_prediction, uk_avg_anchor * _CLAMP_LOWER_RATIO)
        uk_prediction = min(uk_prediction, uk_avg_anchor * _CLAMP_UPPER_RATIO)

        # Derive the % change in the UK market from this prediction,
        # then apply that same % change to the subject property's valuation.
        ratio = uk_prediction / uk_avg_anchor
        subject_price = state.current_valuation if state.current_valuation > 0 else uk_avg_anchor
        prediction = min(max(subject_price * ratio, _MIN_PROPERTY_PRICE), _MAX_PROPERTY_PRICE)

        state.model_ready = True
        state.prediction = prediction

        # Direction and change % are based on the UK market trend (ratio vs UK avg)
        state.predicted_change_pct = round((ratio - 1.0) * 100, 2)
        if ratio > UP_THRESHOLD:
            state.direction = "UP"
        elif ratio < DOWN_THRESHOLD:
            state.direction = "DOWN"
        else:
            state.direction = "SIDEWAYS"

        # Confidence grows with training data
        state.confidence = min(70.0 + self._n_trained * 2.0, 95.0)

        # Error vs target
        state.error = abs(prediction - state.target)

        self.logger.debug(
            "Cycle %d: predicted=£%,.0f direction=%s confidence=%.1f%%",
            self._n_trained, prediction, state.direction, state.confidence,
        )
        return state
