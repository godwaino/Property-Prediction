"""
Claude AI Integration Module
Uses Anthropic SDK to provide two capabilities:

1. extract_listing_details() — structured extraction from unstructured listing text
   when PAGE_MODEL scraping fails and key fields are missing.

2. generate_ai_narrative() — independent AI property narrative combining valuation,
   area risk, prediction signal, and personalized advice.
   Claude never sees the asking price to ensure an unbiased valuation.

Requires ANTHROPIC_API_KEY env var. All functions degrade gracefully to empty
dicts/strings when the API key is absent or any call fails.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"


# ── Client factory ─────────────────────────────────────────────────────────────

_client = None


def _get_client():
    """Return a cached Anthropic client, or None if key not set."""
    global _client
    if _client is not None:
        return _client
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import anthropic
        _client = anthropic.Anthropic(api_key=api_key)
        return _client
    except Exception as exc:
        logger.warning("Failed to create Anthropic client: %s", exc)
        return None


def is_claude_available() -> bool:
    """Return True if Anthropic API key is configured."""
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


# ── Listing extraction ─────────────────────────────────────────────────────────

def extract_listing_details(page_text: str, partial_facts: Dict[str, Any]) -> Dict[str, Any]:
    """
    Use Claude to extract structured property details from raw listing text.
    Called as a fallback when Rightmove PAGE_MODEL scraping fails.

    Returns a dict with any of these keys populated:
      price, bedrooms, bathrooms, property_type, tenure,
      epc_rating, floor_area_sqm, postcode, key_features, description
    Returns {} on any failure.
    """
    client = _get_client()
    if not client:
        return {}

    # Only extract fields that are missing
    missing = [
        k for k, v in partial_facts.items()
        if v is None or v == "" or v == []
    ]
    if not missing:
        return {}

    try:
        truncated_text = page_text[:4000] if page_text else ""
        prompt = (
            f"Extract property listing data from this text and return ONLY valid JSON.\n"
            f"Extract these fields if present: {', '.join(missing)}\n"
            f"For price, return an integer (e.g. 350000 for £350,000).\n"
            f"For floor_area_sqm, return a float in square metres.\n"
            f"For epc_rating, return a single letter A-G.\n"
            f"For key_features, return a list of strings.\n"
            f"If a field cannot be determined, omit it from the JSON.\n\n"
            f"TEXT:\n{truncated_text}"
        )

        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = (response.content[0].text or "").strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        extracted = json.loads(raw)
        if isinstance(extracted, dict):
            return extracted

    except json.JSONDecodeError:
        logger.debug("Claude extraction returned non-JSON")
    except Exception as exc:
        logger.warning("Claude extract_listing_details failed: %s", exc)

    return {}


# ── AI narrative generation ────────────────────────────────────────────────────

def generate_ai_narrative(
    facts: Dict[str, Any],
    valuation: Dict[str, Any],
    comps: List[Dict[str, Any]],
    score_data: Dict[str, Any],
    strategy: Dict[str, Any],
    enrichment: Optional[Dict[str, Any]] = None,
    prediction: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate a concise AI narrative analysis of the property (≤350 words).
    Claude receives property facts, comparable sales, area data, and ML signal
    but NEVER sees the asking price — ensuring an independent assessment.

    Returns a markdown string, or "" on failure/unavailability.
    """
    client = _get_client()
    if not client:
        return ""

    try:
        # Build context — deliberately exclude asking price
        comp_summary = _summarise_comps(comps)
        area_summary = _summarise_enrichment(enrichment)
        pred_summary = _summarise_prediction(prediction)
        score = score_data.get("score", 0)
        fair_mid = valuation.get("fair_value_mid") or score_data.get("fair_value_mid")
        fair_low = valuation.get("fair_value_low") or score_data.get("fair_value_low")
        fair_high = valuation.get("fair_value_high") or score_data.get("fair_value_high")
        user_type = facts.get("user_type", "investor")

        system_prompt = (
            "You are an expert UK property analyst. "
            "You must NOT ask about or reference the asking price — it has been deliberately withheld. "
            "Base your analysis only on the property characteristics, comparable sales, area data, "
            "and market prediction signal provided. "
            "Write in a professional but accessible tone suitable for a UK property buyer. "
            "Respond with a markdown-formatted analysis only — no preamble or sign-off."
        )

        user_prompt = f"""Analyse this UK property and provide a concise investment narrative.

## Property Details
- Address: {facts.get('address', 'Unknown')}
- Type: {facts.get('property_type', 'Unknown')}
- Bedrooms: {facts.get('bedrooms', 'Unknown')}
- Bathrooms: {facts.get('bathrooms', 'Unknown')}
- Tenure: {facts.get('tenure', 'Unknown')}
- Floor Area: {f"{facts.get('floor_area_sqm'):.0f} m²" if facts.get('floor_area_sqm') else 'Unknown'}
- EPC Rating: {facts.get('epc_rating', 'Unknown')}
- Key Features: {', '.join(facts.get('key_features', [])) or 'None listed'}

## Comparable Sales (Land Registry)
{comp_summary}

## Independent Valuation Range (from comparables)
- Low: £{fair_low:,} | Mid: £{fair_mid:,} | High: £{fair_high:,}
- Reasonableness score: {score}/100

## Area Data
{area_summary}

## ML Market Signal
{pred_summary}

## User Profile
{_user_type_guidance(user_type)}

Provide:
1. **Market Position** (1-2 sentences): How this property compares to local comparables and what the valuation range implies.
2. **Area Assessment** (1-2 sentences): Key area risk factors and how they affect the investment case.
3. **{_user_type_heading(user_type)}** (2-3 sentences): Tailored advice for a {user_type.replace('_', ' ')}.
4. **Key Risks** (bullet list, max 3 items): Most important considerations.

Keep the entire response under 350 words."""

        response = client.messages.create(
            model=MODEL,
            max_tokens=600,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        narrative = (response.content[0].text or "").strip()
        return narrative

    except Exception as exc:
        logger.warning("Claude generate_ai_narrative failed: %s", exc)
        return ""


# ── Helper formatters ──────────────────────────────────────────────────────────

def _summarise_comps(comps: List[Dict[str, Any]]) -> str:
    if not comps:
        return "No comparable sales found."
    lines = []
    for c in comps[:8]:
        price = c.get("price", 0)
        date = c.get("date", "")
        pcode = c.get("postcode", "")
        ptype = c.get("property_type", "")
        lines.append(f"- £{price:,} | {date} | {pcode} | {ptype}")
    return "\n".join(lines)


def _summarise_enrichment(enrichment: Optional[Dict[str, Any]]) -> str:
    if not enrichment:
        return "Area data not available."
    parts = []
    crime_sev = enrichment.get("crime_severity", "unknown")
    flood_sev = enrichment.get("flood_severity", "negligible")
    imd = enrichment.get("imd_decile")
    earnings = enrichment.get("median_earnings")
    planning = enrichment.get("planning_major_nearby", False)

    parts.append(f"- Crime: {crime_sev}")
    parts.append(f"- Flood risk: {flood_sev}")
    if imd:
        parts.append(f"- Deprivation: IMD decile {imd}/10 (10=least deprived)")
    if earnings:
        parts.append(f"- Median earnings: £{earnings:,.0f}/year")
    if planning:
        parts.append("- Major planning application nearby")

    flags = enrichment.get("area_flags", [])
    for flag in flags:
        parts.append(f"- ⚠ {flag}")

    return "\n".join(parts) if parts else "No area risk factors identified."


def _summarise_prediction(prediction: Optional[Dict[str, Any]]) -> str:
    if not prediction or prediction.get("model_ready") is False:
        return "ML model warming up — signal not yet available."
    direction = prediction.get("direction", "UNKNOWN")
    signal = prediction.get("investment_signal", "HOLD")
    confidence = prediction.get("confidence", 0)
    return f"Direction: {direction} | Signal: {signal} | Confidence: {confidence:.1f}%"


def _user_type_guidance(user_type: str) -> str:
    guidance = {
        "investor": "Focused on capital appreciation, rental yield, and buy-to-let viability.",
        "first_time_buyer": "Priority is affordability, mortgage eligibility, and long-term stability.",
        "home_mover": "Balance between lifestyle upgrade and financial prudence. Less focused on yield.",
    }
    return guidance.get(user_type, guidance["investor"])


def _user_type_heading(user_type: str) -> str:
    headings = {
        "investor": "Investment Case",
        "first_time_buyer": "Buyer Advice",
        "home_mover": "Move Advice",
    }
    return headings.get(user_type, "Investment Case")
