from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np


@dataclass
class PipelineState:
    postcode: str = ""
    property_type: str = "semi-detached"
    bedrooms: int = 2
    current_valuation: float = 0.0
    comparable_average: float = 0.0
    raw_data: dict = field(default_factory=dict)
    features: np.ndarray = field(default_factory=lambda: np.array([]))
    feature_names: List[str] = field(default_factory=list)
    target: float = 0.0
    prediction: float = 0.0
    direction: str = "SIDEWAYS"
    confidence: float = 0.0
    investment_signal: str = "HOLD"
    composite_score: float = 0.0
    predicted_change_pct: float = 0.0
    macro_signals: Dict = field(default_factory=dict)
    user_insights: Dict = field(default_factory=dict)
    model_ready: bool = False
    cycle: int = 0
    error: float = 0.0
    user_type: str = "investor"
