from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import exp
from statistics import mean, pstdev
from typing import Dict, List, Tuple

from ppd_sqlite import get_comparable_records


@dataclass
class ValuationResult:
    estimated_value: float
    comparable_average: float
    confidence: float
    risk_flags: List[str]
    negotiation_strategy: str
    deal_verdict: str


USER_MULTIPLIERS = {
    "investor": 0.99,
    "first_time_buyer": 1.00,
    "home_mover": 1.01,
}

PROPERTY_TYPE_PREMIUM = {
    "detached": 0.12,
    "semi-detached": 0.04,
    "terraced": -0.02,
    "flat": -0.10,
}


def _months_since(date_sold: str) -> float:
    try:
        d = datetime.strptime(date_sold, "%Y-%m-%d")
        return max((datetime.utcnow() - d).days / 30.4, 0.0)
    except Exception:
        return 24.0


def _time_adjustment(months_old: float, annual_growth: float = 0.028) -> float:
    return (1 + annual_growth) ** (months_old / 12)


def _comparable_weight(subject_postcode: str, subject_bedrooms: int, row: Dict) -> float:
    postcode_match = 1.0 if row.get("postcode", "").replace(" ", "").upper() == subject_postcode else 0.0
    district_match = 1.0 if row.get("postcode_district", "") == _postcode_district(subject_postcode) else 0.0
    bedroom_gap = abs(int(row.get("bedrooms") or subject_bedrooms) - subject_bedrooms)
    months_old = _months_since(str(row.get("date_sold") or ""))

    # engineered similarity factors
    recency_factor = exp(-months_old / 18)
    bedroom_factor = exp(-bedroom_gap / 1.25)
    location_factor = 0.55 + (0.30 * district_match) + (0.15 * postcode_match)

    return max(recency_factor * bedroom_factor * location_factor, 0.03)


def _postcode_district(postcode: str) -> str:
    pc = postcode.replace(" ", "").upper()
    return "".join(ch for ch in pc if not ch.isdigit())[:3] or pc[:2]


def _engineer_valuation_features(
    postcode: str,
    property_type: str,
    bedrooms: int,
    comparable_rows: List[Dict],
) -> Tuple[float, float, float, int]:
    if not comparable_rows:
        return 0.0, 0.0, 55.0, 0

    subject_postcode = postcode.replace(" ", "").upper()
    subject_bedrooms = max(int(bedrooms or 2), 1)

    weighted_prices = []
    raw_prices = []
    weights = []

    for row in comparable_rows:
        base_price = float(row.get("price") or 0)
        if base_price <= 0:
            continue

        months_old = _months_since(str(row.get("date_sold") or ""))
        time_adj = _time_adjustment(months_old)

        comp_bedrooms = int(row.get("bedrooms") or subject_bedrooms)
        bedroom_adj = 1 + ((subject_bedrooms - comp_bedrooms) * 0.03)

        comp_type = str(row.get("property_type") or "").lower()
        type_adj = 1 + (PROPERTY_TYPE_PREMIUM.get(property_type.lower(), 0.0) - PROPERTY_TYPE_PREMIUM.get(comp_type, 0.0))

        feature_adjusted_price = base_price * time_adj * bedroom_adj * type_adj
        weight = _comparable_weight(subject_postcode, subject_bedrooms, row)

        weighted_prices.append(feature_adjusted_price * weight)
        raw_prices.append(feature_adjusted_price)
        weights.append(weight)

    if not weights:
        return 0.0, 0.0, 55.0, 0

    weighted_mean = sum(weighted_prices) / sum(weights)
    comparable_average = mean(raw_prices)

    dispersion = (pstdev(raw_prices) / comparable_average) if len(raw_prices) > 1 and comparable_average else 0.20
    effective_n = (sum(weights) ** 2) / max(sum(w * w for w in weights), 1e-6)
    confidence = max(45.0, min(94.0, 72 + (effective_n * 2.8) - (dispersion * 55)))

    return weighted_mean, comparable_average, round(confidence, 1), len(raw_prices)


def estimate_property_value(postcode: str, property_type: str, bedrooms: int, asking_price: float, user_type: str) -> ValuationResult:
    rows = get_comparable_records(postcode, property_type, bedrooms, limit=80)
    model_value, comparable_average, confidence, used = _engineer_valuation_features(postcode, property_type, bedrooms, rows)

    if used == 0:
        model_value = asking_price
        comparable_average = asking_price

    user_adj = USER_MULTIPLIERS.get(user_type, 1.0)
    estimated_value = model_value * user_adj

    risk_flags = generate_risk_flags(asking_price, estimated_value, postcode, confidence, used)
    negotiation_strategy = generate_negotiation_strategy(asking_price, estimated_value)
    deal_verdict = calculate_deal_verdict(asking_price, estimated_value, risk_flags)

    return ValuationResult(
        estimated_value=round(estimated_value, 2),
        comparable_average=round(comparable_average, 2),
        confidence=confidence,
        risk_flags=risk_flags,
        negotiation_strategy=negotiation_strategy,
        deal_verdict=deal_verdict,
    )


def generate_risk_flags(asking_price: float, estimated_value: float, postcode: str, confidence: float, comparable_count: int) -> List[str]:
    flags: List[str] = []
    premium = (asking_price - estimated_value) / max(estimated_value, 1)

    if premium > 0.10:
        flags.append("Asking price is >10% above comparable-feature valuation.")
    elif premium > 0.05:
        flags.append("Asking price sits at a noticeable premium to local comparables.")

    if comparable_count < 4:
        flags.append("Low comparable depth for this postcode/type profile.")

    if confidence < 65:
        flags.append("Confidence is moderate due to spread/recency of comparables.")

    if postcode.strip().upper().startswith("E"):
        flags.append("East-London submarkets can exhibit higher short-term volatility.")

    return flags


def calculate_deal_verdict(asking_price: float, estimated_value: float, risk_flags: List[str]) -> str:
    delta = (estimated_value - asking_price) / max(asking_price, 1)
    risk_penalty = min(len(risk_flags) * 0.02, 0.10)
    adjusted_edge = delta - risk_penalty

    if adjusted_edge >= 0.06:
        return "STRONG BUY"
    if adjusted_edge >= 0.01:
        return "BUY"
    if adjusted_edge > -0.04:
        return "NEGOTIATE"
    return "AVOID"


def generate_negotiation_strategy(asking_price: float, estimated_value: float) -> str:
    premium = (asking_price - estimated_value) / max(estimated_value, 1)
    if premium > 0.10:
        return "Lead with a data-backed offer 8-10% below asking and justify with recency-adjusted comparables."
    if premium > 0.03:
        return "Open 4-6% below asking and escalate using comparable bedroom/time-adjusted evidence."
    return "Offer near fair value and negotiate on speed, completion certainty, and fixtures."


def serialize_result(result: ValuationResult) -> Dict:
    return {
        "estimated_value": result.estimated_value,
        "comparable_average": result.comparable_average,
        "confidence": result.confidence,
        "risk_flags": result.risk_flags,
        "negotiation_strategy": result.negotiation_strategy,
        "deal_verdict": result.deal_verdict,
    }
