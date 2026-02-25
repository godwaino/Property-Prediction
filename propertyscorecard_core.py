"""
Property Scorecard Core — UK Property Analysis Engine
Scrapes Rightmove listings and analyses them against Land Registry comparables.
"""
from __future__ import annotations

import json
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


# ─── valuation ────────────────────────────────────────────────────────────────

BASELINE_SQM = 68.0  # UK average floor area


def estimate_value_from_comps(
    comps: List[Any],
    floor_area_sqm: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    if not comps:
        return None

    prices = [c.price if hasattr(c, "price") else c.get("price", 0) for c in comps]
    prices = [p for p in prices if p and p > 10_000]
    if not prices:
        return None

    # Light-touch size adjustment
    if floor_area_sqm and floor_area_sqm > 20:
        adj = floor_area_sqm / BASELINE_SQM
        prices = [int(p * adj) for p in prices]

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
    facts: ListingFacts,
    valuation: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    score = 0
    notes: List[str] = []
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
    else:
        score += 8

    # 4. EPC rating (15 pts)
    epc = (facts.epc_rating or "").upper().strip()
    epc_scores = {"A": 15, "B": 13, "C": 10, "D": 7, "E": 4, "F": 2, "G": 0}
    score += epc_scores.get(epc, 5)
    if epc in ("F", "G"):
        notes.append("Poor EPC rating — energy costs will be high")
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

    score = min(100, max(0, score))

    label = SCORE_LABELS[-1][1]
    for threshold, lbl in SCORE_LABELS:
        if score >= threshold:
            label = lbl
            break

    return {
        "score": score,
        "label": label,
        "notes": notes,
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
    facts: ListingFacts,
    comps: List[Any],
    valuation: Optional[Dict[str, Any]],
    score_data: Dict[str, Any],
    strategy: Dict[str, Any],
) -> str:
    ts = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
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
        f"| Reasonableness Score | {score_data['score']}/100 — {score_data['label']} |",
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
) -> Dict[str, Any]:
    """
    Main analysis entry point. Returns a dict with:
      facts, comps, valuation, md_report, created_at_utc
    """
    ts = datetime.now(timezone.utc).isoformat()

    # Fetch and parse
    html = fetch_rightmove_html(url)
    facts = parse_listing(url, html)

    # Find comparables
    comps: List[Any] = []
    if ppd_sqlite_path and HAS_PPD:
        import os
        if os.path.exists(ppd_sqlite_path):
            try:
                comps = find_comps_sqlite(
                    ppd_sqlite_path,
                    postcode=facts.postcode,
                    property_type=facts.property_type,
                )
            except Exception as e:
                print(f"[WARN] PPD lookup failed: {e}")

    # Valuation
    valuation = estimate_value_from_comps(comps, facts.floor_area_sqm)

    # Score
    score_data = reasonableness_score(facts, valuation)

    # Strategy
    strategy = offer_strategy(facts, valuation, score_data["score"])

    # Markdown report
    md = build_md_report(facts, comps, valuation, score_data, strategy)

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

    return {
        "ok": True,
        "created_at_utc": ts,
        "url": url,
        "facts": facts_dict,
        "comps": comps_list,
        "valuation": valuation_dict,
        "md_report": md,
    }
