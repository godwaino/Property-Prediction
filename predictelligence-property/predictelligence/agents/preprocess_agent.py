from __future__ import annotations

from collections import deque

import numpy as np
from sklearn.preprocessing import StandardScaler

from ppd_sqlite import postcode_property_benchmark
from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState


PROPERTY_MAP = {
    "detached": 1.0,
    "semi-detached": 0.75,
    "terraced": 0.5,
    "flat": 0.25,
}


class PreprocessAgent(BaseAgent):
    def __init__(self):
        super().__init__("PreprocessAgent")
        self.scaler = StandardScaler()
        self.fitted = False
        self.boe_history = deque(maxlen=5)

    @staticmethod
    def _postcode_numeric(postcode: str) -> float:
        pc = postcode.replace(" ", "").upper()
        # stable postcode embedding via bounded hash
        return (sum((idx + 1) * ord(ch) for idx, ch in enumerate(pc)) % 1000) / 1000.0

    def run(self, state: PipelineState) -> PipelineState:
        d = state.raw_data
        boe = float(d.get("boe_rate", 5.25))
        inflation = float(d.get("inflation_rate", 3.8))
        self.boe_history.append(boe)

        inflation_prev = float(d.get("inflation_prev", inflation))
        inflation_momentum = inflation - inflation_prev
        rolling_boe_mean = float(np.mean(self.boe_history))

        bench = postcode_property_benchmark(state.postcode, state.property_type, state.bedrooms)
        local_median = float(bench.get("median_price", 285000.0))
        local_count = float(bench.get("count", 0.0))

        property_type_code = PROPERTY_MAP.get(str(state.property_type).lower(), 0.6)
        postcode_code = self._postcode_numeric(state.postcode)

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
                property_type_code,
                postcode_code,
                state.bedrooms,
                local_count,
                local_median / 1_000_000.0,
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
            "property_type_code",
            "postcode_code",
            "bedrooms",
            "local_sample_count",
            "local_median_price_m",
        ]

        # stronger target: blend local benchmark + UK HPI fallback
        uk_target = float(d.get("uk_avg_price", 285000.0))
        if local_count >= 2:
            state.target = (0.7 * local_median) + (0.3 * uk_target)
        else:
            state.target = uk_target
        return state
