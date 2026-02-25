"""
PreprocessAgent — engineers the 10 macroeconomic features used by the model.
Uses StandardScaler with fit-on-first-call pattern for incremental use.
Supports persistence via save()/load() so scaling parameters survive restarts.
"""
from __future__ import annotations

import math
import os
import pickle
from collections import deque
from typing import Deque, List, Optional

import numpy as np
from sklearn.preprocessing import StandardScaler

from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState

# Feature name constants (order matters — must stay consistent)
FEATURE_NAMES: List[str] = [
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


class PreprocessAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("PreprocessAgent")
        self._scaler: Optional[StandardScaler] = None
        self._scaler_fitted: bool = False
        self._boe_history: Deque[float] = deque(maxlen=5)
        self._prev_inflation: Optional[float] = None

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str) -> bool:
        """Pickle scaler state to disk."""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                pickle.dump({
                    "scaler": self._scaler,
                    "fitted": self._scaler_fitted,
                    "boe_history": list(self._boe_history),
                    "prev_inflation": self._prev_inflation,
                }, f)
            return True
        except Exception as exc:
            self.logger.warning("Could not save scaler: %s", exc)
            return False

    def load(self, path: str) -> bool:
        """Restore scaler state from disk."""
        if not os.path.exists(path):
            return False
        try:
            with open(path, "rb") as f:
                state = pickle.load(f)
            self._scaler = state["scaler"]
            self._scaler_fitted = state["fitted"]
            self._boe_history = deque(state.get("boe_history", []), maxlen=5)
            self._prev_inflation = state.get("prev_inflation")
            self.logger.info("Scaler restored from %s", path)
            return True
        except Exception as exc:
            self.logger.warning("Could not load scaler from %s: %s", path, exc)
            return False

    # ── Feature engineering ───────────────────────────────────────────────────

    def run(self, state: PipelineState) -> PipelineState:
        raw = state.raw_data

        boe_rate: float = float(raw.get("boe_rate", 5.25))
        inflation_rate: float = float(raw.get("inflation_rate", 3.8))
        weather_temp: float = float(raw.get("avg_temp", 12.0))
        season_factor: float = float(raw.get("season_factor", 0.8))
        uk_avg_price: float = float(raw.get("uk_avg_price", 285_000))

        self._boe_history.append(boe_rate)
        rolling_boe_mean = float(np.mean(list(self._boe_history)))

        rate_affordability_impact = 10.0 - boe_rate
        log_boe_rate = math.log(boe_rate + 1.0)

        if self._prev_inflation is not None:
            inflation_momentum = inflation_rate - self._prev_inflation
        else:
            inflation_momentum = 0.0
        self._prev_inflation = inflation_rate

        rate_inflation_interaction = boe_rate * inflation_rate
        affordability_score = (
            (10.0 - boe_rate) / 10.0 * (1.0 - inflation_rate / 20.0)
        )

        raw_features = np.array([
            boe_rate,
            inflation_rate,
            rate_affordability_impact,
            log_boe_rate,
            inflation_momentum,
            weather_temp,
            season_factor,
            rate_inflation_interaction,
            affordability_score,
            rolling_boe_mean,
        ], dtype=np.float64).reshape(1, -1)

        if self._scaler is None:
            self._scaler = StandardScaler()

        if not self._scaler_fitted:
            self._scaler.fit(raw_features)
            self._scaler_fitted = True

        scaled = self._scaler.transform(raw_features)

        state.features = scaled
        state.feature_names = FEATURE_NAMES
        state.target = uk_avg_price

        self.logger.debug(
            "Features engineered: boe=%.2f inflation=%.2f rolling_boe=%.2f",
            boe_rate, inflation_rate, rolling_boe_mean,
        )
        return state
