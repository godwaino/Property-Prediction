"""
Property Scorecard Core — UK Property Analysis Engine
Scrapes Rightmove listings and analyses them against Land Registry comparables.
Enhanced with: IQR outlier filtering, comp similarity scoring,
location risk adjustments, and red flags.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

try:
    from ppd_sqlite import find_comps_sqlite, Comp
    HAS_PPD = True
except ImportError:
    HAS_PPD = False


# ─── helpers ──────────────────────────────────────────────────────────────────

def sqft_to_sqm(sqft: float) -> float:
    return sqft * 0.0929


def sqm_to_sqft(sqm: float) -> float:
    return sqm * 10.7639


def median(values: List[float]) -> float:
    return statistics.median(values) if values else 0.0


def quantile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = (len(s) - 1) * q
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] + frac * (s[hi] - s[lo])


def money_int(text: str) -> Optional[int]:
    if not text:
        return None
    cleaned = re.sub(r"[£,\s]", "", str(text))
    m = re.search(r"\d+", cleaned)
    return int(m.group()) if m else None


def safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ─── data model ───────────────────────────────────────────────────────────────

@dataclass
class ListingFacts:
    url: str = ""
    property_id: str = ""
    address: str = ""
    price: Optional[int] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    property_type: Optional[str] = None
    tenure: Optional[str] = None
    floor_area_sqm: Optional[float] = None
    epc_rating: Optional[str] = None
    postcode: Optional[str] = None
    key_features: List[str] = field(default_factory=list)
    description: str = ""


# ─── scraping ─────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.rightmove.co.uk/",
}


def fetch_rightmove_html(url: str, timeout: int = 15) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    html = resp.text
    block_signals = [
        "Access to this page has been denied",
        "cf-browser-verification",
        "robot or automated browser",
        "Just a moment",
    ]
    for sig in block_signals:
        if sig.lower() in html.lower():
            raise RuntimeError(
                "Rightmove is blocking datacenter IPs. "
                "Try running locally or use a residential proxy."
            )
    return html


def _extract_property_id(url: str) -> str:
    m = re.search(r"properties/(\d+)", url)
    return m.group(1) if m else ""


def _parse_page_model(html: str) -> Optional[Dict[str, Any]]:
    """Try to extract Rightmove's PAGE_MODEL JS object."""
    m = re.search(r"window\.PAGE_MODEL\s*=\s*(\{.+?\});", html, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _parse_jsonld(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
    """Try JSON-LD structured data."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            if isinstance(data, list):
                data = data[0]
            if data.get("@type") in ("Product", "Offer", "RealEstateListing"):
                return data
        except Exception:
            pass
    return None


def parse_listing(url: str, html: str) -> ListingFacts:
    facts = ListingFacts(url=url, property_id=_extract_property_id(url))
    soup = BeautifulSoup(html, "lxml")

    # ── Try PAGE_MODEL first (most reliable) ──
    pm = _parse_page_model(html)
    if pm:
        try:
            prop = pm.get("propertyData") or pm.get("property") or {}
            address_data = prop.get("address") or {}
            facts.address = (
                address_data.get("displayAddress")
                or address_data.get("outcode")
                or ""
            )
            facts.postcode = address_data.get("postcode") or _infer_postcode(facts.address)

            # price
            prices = prop.get("prices") or prop.get("price") or {}
            if isinstance(prices, dict):
                facts.price = money_int(str(prices.get("primaryPrice") or prices.get("amount") or ""))
            elif isinstance(prices, (int, float)):
                facts.price = int(prices)

            # bedrooms / bathrooms
            facts.bedrooms = safe_int(prop.get("bedrooms"), None)
            facts.bathrooms = safe_int(prop.get("bathrooms"), None)
            if facts.bedrooms == 0:
                facts.bedrooms = None

            # property type / tenure
            facts.property_type = (
                prop.get("propertySubType")
                or prop.get("propertyType")
                or ""
            )
            tenure_data = prop.get("tenure") or {}
            if isinstance(tenure_data, dict):
                facts.tenure = tenure_data.get("tenureType") or tenure_data.get("display") or ""
            else:
                facts.tenure = str(tenure_data) if tenure_data else ""

            # floor area
            size = prop.get("sizings") or []
            for s in size:
                if "sqm" in str(s).lower() or "m²" in str(s).lower():
                    facts.floor_area_sqm = safe_float(s.get("minimumSize") or s.get("size"))
                    break

            # EPC
            epc = prop.get("epcGraphs") or prop.get("energyEfficiency") or {}
            if isinstance(epc, list) and epc:
                epc = epc[0]
            if isinstance(epc, dict):
                facts.epc_rating = epc.get("rating") or epc.get("ercRating") or ""

            # key features
            facts.key_features = prop.get("keyFeatures") or []
        except Exception:
            pass  # fall through to HTML parsing

    # ── HTML fallback ──
    if not facts.price:
        price_tag = (
            soup.find("span", {"data-testid": "price"})
            or soup.find(class_=re.compile(r"price", re.I))
        )
        if price_tag:
            facts.price = money_int(price_tag.get_text())

    if not facts.address:
        addr_tag = soup.find("address") or soup.find(class_=re.compile(r"address", re.I))
        if addr_tag:
            facts.address = addr_tag.get_text(strip=True)
            facts.postcode = _infer_postcode(facts.address)

    if not facts.bedrooms:
        bed_tag = soup.find(string=re.compile(r"\d+\s*bed", re.I))
        if bed_tag:
            m = re.search(r"(\d+)\s*bed", str(bed_tag), re.I)
            if m:
                facts.bedrooms = int(m.group(1))

    # key features from HTML
    if not facts.key_features:
        feat_list = soup.find("ul", class_=re.compile(r"feature", re.I))
        if feat_list:
            facts.key_features = [li.get_text(strip=True) for li in feat_list.find_all("li")]

    return facts


def _infer_postcode(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(
        r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b",
        text.upper(),
    )
    return m.group(1).strip() if m else None


# ─── IQR outlier filtering ────────────────────────────────────────────────────

def filter_outliers_iqr(prices: List[float]) -> List[float]:
    """Remove prices outside Q1 - 1.5×IQR and Q3 + 1.5×IQR."""
    if len(prices) < 4:
        return prices
    q1 = quantile(prices, 0.25)
    q3 = quantile(prices, 0.75)
    iqr = q3 - q1
    lo = q1 - 1.5 * iqr
    hi = q3 + 1.5 * iqr
    filtered = [p for p in prices if lo <= p <= hi]
    return filtered if filtered else prices  # never return empty list


# ─── comp similarity scoring ──────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def score_comp_similarity(
    comp: Any,
    facts: "ListingFacts",
    avg_comp_price: float,
    comp_lat: Optional[float] = None,
    comp_lng: Optional[float] = None,
    prop_lat: Optional[float] = None,
    prop_lng: Optional[float] = None,
) -> int:
    """
    Score 0-100 how similar a comp is to the subject property.
      Type match:      0 or 30 pts
      Price proximity: 0-30 pts (inversely proportional to % deviation from avg)
      Recency:         0-20 pts (newer comps score higher)
      Distance:        0-20 pts (closer comps score higher)
    """
    score = 0

    # Type match (+30)
    comp_type = (
        comp.property_type if hasattr(comp, "property_type") else comp.get("property_type", "")
    ) or ""
    prop_type = facts.property_type or ""
    if comp_type.lower() == prop_type.lower() and comp_type:
        score += 30

    # Price proximity (+30)
    comp_price = float(comp.price if hasattr(comp, "price") else comp.get("price", 0) or 0)
    if avg_comp_price > 0 and comp_price > 0:
        pct_diff = abs(comp_price - avg_comp_price) / avg_comp_price
        price_pts = max(0, 30 - int(pct_diff * 100))
        score += price_pts

    # Recency (+20): comps within 12 months get full points, decay over 36 months
    comp_date = comp.date if hasattr(comp, "date") else comp.get("date", "")
    if comp_date:
        try:
            comp_dt = datetime.fromisoformat(str(comp_date)[:10])
            months_ago = (datetime.now() - comp_dt).days / 30.44
            if months_ago <= 12:
                score += 20
            elif months_ago <= 24:
                score += 12
            elif months_ago <= 36:
                score += 6
        except ValueError:
            pass

    # Distance (+20): only if we have coordinates for both
    if all(v is not None for v in [comp_lat, comp_lng, prop_lat, prop_lng]):
        try:
            km = _haversine_km(prop_lat, prop_lng, comp_lat, comp_lng)
            if km <= 0.25:
                score += 20
            elif km <= 0.5:
                score += 15
            elif km <= 1.0:
                score += 10
            elif km <= 2.0:
                score += 5
        except Exception:
            pass

    return min(100, score)


# ─── valuation ────────────────────────────────────────────────────────────────

BASELINE_SQM = 68.0  # UK average floor area


def estimate_value_from_comps(
    comps: List[Any],
    floor_area_sqm: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    if not comps:
        return None

    prices = [c.price if hasattr(c, "price") else c.get("price", 0) for c in comps]
    prices = [float(p) for p in prices if p and p > 10_000]
    if not prices:
        return None

    # IQR outlier removal before valuation
    prices = filter_outliers_iqr(prices)

    # Light-touch size adjustment (square-root curve, clamped 0.92–1.10)
    if floor_area_sqm and floor_area_sqm > 20:
        raw_adj = math.sqrt(floor_area_sqm / BASELINE_SQM)
        adj = max(0.92, min(1.10, raw_adj))
        prices = [p * adj for p in prices]

    low = int(quantile(prices, 0.25))
    mid = int(median(prices))
    high = int(quantile(prices, 0.75))

    return {
        "comp_count": len(prices),
        "fair_value_low": low,
        "fair_value_mid": mid,
        "fair_value_high": high,
    }


# ─── scoring ──────────────────────────────────────────────────────────────────

SCORE_LABELS = [
    (85, "Excellent value — strong buy signal"),
    (70, "Good value — priced reasonably"),
    (55, "Fair pricing — within normal range"),
    (40, "Slightly above market — negotiate"),
    (25, "Stretch pricing — proceed cautiously"),
    (0,  "Significantly overpriced — high risk"),
]


def reasonableness_score(
    facts: "ListingFacts",
    valuation: Optional[Dict[str, Any]],
    enrichment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    score = 0
    notes: List[str] = []
    red_flags: List[Dict[str, str]] = []
    asking = facts.price or 0
    mid = (valuation or {}).get("fair_value_mid") or 0

    # 1. Price deviation vs comparables (40 pts)
    if asking and mid:
        ratio = asking / mid
        if ratio <= 0.90:
            score += 40
            notes.append("Priced well below comparables — strong value")
        elif ratio <= 0.97:
            score += 33
            notes.append("Slightly below comparable average")
        elif ratio <= 1.03:
            score += 26
            notes.append("In line with comparable sales")
        elif ratio <= 1.10:
            score += 16
            notes.append("Above comparable average — room to negotiate")
        elif ratio <= 1.20:
            score += 6
            notes.append("Significantly above comparables — negotiate hard")
        else:
            score += 0
            notes.append("Substantially overpriced vs comparables")
    else:
        score += 10  # partial credit when no comps
        notes.append("No comparables found — price reasonableness unverified")

    # 2. Data completeness (20 pts)
    completeness = sum([
        bool(facts.price),
        bool(facts.bedrooms),
        bool(facts.property_type),
        bool(facts.tenure),
        bool(facts.floor_area_sqm),
        bool(facts.epc_rating),
    ])
    comp_score = int(completeness / 6 * 20)
    score += comp_score
    if completeness < 3:
        notes.append("Limited data — analysis confidence reduced")

    # 3. Tenure (15 pts)
    tenure = (facts.tenure or "").lower()
    if "freehold" in tenure:
        score += 15
    elif "share of freehold" in tenure:
        score += 12
    elif "leasehold" in tenure:
        score += 6
        notes.append("Leasehold — check remaining lease length")
        red_flags.append({
            "flag": "Leasehold tenure",
            "impact": "Lease <80 years can cost £10k–£50k+ to extend; check lease length urgently",
            "severity": "medium",
        })
    else:
        score += 8

    # 4. EPC rating (15 pts)
    epc = (facts.epc_rating or "").upper().strip()
    epc_scores = {"A": 15, "B": 13, "C": 10, "D": 7, "E": 4, "F": 2, "G": 0}
    score += epc_scores.get(epc, 5)
    if epc in ("F", "G"):
        notes.append("Poor EPC rating — energy costs will be high")
        red_flags.append({
            "flag": f"Poor EPC rating ({epc})",
            "impact": "Energy bills may be £1,500–£3,000/year higher than a C-rated equivalent; retrofitting could cost £10k–£30k",
            "severity": "high",
        })
    elif epc in ("A", "B"):
        notes.append("Excellent EPC — low energy bills")

    # 5. Market behaviour indicators (10 pts)
    feats_text = " ".join(facts.key_features).lower()
    if "reduced" in feats_text or "price reduced" in feats_text:
        score += 8
        notes.append("Price has been reduced — seller motivated")
    elif any(w in feats_text for w in ["guide price", "offers in excess"]):
        score += 4
        notes.append("Guide price format — competitive offers expected")
    else:
        score += 6

    base_score = min(100, max(0, score))
    score = base_score

    # 6. Location risk adjustment from enrichment data
    area_adj_pts = 0
    area_data_summary: Dict[str, Any] = {}

    if enrichment:
        area_adj_pct = enrichment.get("area_score_adjustment", 0.0)
        if area_adj_pct:
            # Convert % adjustment to pts (0.5 multiplier keeps adjustments modest)
            area_adj_pts = round(area_adj_pct * 0.5)
            score += area_adj_pts

        area_flags = enrichment.get("area_flags", [])
        notes.extend(area_flags)

        # Convert area flags into red_flags with impact estimates
        flood_sev = enrichment.get("flood_severity", "negligible")
        if flood_sev in ("high", "severe"):
            red_flags.append({
                "flag": f"High flood risk ({flood_sev})",
                "impact": "Can reduce resale value 3–6%; buildings insurance premium significantly higher",
                "severity": "high",
            })
        elif flood_sev == "medium":
            red_flags.append({
                "flag": "Medium flood risk",
                "impact": "Potential insurance premium increase of £200–£800/year",
                "severity": "medium",
            })

        imd_decile = enrichment.get("imd_decile")
        if imd_decile is not None and imd_decile <= 2:
            red_flags.append({
                "flag": f"Highly deprived area (IMD decile {imd_decile}/10)",
                "impact": "May limit capital appreciation; higher void risk for BTL investors",
                "severity": "medium",
            })

        crime_sev = enrichment.get("crime_severity", "unknown")
        if crime_sev == "high":
            red_flags.append({
                "flag": "High crime area",
                "impact": "Higher insurance costs; potential impact on tenant/buyer pool",
                "severity": "medium",
            })

        if enrichment.get("planning_major_nearby"):
            red_flags.append({
                "flag": "Major planning application nearby",
                "impact": "Review impact — could affect views, traffic, or neighbourhood character",
                "severity": "low",
            })

        area_data_summary = {
            "crime_severity": enrichment.get("crime_severity", "unknown"),
            "crime_count_12m": enrichment.get("crime_count_12m"),
            "flood_severity": enrichment.get("flood_severity", "negligible"),
            "imd_decile": imd_decile,
            "planning_major_nearby": enrichment.get("planning_major_nearby", False),
            "median_earnings": enrichment.get("median_earnings"),
            "area_flags": area_flags,
            "fetch_errors": enrichment.get("fetch_errors", []),
        }

    score = min(100, max(0, score))

    label = SCORE_LABELS[-1][1]
    for threshold, lbl in SCORE_LABELS:
        if score >= threshold:
            label = lbl
            break

    return {
        "score": score,
        "base_score": base_score,
        "area_adjustment_pts": area_adj_pts,
        "label": label,
        "notes": notes,
        "red_flags": red_flags,
        "area_data": area_data_summary,
        "fair_value_low": (valuation or {}).get("fair_value_low"),
        "fair_value_mid": (valuation or {}).get("fair_value_mid"),
        "fair_value_high": (valuation or {}).get("fair_value_high"),
        "comp_count": (valuation or {}).get("comp_count", 0),
    }


# ─── offer strategy ───────────────────────────────────────────────────────────

def offer_strategy(
    facts: ListingFacts,
    valuation: Optional[Dict[str, Any]],
    score: int,
) -> Dict[str, Any]:
    mid = (valuation or {}).get("fair_value_mid") or facts.price or 0
    low = (valuation or {}).get("fair_value_low") or mid
    asking = facts.price or mid

    # Anchor at ~95% of fair-mid, rounded to nearest £1k
    anchor_raw = mid * 0.95
    anchor = int(round(anchor_raw / 1000) * 1000)

    # Range based on score
    if score >= 70:
        range_pct = 0.97  # strong position, bid closer to asking
    elif score >= 50:
        range_pct = 0.94
    else:
        range_pct = 0.90  # low score, bid harder

    range_low = int(round(low * range_pct / 1000) * 1000)
    range_high = int(round(mid * 0.98 / 1000) * 1000)

    if score >= 75:
        tactic = "Competitive market — move quickly. Offer at or near anchor."
    elif score >= 55:
        tactic = "Room to negotiate. Open at anchor, be prepared to go to mid."
    else:
        tactic = "Overpriced — anchor low and justify with comparables. Walk away if seller unmoved."

    return {
        "anchor_offer": anchor,
        "offer_range_low": range_low,
        "offer_range_high": range_high,
        "tactic": tactic,
        "asking_discount_pct": round((1 - anchor / asking) * 100, 1) if asking else 0,
    }


# ─── markdown report ──────────────────────────────────────────────────────────

def _fmt_money(v: Optional[int]) -> str:
    if v is None:
        return "—"
    return f"£{v:,}"


def build_md_report(
    facts: "ListingFacts",
    comps: List[Any],
    valuation: Optional[Dict[str, Any]],
    score_data: Dict[str, Any],
    strategy: Dict[str, Any],
    ai_narrative: str = "",
) -> str:
    ts = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    adj_pts = score_data.get("area_adjustment_pts", 0)
    adj_label = f" ({adj_pts:+d} pts from area risk)" if adj_pts else ""

    lines = [
        f"# Property Scorecard Report",
        f"**Generated:** {ts}",
        f"**Source:** {facts.url}",
        "",
        "---",
        "",
        "## Property Facts",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Address | {facts.address or '—'} |",
        f"| Asking Price | {_fmt_money(facts.price)} |",
        f"| Bedrooms | {facts.bedrooms or '—'} |",
        f"| Bathrooms | {facts.bathrooms or '—'} |",
        f"| Type | {facts.property_type or '—'} |",
        f"| Tenure | {facts.tenure or '—'} |",
        f"| Floor Area | {f'{facts.floor_area_sqm:.0f} m²' if facts.floor_area_sqm else '—'} |",
        f"| EPC Rating | {facts.epc_rating or '—'} |",
        "",
        "## Valuation Summary",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Fair Value (Low) | {_fmt_money(score_data.get('fair_value_low'))} |",
        f"| Fair Value (Mid) | {_fmt_money(score_data.get('fair_value_mid'))} |",
        f"| Fair Value (High) | {_fmt_money(score_data.get('fair_value_high'))} |",
        f"| Reasonableness Score | {score_data['score']}/100{adj_label} — {score_data['label']} |",
        f"| Comparables Used | {score_data.get('comp_count', 0)} |",
        "",
        "## Offer Strategy",
        f"- **Anchor offer:** {_fmt_money(strategy.get('anchor_offer'))}",
        f"- **Offer range:** {_fmt_money(strategy.get('offer_range_low'))} – {_fmt_money(strategy.get('offer_range_high'))}",
        f"- **Implied discount from asking:** {strategy.get('asking_discount_pct', 0):.1f}%",
        f"- **Tactic:** {strategy.get('tactic', '')}",
        "",
        "## Analysis Notes",
    ]
    for note in score_data.get("notes", []):
        lines.append(f"- {note}")

    # Red flags section
    red_flags = score_data.get("red_flags", [])
    if red_flags:
        lines += ["", "## Red Flags"]
        for rf in red_flags:
            sev = rf.get("severity", "").upper()
            lines.append(f"- **[{sev}] {rf.get('flag', '')}**: {rf.get('impact', '')}")

    # Area risk section
    area_data = score_data.get("area_data", {})
    if area_data:
        lines += ["", "## Area Risk Factors"]
        if area_data.get("crime_severity") and area_data["crime_severity"] != "unknown":
            count_str = f" ({area_data['crime_count_12m']} incidents in 6 months)" if area_data.get("crime_count_12m") else ""
            lines.append(f"- **Crime:** {area_data['crime_severity'].title()}{count_str}")
        if area_data.get("flood_severity", "negligible") != "negligible":
            lines.append(f"- **Flood risk:** {area_data['flood_severity'].title()}")
        if area_data.get("imd_decile") is not None:
            lines.append(f"- **Deprivation:** IMD decile {area_data['imd_decile']}/10 (10 = least deprived)")
        if area_data.get("median_earnings"):
            lines.append(f"- **Median local earnings:** £{area_data['median_earnings']:,.0f}/year")
        if area_data.get("planning_major_nearby"):
            lines.append("- **Planning:** Major development application nearby")
        if adj_pts:
            lines.append(f"- **Score adjustment:** {adj_pts:+d} points from area risk factors")

    # AI narrative section
    if ai_narrative:
        lines += ["", "## AI Analysis", ai_narrative]

    if comps:
        lines += [
            "",
            "## Comparable Sales (Land Registry)",
            "| Price | Date | Postcode | Type |",
            "|-------|------|----------|------|",
        ]
        for c in comps[:10]:
            price = c.price if hasattr(c, "price") else c.get("price", "")
            date = c.date if hasattr(c, "date") else c.get("date", "")
            postcode = c.postcode if hasattr(c, "postcode") else c.get("postcode", "")
            ptype = c.property_type if hasattr(c, "property_type") else c.get("property_type", "")
            lines.append(f"| {_fmt_money(price)} | {date} | {postcode} | {ptype} |")

    lines += [
        "",
        "---",
        "*This report is for educational purposes only and does not constitute financial or professional valuation advice.*",
    ]
    return "\n".join(lines)


# ─── main entry point ─────────────────────────────────────────────────────────

def run_propertyscorecard(
    url: str,
    ppd_sqlite_path: Optional[str] = None,
    user_type: str = "investor",
    enrich_location: bool = True,
    use_claude: bool = True,
) -> Dict[str, Any]:
    """
    Main analysis entry point. Returns a dict with:
      facts, comps, valuation, md_report, created_at_utc, enrichment (optional),
      ai_narrative (optional)
    """
    import concurrent.futures
    import os

    ts = datetime.now(timezone.utc).isoformat()

    # Fetch and parse
    html = fetch_rightmove_html(url)
    facts = parse_listing(url, html)

    # Claude fallback extraction when key fields are missing
    if use_claude:
        try:
            from claude_ai import extract_listing_details, is_claude_available
            if is_claude_available() and not facts.price:
                extracted = extract_listing_details(html[:6000], {
                    "price": facts.price,
                    "bedrooms": facts.bedrooms,
                    "tenure": facts.tenure,
                    "floor_area_sqm": facts.floor_area_sqm,
                    "epc_rating": facts.epc_rating,
                    "postcode": facts.postcode,
                })
                if extracted.get("price") and not facts.price:
                    facts.price = int(extracted["price"])
                if extracted.get("bedrooms") and not facts.bedrooms:
                    facts.bedrooms = int(extracted["bedrooms"])
                if extracted.get("tenure") and not facts.tenure:
                    facts.tenure = str(extracted["tenure"])
                if extracted.get("floor_area_sqm") and not facts.floor_area_sqm:
                    facts.floor_area_sqm = float(extracted["floor_area_sqm"])
                if extracted.get("epc_rating") and not facts.epc_rating:
                    facts.epc_rating = str(extracted["epc_rating"])
                if extracted.get("postcode") and not facts.postcode:
                    facts.postcode = str(extracted["postcode"])
        except Exception as exc:
            print(f"[WARN] Claude extraction fallback failed: {exc}")

    # Find comparables
    comps: List[Any] = []
    if ppd_sqlite_path and HAS_PPD:
        if os.path.exists(ppd_sqlite_path):
            try:
                comps = find_comps_sqlite(
                    ppd_sqlite_path,
                    postcode=facts.postcode,
                    property_type=facts.property_type,
                )
            except Exception as e:
                print(f"[WARN] PPD lookup failed: {e}")

    # Sort comps by similarity score (best matches first), limit to top 20
    if comps:
        avg_price = sum(
            (c.price if hasattr(c, "price") else c.get("price", 0)) for c in comps
        ) / len(comps) if comps else 0
        comps = sorted(
            comps,
            key=lambda c: score_comp_similarity(c, facts, avg_price),
            reverse=True,
        )[:20]

    # Parallel: location enrichment + Claude AI (both optional, both non-blocking)
    enrichment_dict: Optional[Dict[str, Any]] = None
    ai_narrative = ""

    futures = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        if enrich_location and facts.postcode:
            try:
                from location_enrichment import enrich_location as _enrich
                futures["enrich"] = executor.submit(_enrich, facts.postcode)
            except ImportError:
                pass

        # Valuation needed before Claude can run — do it synchronously first
        valuation = estimate_value_from_comps(comps, facts.floor_area_sqm)

        if use_claude:
            try:
                from claude_ai import generate_ai_narrative, is_claude_available
                if is_claude_available():
                    comps_list_preview = [
                        (c.__dict__ if hasattr(c, "__dict__") else dict(c))
                        for c in comps[:8]
                    ]
                    futures["claude"] = executor.submit(
                        generate_ai_narrative,
                        {
                            "address": facts.address,
                            "property_type": facts.property_type,
                            "bedrooms": facts.bedrooms,
                            "bathrooms": facts.bathrooms,
                            "tenure": facts.tenure,
                            "floor_area_sqm": facts.floor_area_sqm,
                            "epc_rating": facts.epc_rating,
                            "postcode": facts.postcode,
                            "key_features": facts.key_features,
                            "user_type": user_type,
                        },
                        valuation or {},
                        comps_list_preview,
                        {},   # score_data not yet computed; passed again after
                        {},   # strategy not yet computed
                        None, # enrichment will be merged in later
                        None, # prediction not available at this stage
                    )
            except ImportError:
                pass

        # Collect enrichment result (timeout 15s)
        if "enrich" in futures:
            try:
                enrich_result = futures["enrich"].result(timeout=15)
                enrichment_dict = enrich_result.to_dict()
            except Exception as exc:
                print(f"[WARN] Location enrichment failed: {exc}")

        # Collect Claude result (timeout 30s)
        if "claude" in futures:
            try:
                ai_narrative = futures["claude"].result(timeout=30) or ""
            except Exception as exc:
                print(f"[WARN] Claude narrative failed: {exc}")

    # Score (with enrichment if available)
    score_data = reasonableness_score(facts, valuation, enrichment=enrichment_dict)

    # Strategy
    strategy = offer_strategy(facts, valuation, score_data["score"])

    # Markdown report
    md = build_md_report(facts, comps, valuation, score_data, strategy, ai_narrative=ai_narrative)

    # Serialise comps
    comps_list = []
    for c in comps:
        if hasattr(c, "__dict__"):
            comps_list.append(c.__dict__)
        else:
            comps_list.append(dict(c))

    facts_dict = {
        "url": facts.url,
        "property_id": facts.property_id,
        "address": facts.address,
        "price": facts.price,
        "bedrooms": facts.bedrooms,
        "bathrooms": facts.bathrooms,
        "property_type": facts.property_type,
        "tenure": facts.tenure,
        "floor_area_sqm": facts.floor_area_sqm,
        "epc_rating": facts.epc_rating,
        "postcode": facts.postcode,
        "key_features": facts.key_features,
        "user_type": user_type,
    }

    valuation_dict = {
        **(valuation or {}),
        **score_data,
        "strategy": strategy,
    }

    result = {
        "ok": True,
        "created_at_utc": ts,
        "url": url,
        "facts": facts_dict,
        "comps": comps_list,
        "valuation": valuation_dict,
        "md_report": md,
    }

    if enrichment_dict:
        result["enrichment"] = enrichment_dict

    if ai_narrative:
        result["ai_narrative"] = ai_narrative

    return result
