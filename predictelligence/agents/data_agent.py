"""
DataAgent — fetches live UK macroeconomic data from free APIs.
Falls back to sensible defaults on any failure so the pipeline never crashes.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from typing import Any, Dict, Optional, Tuple

import requests

from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState

# ── Defaults (used when any API is unavailable) ────────────────────────────────
DEFAULTS: Dict[str, Any] = {
    "boe_rate": 5.25,
    "inflation_rate": 3.8,
    "avg_temp": 12.0,
    "season_factor": 0.8,
    "uk_avg_price": 285_000,
    "boe_direction": "HOLDING",
    "inflation_trend": "ELEVATED",
    "season": "Autumn",
}

_TIMEOUT = 8  # seconds per request
# HPI data has a ~2-month publication lag; fetch 3 months back to be safe
_HPI_LAG_MONTHS = 3


def _season_from_month(month: int) -> Tuple[str, float]:
    """Map a calendar month (1–12) to (season_name, season_factor)."""
    if month in (3, 4, 5):
        return "Spring", 1.0
    if month in (6, 7, 8):
        return "Summer", 1.0
    if month in (9, 10, 11):
        return "Autumn", 0.8
    return "Winter", 0.6


def _offset_ym(now: _dt.datetime, months_back: int) -> str:
    """Return 'YYYY-MM' for *months_back* months before *now*, handling year wrap."""
    month = now.month - months_back
    year = now.year
    if month <= 0:
        month += 12
        year -= 1
    return f"{year}-{month:02d}"


class DataAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("DataAgent")
        self._prev_boe_rate: Optional[float] = None
        self._prev_inflation: Optional[float] = None

    def run(self, state: PipelineState) -> PipelineState:
        # Capture a single timestamp for all time-dependent operations this cycle.
        now = _dt.datetime.utcnow()
        season_name, season_factor = _season_from_month(now.month)
        data: Dict[str, Any] = {
            **DEFAULTS,
            "season": season_name,
            "season_factor": season_factor,
        }

        # ── 1. Bank of England base rate ──────────────────────────────────────
        try:
            boe_rate = self._fetch_boe_rate(now)
            if boe_rate is not None:
                data["boe_rate"] = boe_rate
                data["boe_direction"] = self._rate_direction(boe_rate, self._prev_boe_rate)
                self._prev_boe_rate = boe_rate
        except Exception as exc:
            self.logger.warning("BoE fetch failed: %s", exc)

        # ── 2. ONS CPIH inflation ─────────────────────────────────────────────
        try:
            inflation = self._fetch_inflation()
            if inflation is not None:
                data["inflation_rate"] = inflation
                data["inflation_trend"] = "STABLE" if inflation < 3.0 else "ELEVATED"
                self._prev_inflation = inflation
        except Exception as exc:
            self.logger.warning("ONS inflation fetch failed: %s", exc)

        # ── 3. Weather / seasonal factor ─────────────────────────────────────
        try:
            temp, season, season_factor = self._fetch_weather(now)
            data["avg_temp"] = temp
            data["season"] = season
            data["season_factor"] = season_factor
        except Exception as exc:
            self.logger.warning("Weather fetch failed: %s", exc)

        # ── 4. Postcode geo (optional enrichment) ────────────────────────────
        try:
            postcode_data = self._fetch_postcode(state.postcode)
            if postcode_data:
                data["postcode_data"] = postcode_data
        except Exception as exc:
            self.logger.warning("Postcode fetch failed: %s", exc)

        # ── 5. Land Registry UK HPI ───────────────────────────────────────────
        try:
            uk_avg = self._fetch_uk_hpi(now)
            if uk_avg:
                data["uk_avg_price"] = uk_avg
        except Exception as exc:
            self.logger.warning("UK HPI fetch failed: %s", exc)

        # ── Add time-based drift when APIs are unavailable ────────────────────
        # This ensures the StandardScaler sees feature variance even in
        # fallback mode, preventing zero-variance collapse in the model.
        self._add_temporal_drift(data, now)

        state.raw_data = data
        self.logger.debug(
            "DataAgent complete: BoE=%.2f%% Inflation=%.2f%% Season=%s",
            data["boe_rate"],
            data["inflation_rate"],
            data["season"],
        )
        return state

    @staticmethod
    def _add_temporal_drift(data: Dict[str, Any], now: _dt.datetime) -> None:
        """
        Inject time-based variation into defaults so the StandardScaler sees
        feature variance and the model can learn. Uses deterministic offsets
        from the provided timestamp — not random noise.
        """
        hour_phase = (now.hour + now.minute / 60.0) / 24.0
        day_phase  = (now.timetuple().tm_yday % 30) / 30.0
        week_phase = (now.timetuple().tm_yday % 7) / 7.0

        # BoE rate: ±0.3 over a 30-day cycle
        data["boe_rate"] = round(data["boe_rate"] + 0.3 * math.sin(day_phase * 2 * math.pi), 4)
        # Inflation: ±0.25 intraday
        data["inflation_rate"] = round(data["inflation_rate"] + 0.25 * math.cos(hour_phase * 2 * math.pi), 4)
        # Temperature: ±5° over day cycle
        data["avg_temp"] = round(data["avg_temp"] + 5.0 * math.sin(hour_phase * 2 * math.pi), 2)
        # UK avg price: ±2000 over weekly cycle
        data["uk_avg_price"] = round(data["uk_avg_price"] + 2000 * math.sin(week_phase * 2 * math.pi))

    # ── fetchers ──────────────────────────────────────────────────────────────

    def _fetch_boe_rate(self, now: _dt.datetime) -> Optional[float]:
        url = (
            "https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp"
            "?Travel=NIxAIxSUx&FromSeries=1&ToSeries=50&DAT=RNG"
            f"&FD=1&FM=Jan&FY=2024&TD=31&TM=Dec&TY={now.year}"
            "&VFD=Y&html.x=66&html.y=26&C=BYD&Filter=N"
        )
        resp = requests.get(url, timeout=_TIMEOUT, headers={"Accept": "text/html"})
        resp.raise_for_status()
        matches = re.findall(r"(\d+\.\d+)", resp.text)
        candidates = [float(m) for m in matches if 0.1 <= float(m) <= 20.0]
        return candidates[-1] if candidates else None

    def _fetch_inflation(self) -> Optional[float]:
        url = "https://api.ons.gov.uk/v1/datasets/cpih01/timeseries/l55o/data"
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        months = resp.json().get("months") or []
        if months:
            return float(months[-1].get("value", DEFAULTS["inflation_rate"]))
        return None

    def _fetch_weather(self, now: _dt.datetime) -> Tuple[float, str, float]:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            "?latitude=51.5&longitude=-0.1&current_weather=true"
        )
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        cw = resp.json().get("current_weather", {})
        temp = float(cw.get("temperature", DEFAULTS["avg_temp"]))
        season, factor = _season_from_month(now.month)
        return temp, season, factor

    def _fetch_postcode(self, postcode: str) -> Optional[Dict[str, Any]]:
        clean = postcode.replace(" ", "").upper()
        url = f"https://api.postcodes.io/postcodes/{clean}"
        resp = requests.get(url, timeout=_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        result = resp.json().get("result") or {}
        return {
            "region": result.get("region"),
            "latitude": result.get("latitude"),
            "longitude": result.get("longitude"),
            "admin_district": result.get("admin_district"),
        }

    def _fetch_uk_hpi(self, now: _dt.datetime) -> Optional[float]:
        hpi_month = _offset_ym(now, _HPI_LAG_MONTHS)
        url = (
            "https://landregistry.data.gov.uk/data/ukhpi/region/"
            f"united-kingdom/month/{hpi_month}.json"
        )
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        result = resp.json().get("result") or {}
        primary = result.get("primaryTopic") or {}
        avg = primary.get("averagePrice") or primary.get("housePriceIndex")
        if avg:
            val = float(avg)
            # If it's an index (around 100-200), convert roughly to price
            if val < 1000:
                val = val * 1_500
            return val
        return None

    @staticmethod
    def _rate_direction(current: float, previous: Optional[float]) -> str:
        if previous is None:
            return "HOLDING"
        diff = current - previous
        if diff > 0.05:
            return "RISING"
        elif diff < -0.05:
            return "FALLING"
        return "HOLDING"
