"""
Location Enrichment Module
Fetches UK area data to supplement PropertyScorecard analysis.
All API calls have timeouts and fallbacks — never raises, never crashes the pipeline.

Data sources:
  - postcodes.io        — geocoding, lat/lng, LSOA code
  - opendatacommunities — EPC ratings (requires EPC_API_KEY env var)
  - data.police.uk      — crime statistics
  - environment.data.gov.uk — flood monitoring
  - ArcGIS MHCLG        — IMD 2019 deprivation indices
  - nomisweb.co.uk      — NOMIS ASHE median earnings
  - planit.org.uk       — planning applications
"""
from __future__ import annotations

import base64
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# ── Module-level postcode cache (TTL 3600s) ────────────────────────────────────
_enrich_cache: Dict[str, Tuple[float, "LocationEnrichment"]] = {}
_CACHE_TTL = 3600


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class LocationEnrichment:
    postcode: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    lsoa_code: Optional[str] = None
    admin_district: Optional[str] = None

    # EPC (from opendatacommunities.org)
    epc_rating: Optional[str] = None
    epc_floor_area_sqm: Optional[float] = None
    epc_heating_type: Optional[str] = None

    # Crime (data.police.uk)
    crime_count_12m: Optional[int] = None
    crime_categories: Dict[str, int] = field(default_factory=dict)
    crime_severity: str = "unknown"   # "low"|"medium"|"high"|"unknown"

    # Flood (environment.data.gov.uk)
    flood_warnings_active: int = 0
    flood_severity: str = "negligible"   # "negligible"|"low"|"medium"|"high"|"severe"
    flood_adjustment_pct: float = 0.0

    # Deprivation (MHCLG IMD 2019)
    imd_rank: Optional[int] = None
    imd_decile: Optional[int] = None   # 1 = most deprived, 10 = least

    # Planning (planit.org.uk)
    planning_apps_count: int = 0
    planning_major_nearby: bool = False

    # Earnings (NOMIS ASHE)
    median_earnings: Optional[float] = None

    # Composite
    area_score_adjustment: float = 0.0
    area_flags: List[str] = field(default_factory=list)
    fetch_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "postcode": self.postcode,
            "lat": self.lat,
            "lng": self.lng,
            "lsoa_code": self.lsoa_code,
            "admin_district": self.admin_district,
            "epc_rating": self.epc_rating,
            "epc_floor_area_sqm": self.epc_floor_area_sqm,
            "epc_heating_type": self.epc_heating_type,
            "crime_count_12m": self.crime_count_12m,
            "crime_categories": self.crime_categories,
            "crime_severity": self.crime_severity,
            "flood_warnings_active": self.flood_warnings_active,
            "flood_severity": self.flood_severity,
            "flood_adjustment_pct": self.flood_adjustment_pct,
            "imd_rank": self.imd_rank,
            "imd_decile": self.imd_decile,
            "planning_apps_count": self.planning_apps_count,
            "planning_major_nearby": self.planning_major_nearby,
            "median_earnings": self.median_earnings,
            "area_score_adjustment": self.area_score_adjustment,
            "area_flags": self.area_flags,
            "fetch_errors": self.fetch_errors,
        }


# ── Geocoding ───────────────────────────────────────────────────────────────────

def _fetch_geocode(postcode: str) -> dict:
    """Fetch lat/lng, LSOA code, admin_district from postcodes.io."""
    try:
        clean = re.sub(r"\s+", "", postcode).upper()
        resp = requests.get(
            f"https://api.postcodes.io/postcodes/{clean}",
            timeout=6,
        )
        if resp.status_code == 200:
            result = resp.json().get("result") or {}
            return {
                "lat": result.get("latitude"),
                "lng": result.get("longitude"),
                "lsoa_code": result.get("codes", {}).get("lsoa"),
                "admin_district": result.get("admin_district"),
            }
    except Exception as exc:
        logger.debug("Geocode failed for %s: %s", postcode, exc)
    return {}


# ── EPC ─────────────────────────────────────────────────────────────────────────

