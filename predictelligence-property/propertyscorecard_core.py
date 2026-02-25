from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ppd_sqlite import get_comparable_prices


@dataclass
class ValuationResult:
    estimated_value: float
    comparable_average: float
    confidence: float
    risk_flags: List[str]
    negotiation_strategy: str
    deal_verdict: str


USER_MULTIPLIERS = {
    "investor": 0.98,
    "first_time_buyer": 1.0,
    "home_mover": 1.01,
}


def estimate_property_value(postcode: str, property_type: str, bedrooms: int, asking_price: float, user_type: str) -> ValuationResult:
    comparables = get_comparable_prices(postcode, property_type)
    comparable_average = sum(comparables) / len(comparables) if comparables else asking_price

    bedroom_adjustment = 1 + (max(bedrooms, 1) - 2) * 0.04
    type_adjustment = {
        "detached": 1.15,
        "semi-detached": 1.04,
        "terraced": 0.96,
        "flat": 0.9,
    }.get(property_type.lower(), 1.0)
    user_adj = USER_MULTIPLIERS.get(user_type, 1.0)

    estimated_value = comparable_average * bedroom_adjustment * type_adjustment * user_adj
    confidence = 82.0 if comparables else 68.0

    risk_flags = generate_risk_flags(asking_price, estimated_value, postcode)
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


def generate_risk_flags(asking_price: float, estimated_value: float, postcode: str) -> List[str]:
    flags = []
    premium = (asking_price - estimated_value) / max(estimated_value, 1)
    if premium > 0.1:
        flags.append("Asking price appears materially above estimated value.")
    if postcode.strip().upper().startswith("E"):
        flags.append("Higher volatility district detected in this postcode area.")
    if estimated_value < 150000:
        flags.append("Limited liquidity band; resale timing may be slower.")
    return flags


def calculate_deal_verdict(asking_price: float, estimated_value: float, risk_flags: List[str]) -> str:
    delta = (estimated_value - asking_price) / max(asking_price, 1)
    penalty = min(len(risk_flags) * 0.03, 0.12)
    adjusted = delta - penalty
    if adjusted >= 0.05:
        return "STRONG BUY"
    if adjusted >= 0.0:
        return "BUY"
    if adjusted > -0.05:
        return "NEGOTIATE"
    return "AVOID"


def generate_negotiation_strategy(asking_price: float, estimated_value: float) -> str:
    if asking_price > estimated_value * 1.08:
        return "Open 8-10% below asking; anchor on local comparables and renovation risks."
    if asking_price > estimated_value:
        return "Open 4-6% below asking; push for fixtures or seller-paid costs."
    return "Offer close to asking with speed/certainty incentives to win quickly."


def serialize_result(result: ValuationResult) -> Dict:
    return {
        "estimated_value": result.estimated_value,
        "comparable_average": result.comparable_average,
        "confidence": result.confidence,
        "risk_flags": result.risk_flags,
        "negotiation_strategy": result.negotiation_strategy,
        "deal_verdict": result.deal_verdict,
    }
