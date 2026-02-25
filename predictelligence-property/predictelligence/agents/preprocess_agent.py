from __future__ import annotations

from collections import deque

import numpy as np
from sklearn.preprocessing import StandardScaler

from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState


class PreprocessAgent(BaseAgent):
    def __init__(self):
        super().__init__("PreprocessAgent")
        self.scaler = StandardScaler()
        self.fitted = False
        self.boe_history = deque(maxlen=5)

    def run(self, state: PipelineState) -> PipelineState:
        d = state.raw_data
        boe = float(d.get("boe_rate", 5.25))
        inflation = float(d.get("inflation_rate", 3.8))
        self.boe_history.append(boe)

        inflation_prev = float(d.get("inflation_prev", inflation))
        inflation_momentum = inflation - inflation_prev
        rolling_boe_mean = float(np.mean(self.boe_history))

        features = np.array(
            [
                boe,
                inflation,
                10 - boe,
                np.log(boe + 1),
                inflation_momentum,
                float(d.get("avg_temp", 12.0)),
                float(d.get("season_factor", 0.8)),
                boe * inflation,
                ((10 - boe) / 10) * (1 - inflation / 20),
                rolling_boe_mean,
            ],
            dtype=float,
        ).reshape(1, -1)

        if not self.fitted:
            scaled = self.scaler.fit_transform(features)
            self.fitted = True
        else:
            scaled = self.scaler.transform(features)

        state.features = scaled
        state.feature_names = [
            "boe_rate",
            "inflation_rate",
            "rate_affordability_impact",
            "log_boe_rate",
            "inflation_momentum",
            "weather_temp",
            "season_factor",
            "rate_inflation_interaction",
            "affordability_score",
            "rolling_boe_mean",
        ]
        state.target = float(d.get("uk_avg_price", 285000.0))
        return state
