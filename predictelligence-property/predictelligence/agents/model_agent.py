from __future__ import annotations

from collections import deque

import numpy as np
from sklearn.linear_model import SGDRegressor

from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState


class ModelAgent(BaseAgent):
    def __init__(self):
        super().__init__("ModelAgent")
        self.fast_model = SGDRegressor(
            loss="huber",
            penalty="elasticnet",
            alpha=0.0005,
            l1_ratio=0.15,
            learning_rate="adaptive",
            eta0=0.01,
            max_iter=1,
            warm_start=True,
            average=True,
            random_state=42,
        )
        self.slow_model = SGDRegressor(
            loss="squared_error",
            penalty="l2",
            alpha=0.001,
            learning_rate="invscaling",
            eta0=0.005,
            power_t=0.25,
            max_iter=1,
            warm_start=True,
            average=True,
            random_state=7,
        )
        self.n_trained = 0
        self.error_window = deque(maxlen=25)

    def run(self, state: PipelineState) -> PipelineState:
        X = state.features
        y = np.array([state.target], dtype=float)

        self.fast_model.partial_fit(X, y)
        self.slow_model.partial_fit(X, y)
        self.n_trained += 1
        state.cycle = self.n_trained
        state.model_ready = self.n_trained >= 3

        if state.model_ready:
            pred_fast = float(self.fast_model.predict(X)[0])
            pred_slow = float(self.slow_model.predict(X)[0])
            pred = (0.65 * pred_fast) + (0.35 * pred_slow)
        else:
            pred = state.current_valuation

        # clip unrealistic outputs using valuation anchors
        floor = max(min(state.current_valuation, state.comparable_average) * 0.65, 50_000)
        cap = max(state.current_valuation, state.comparable_average) * 1.6
        pred = min(max(pred, floor), cap)

        state.prediction = pred

        cv = max(state.current_valuation, 1.0)
        if pred > cv * 1.005:
            state.direction = "UP"
        elif pred < cv * 0.995:
            state.direction = "DOWN"
        else:
            state.direction = "SIDEWAYS"

        state.predicted_change_pct = ((pred - cv) / cv) * 100
        state.error = abs(state.target - pred)
        self.error_window.append(state.error)

        if self.error_window:
            mean_err = float(np.mean(self.error_window))
            err_ratio = mean_err / max(state.current_valuation, 1.0)
        else:
            err_ratio = 0.1

        confidence_raw = 92 - (err_ratio * 240) + min(self.n_trained, 200) * 0.05
        state.confidence = max(45.0, min(confidence_raw, 95.0))
        return state