def _fetch_epc(postcode: str) -> dict:
    """Fetch EPC data from opendatacommunities.org. Requires EPC_API_KEY env var."""
    api_key = os.environ.get("EPC_API_KEY", "")
    if not api_key or ":" not in api_key:
        return {}
    try:
        email, key = api_key.split(":", 1)
        token = base64.b64encode(f"{email}:{key}".encode()).decode()
        clean = re.sub(r"\s+", "", postcode).upper()
        resp = requests.get(
            f"https://epc.opendatacommunities.org/api/v1/domestic/search",
            params={"postcode": clean, "size": "1"},
            headers={
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
            },
            timeout=8,
        )
        if resp.status_code == 200:
            rows = resp.json().get("rows") or []
            if rows:
                row = rows[0]
                return {
                    "epc_rating": row.get("current-energy-rating"),
                    "epc_floor_area_sqm": _safe_float(row.get("total-floor-area")),
                    "epc_heating_type": row.get("main-heat-description"),
                }
    except Exception as exc:
        logger.debug("EPC fetch failed: %s", exc)
    return {}


# ── Crime ───────────────────────────────────────────────────────────────────────

def _fetch_crime(lat: float, lng: float) -> dict:
    """Fetch crime stats for last 6 months from data.police.uk."""
    if lat is None or lng is None:
        return {}
    try:
        now = datetime.now(timezone.utc)
        total = 0
        categories: Dict[str, int] = {}
        # Police API has ~2-month lag; fetch last 6 available months
        for months_back in range(2, 8):
            yr = now.year
            mo = now.month - months_back
            while mo <= 0:
                mo += 12
                yr -= 1
            date_str = f"{yr}-{mo:02d}"
            resp = requests.get(
                "https://data.police.uk/api/crimes-street/all-crime",
                params={"lat": lat, "lng": lng, "date": date_str},
                timeout=8,
            )
            if resp.status_code == 200:
                crimes = resp.json()
                for crime in crimes:
                    cat = crime.get("category", "other")
                    categories[cat] = categories.get(cat, 0) + 1
                    total += 1
            time.sleep(0.1)  # gentle rate limiting

        severity = "low"
        if total > 300:
            severity = "high"
        elif total > 100:
            severity = "medium"

        return {
            "crime_count_12m": total,
            "crime_categories": categories,
            "crime_severity": severity,
        }
    except Exception as exc:
        logger.debug("Crime fetch failed: %s", exc)
    return {}


# ── Flood ───────────────────────────────────────────────────────────────────────

def _fetch_flood(lat: float, lng: float) -> dict:
    """Fetch active flood warnings within 5km from Environment Agency."""
    if lat is None or lng is None:
        return {}
    try:
        resp = requests.get(
            "https://environment.data.gov.uk/flood-monitoring/id/floods",
            params={"lat": lat, "long": lng, "dist": 5},
            timeout=8,
        )
        if resp.status_code == 200:
            items = resp.json().get("items") or []
            active = len(items)
            # severityLevel: 1=severe, 2=high, 3=medium, 4=low/warning
            worst = min((i.get("severityLevel", 4) for i in items), default=4)
            severity_map = {1: "severe", 2: "high", 3: "medium", 4: "low"}
            severity = severity_map.get(worst, "negligible") if active else "negligible"
            adj_map = {"severe": -6.0, "high": -6.0, "medium": -3.0, "low": 0.0, "negligible": 0.0}
            return {
                "flood_warnings_active": active,
                "flood_severity": severity,
                "flood_adjustment_pct": adj_map.get(severity, 0.0),
            }
    except Exception as exc:
        logger.debug("Flood fetch failed: %s", exc)
    return {}


# ── IMD Deprivation ─────────────────────────────────────────────────────────────

def _fetch_deprivation(lsoa_code: Optional[str]) -> dict:
    """Fetch IMD 2019 deprivation rank and decile from MHCLG ArcGIS."""
    if not lsoa_code:
        return {}
    try:
        resp = requests.get(
            "https://services3.arcgis.com/ivmBBrHfQfDnDf8Q/arcgis/rest/services/"
            "Indices_of_Multiple_Deprivation_(IMD)_2019/FeatureServer/0/query",
            params={
                "where": f"lsoa11cd='{lsoa_code}'",
                "outFields": "IMDRank,IMDDecil",
                "f": "json",
            },
            timeout=8,
        )
        if resp.status_code == 200:
            features = resp.json().get("features") or []
            if features:
                attrs = features[0].get("attributes") or {}
                return {
                    "imd_rank": attrs.get("IMDRank"),
                    "imd_decile": attrs.get("IMDDecil"),
                }
    except Exception as exc:
        logger.debug("IMD fetch failed: %s", exc)
    return {}


# ── Planning ─────────────────────────────────────────────────────────────────────

