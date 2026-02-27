"""Shared state dataclass that flows through the prediction pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class PipelineState:
    # Input
    postcode: str = "SW1A1AA"
    current_valuation: float = 285_000.0
    comparable_average: float = 285_000.0
    user_type: str = "investor"  # investor | first_time_buyer | home_mover

    # Raw data from APIs
    raw_data: Dict[str, Any] = field(default_factory=dict)

    # Feature engineering
    features: Optional[np.ndarray] = None
    feature_names: List[str] = field(default_factory=list)
    target: float = 285_000.0

    # Model outputs
    prediction: float = 0.0
    direction: str = "SIDEWAYS"         # UP | DOWN | SIDEWAYS
    confidence: float = 0.0            # 0-100
    investment_signal: str = "HOLD"    # BUY | HOLD | SELL
    composite_score: float = 0.5
    predicted_change_pct: float = 0.0

    # Enrichment
    macro_signals: Dict[str, Any] = field(default_factory=dict)
    user_insights: Dict[str, Any] = field(default_factory=dict)

    # Status
    model_ready: bool = False
    cycle: int = 0
    error: float = 0.0

    # Error tracking
    pipeline_errors: List[str] = field(default_factory=list)
