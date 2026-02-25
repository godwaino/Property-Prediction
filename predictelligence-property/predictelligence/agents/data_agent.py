from __future__ import annotations

import re
from datetime import datetime

import requests

from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState


class DataAgent(BaseAgent):
    DEFAULTS = {
        "boe_rate": 5.25,
        "inflation_rate": 3.8,
        "avg_temp": 12.0,
        "season_factor": 0.8,
        "uk_avg_price": 285000.0,
    }

    def __init__(self):
        super().__init__("DataAgent")
        self.last_inflation = self.DEFAULTS["inflation_rate"]
        self.last_boe = self.DEFAULTS["boe_rate"]

    def _safe_get(self, url: str, timeout: int = 8):
        try:
            return requests.get(url, timeout=timeout)
        except Exception:
            return None

    @staticmethod
    def _first_reasonable_float(text: str, low: float, high: float):
        for m in re.findall(r"\d+\.\d+|\d+", text):
            try:
                v = float(m)
            except ValueError:
                continue
            if low <= v <= high:
                return v
        return None

    def run(self, state: PipelineState) -> PipelineState:
        data = dict(self.DEFAULTS)

        boe_url = "https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp?Travel=NIxAIxSUx&FromSeries=1&ToSeries=50&DAT=RNG&FD=1&FM=Jan&FY=2024&TD=31&TM=Dec&TY=2025&VFD=Y&html.x=66&html.y=26&C=BYD&Filter=N"
        inflation_url = "https://api.ons.gov.uk/v1/datasets/cpih01/timeseries/l55o/data"
        weather_url = "https://api.open-meteo.com/v1/forecast?latitude=51.5&longitude=-0.1&current_weather=true"
        post_url = f"https://api.postcodes.io/postcodes/{state.postcode}"
        hpi_url = "https://landregistry.data.gov.uk/data/ukhpi/region/united-kingdom/month/2024-01.json"

        try:
            r = self._safe_get(boe_url)
            if r and r.ok:
                parsed = self._first_reasonable_float(r.text, 0.1, 15.0)
                if parsed is not None:
                    data["boe_rate"] = parsed
        except Exception:
            pass

        try:
            r = self._safe_get(inflation_url)
            if r and r.ok:
                payload = r.json()
                obs = payload.get("months", [])
                if obs:
                    data["inflation_rate"] = float(obs[-1].get("value", data["inflation_rate"]))
        except Exception:
            pass

        try:
            r = self._safe_get(weather_url)
            if r and r.ok:
                payload = r.json()
                cw = payload.get("current_weather", {})
                data["avg_temp"] = float(cw.get("temperature", data["avg_temp"]))
        except Exception:
            pass

        try:
            r = self._safe_get(post_url)
            if r and r.ok:
                payload = r.json()
                result = payload.get("result", {})
                data["postcode_valid"] = bool(result)
                data["region"] = result.get("region")
                data["longitude"] = float(result.get("longitude", -0.1))
                data["latitude"] = float(result.get("latitude", 51.5))
                data["outcode"] = str(result.get("outcode") or state.postcode[:4])
        except Exception:
            data["postcode_valid"] = False

        try:
            r = self._safe_get(hpi_url)
            if r and r.ok:
                payload = r.json()
                items = payload.get("result", {}).get("items", [])
                if items:
                    data["uk_avg_price"] = float(items[-1].get("averagePrice", data["uk_avg_price"]))
        except Exception:
            pass

        month = datetime.utcnow().month
        if month in [3, 4, 5, 6, 7, 8]:
            season_factor = 1.0
            season = "Spring/Summer"
        elif month in [9, 10, 11]:
            season_factor = 0.8
            season = "Autumn"
        else:
            season_factor = 0.6
            season = "Winter"
        data["season_factor"] = season_factor
        data["season"] = season
        data["inflation_prev"] = self.last_inflation
        data["boe_prev"] = self.last_boe
        self.last_inflation = data["inflation_rate"]
        self.last_boe = data["boe_rate"]

        state.raw_data = data
        return state