def _fetch_planning(lat: float, lng: float) -> dict:
    """Fetch planning applications within 0.25 miles from PlanIt."""
    if lat is None or lng is None:
        return {}
    try:
        resp = requests.get(
            "https://www.planit.org.uk/api/applics/json",
            params={"lat": lat, "lng": lng, "miles": "0.25", "pg_sz": "10"},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            apps = data.get("records") or []
            count = len(apps)
            major = any(
                "major" in (a.get("application_type") or "").lower()
                for a in apps
            )
            return {
                "planning_apps_count": count,
                "planning_major_nearby": major,
            }
    except Exception as exc:
        logger.debug("Planning fetch failed: %s", exc)
    return {}


# ── Earnings ─────────────────────────────────────────────────────────────────────

# Static mapping of UK local authority names to NOMIS geography codes (top 40 LAs)
_NOMIS_LA_CODES: Dict[str, str] = {
    "City of London": "1946157348",
    "Camden": "1946157350",
    "Greenwich": "1946157351",
    "Hackney": "1946157352",
    "Hammersmith and Fulham": "1946157353",
    "Islington": "1946157354",
    "Kensington and Chelsea": "1946157355",
    "Lambeth": "1946157356",
    "Lewisham": "1946157357",
    "Southwark": "1946157358",
    "Tower Hamlets": "1946157359",
    "Wandsworth": "1946157360",
    "Westminster": "1946157361",
    "Barking and Dagenham": "1946157362",
    "Barnet": "1946157363",
    "Bexley": "1946157364",
    "Brent": "1946157365",
    "Bromley": "1946157366",
    "Croydon": "1946157367",
    "Ealing": "1946157368",
    "Enfield": "1946157369",
    "Haringey": "1946157370",
    "Harrow": "1946157371",
    "Havering": "1946157372",
    "Hillingdon": "1946157373",
    "Hounslow": "1946157374",
    "Kingston upon Thames": "1946157375",
    "Merton": "1946157376",
    "Newham": "1946157377",
    "Redbridge": "1946157378",
    "Richmond upon Thames": "1946157379",
    "Sutton": "1946157380",
    "Waltham Forest": "1946157381",
    "Manchester": "1946157434",
    "Birmingham": "1946157407",
    "Leeds": "1946157426",
    "Sheffield": "1946157438",
    "Liverpool": "1946157429",
    "Bristol, City of": "1946157411",
    "Edinburgh, City of": "1946157476",
}


def _fetch_earnings(admin_district: Optional[str]) -> dict:
    """Fetch median annual earnings from NOMIS ASHE for local authority."""
    if not admin_district:
        return {}
    la_code = _NOMIS_LA_CODES.get(admin_district)
    if not la_code:
        return {}
    try:
        resp = requests.get(
            "https://www.nomisweb.co.uk/api/v01/dataset/NM_30_1.data.json",
            params={
                "geography": la_code,
                "sex": "7",
                "item": "2",
                "pay": "7",
                "measures": "20100",
            },
            timeout=8,
        )
        if resp.status_code == 200:
            obs = (resp.json().get("obs") or [])
            if obs:
                val = obs[0].get("obs_value", {}).get("value")
                if val:
                    return {"median_earnings": float(val)}
    except Exception as exc:
        logger.debug("Earnings fetch failed: %s", exc)
    return {}


# ── Composite adjustment ─────────────────────────────────────────────────────────

def _compute_area_adjustment(data: LocationEnrichment) -> Tuple[float, List[str]]:
    """
    Compute net area score adjustment (percentage points) and flags.
    Capped to [-15.0, +5.0] range.
    """
    adj = 0.0
    flags = []

    # Flood risk
    if data.flood_adjustment_pct:
        adj += data.flood_adjustment_pct
        if data.flood_severity in ("high", "severe"):
            flags.append(f"High flood risk nearby — {abs(data.flood_adjustment_pct):.0f}% negative impact on resale")
        elif data.flood_severity == "medium":
            flags.append("Medium flood risk nearby — potential insurance premium")

    # Deprivation
    if data.imd_decile is not None:
        if data.imd_decile <= 2:
            adj -= 4.0
            flags.append(f"Highly deprived area (IMD decile {data.imd_decile}/10) — affects price appreciation")
        elif data.imd_decile <= 3:
            adj -= 2.0
            flags.append(f"Deprived area (IMD decile {data.imd_decile}/10)")
        elif data.imd_decile >= 9:
            adj += 2.0
            flags.append(f"Low deprivation area (IMD decile {data.imd_decile}/10) — positive for long-term value")

    # Crime
    if data.crime_severity == "high":
        adj -= 3.0
        flags.append(f"High crime area ({data.crime_count_12m} incidents in 6 months) — affects desirability")
    elif data.crime_severity == "medium":
        adj -= 1.5
        flags.append(f"Moderate crime levels ({data.crime_count_12m} incidents in 6 months)")

    # Planning
    if data.planning_major_nearby:
        adj -= 1.0
        flags.append("Major planning application nearby — review development impact")

    # EPC area quality (area-level, not property-level which is already scored)
    if data.epc_rating in ("F", "G"):
        adj -= 1.0
        flags.append("Area has poor EPC stock — older housing stock")

    adj = max(-15.0, min(5.0, adj))
    return adj, flags


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _safe_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Main public function ─────────────────────────────────────────────────────────

def enrich_location(postcode: Optional[str]) -> LocationEnrichment:
    """
    Fetch all available UK area data for a postcode.
    Returns a LocationEnrichment with graceful fallbacks on API failure.
    Results are cached for CACHE_TTL seconds per postcode.
    """
    if not postcode:
        return LocationEnrichment(postcode="", fetch_errors=["No postcode provided"])

    clean_postcode = re.sub(r"\s+", " ", postcode.strip().upper())

    # Cache check
    cached = _enrich_cache.get(clean_postcode)
    if cached:
        expiry, result = cached
        if time.time() < expiry:
            logger.debug("Location enrichment cache hit: %s", clean_postcode)
            return result
        del _enrich_cache[clean_postcode]

    data = LocationEnrichment(postcode=clean_postcode)
    errors = []

    # 1. Geocode (required for most other calls)
    geo = _fetch_geocode(clean_postcode)
    if geo:
        data.lat = geo.get("lat")
        data.lng = geo.get("lng")
        data.lsoa_code = geo.get("lsoa_code")
        data.admin_district = geo.get("admin_district")
    else:
        errors.append("postcodes.io geocoding failed")

    # 2. EPC
    epc = _fetch_epc(clean_postcode)
    if epc:
        data.epc_rating = epc.get("epc_rating")
        data.epc_floor_area_sqm = epc.get("epc_floor_area_sqm")
        data.epc_heating_type = epc.get("epc_heating_type")
    elif not os.environ.get("EPC_API_KEY"):
        errors.append("EPC skipped (EPC_API_KEY not set)")
    else:
        errors.append("EPC fetch failed")

    # 3. Crime
    if data.lat and data.lng:
        crime = _fetch_crime(data.lat, data.lng)
        if crime:
            data.crime_count_12m = crime.get("crime_count_12m")
            data.crime_categories = crime.get("crime_categories", {})
            data.crime_severity = crime.get("crime_severity", "unknown")
        else:
            errors.append("Crime data fetch failed")
    else:
        errors.append("Crime skipped (no geocode)")

    # 4. Flood
    if data.lat and data.lng:
        flood = _fetch_flood(data.lat, data.lng)
        if flood:
            data.flood_warnings_active = flood.get("flood_warnings_active", 0)
            data.flood_severity = flood.get("flood_severity", "negligible")
            data.flood_adjustment_pct = flood.get("flood_adjustment_pct", 0.0)
        else:
            errors.append("Flood data fetch failed")
    else:
        errors.append("Flood skipped (no geocode)")

    # 5. Deprivation (IMD)
    depr = _fetch_deprivation(data.lsoa_code)
    if depr:
        data.imd_rank = depr.get("imd_rank")
        data.imd_decile = depr.get("imd_decile")
    else:
        errors.append("IMD deprivation fetch failed or not available for this area")

    # 6. Planning
    if data.lat and data.lng:
        plan = _fetch_planning(data.lat, data.lng)
        if plan:
            data.planning_apps_count = plan.get("planning_apps_count", 0)
            data.planning_major_nearby = plan.get("planning_major_nearby", False)
        else:
            errors.append("Planning data fetch failed")
    else:
        errors.append("Planning skipped (no geocode)")

    # 7. Earnings
    earn = _fetch_earnings(data.admin_district)
    if earn:
        data.median_earnings = earn.get("median_earnings")
    else:
        errors.append("Earnings data not available for this local authority")

    # Compute composite adjustment
    data.area_score_adjustment, data.area_flags = _compute_area_adjustment(data)
    data.fetch_errors = errors

    # Cache result
    _enrich_cache[clean_postcode] = (time.time() + _CACHE_TTL, data)

    logger.info(
        "Location enrichment complete: %s | crime=%s flood=%s imd=%s adj=%.1f",
        clean_postcode,
        data.crime_severity,
        data.flood_severity,
        data.imd_decile,
        data.area_score_adjustment,
    )

    return data
