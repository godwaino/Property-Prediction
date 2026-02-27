from __future__ import annotations

import sqlite3
from pathlib import Path

from ppd_sqlite import get_data_dir


class DBManager:
    def __init__(self, db_path: str | None = None):
        self.db_path = Path(db_path) if db_path else (get_data_dir() / "predictions.db")

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def latest_prediction(self, postcode):
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM predictions WHERE postcode = ? ORDER BY id DESC LIMIT 1",
            (postcode.replace(" ", "").upper(),),
        ).fetchone()
        conn.close()
        return dict(row) if row else {}

    def prediction_history(self, postcode, limit=20):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM predictions WHERE postcode = ? ORDER BY id DESC LIMIT ?",
            (postcode.replace(" ", "").upper(), int(limit)),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def area_trend(self, postcode_district):
        conn = self._conn()
        rows = conn.execute(
            "SELECT direction, COUNT(*) AS c FROM predictions WHERE postcode LIKE ? GROUP BY direction",
            (f"{postcode_district.upper()}%",),
        ).fetchall()
        conn.close()
        out = {r["direction"]: r["c"] for r in rows}
        total = sum(out.values()) or 1
        return {"distribution": out, "up_share": out.get("UP", 0) / total}

    def model_accuracy(self):
        conn = self._conn()
        rows = conn.execute("SELECT * FROM predictions ORDER BY id DESC LIMIT 20").fetchall()
        conn.close()
        if not rows:
            return {"mae": None, "direction_accuracy": None, "samples": 0}
        errors = [abs(r["predicted"] - r["actual"]) for r in rows]
        hits = 0
        for r in rows:
            delta = r["predicted"] - r["actual"]
            actual_dir = "UP" if delta > 0 else "DOWN" if delta < 0 else "SIDEWAYS"
            if actual_dir == r["direction"]:
                hits += 1
        return {
            "mae": round(sum(errors) / len(errors), 2),
            "direction_accuracy": round(hits / len(rows), 3),
            "samples": len(rows),
        }
