"""
DbManager — helper class for reading Predictelligence prediction history.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(_APP_DIR, "data", "predictions.db")


class DbManager:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return dict(row)

    def latest_prediction(self, postcode: str) -> Optional[Dict[str, Any]]:
        """Return the most recent prediction for a given postcode."""
        if not os.path.exists(self.db_path):
            return None
        con = self._connect()
        try:
            cur = con.cursor()
            row = cur.execute(
                """
                SELECT * FROM predictions
                WHERE postcode = ?
                ORDER BY id DESC LIMIT 1
                """,
                (postcode.replace(" ", "").upper(),),
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            con.close()

    def prediction_history(
        self, postcode: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Return the last N predictions for a postcode."""
        if not os.path.exists(self.db_path):
            return []
        con = self._connect()
        try:
            cur = con.cursor()
            rows = cur.execute(
                """
                SELECT * FROM predictions
                WHERE postcode = ?
                ORDER BY id DESC LIMIT ?
                """,
                (postcode.replace(" ", "").upper(), limit),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            con.close()

    def area_trend(self, postcode_district: str) -> Dict[str, Any]:
        """Aggregate trend data for a postcode district (e.g. 'SW1A')."""
        if not os.path.exists(self.db_path):
            return {}
        district = postcode_district.upper().split(" ")[0]
        con = self._connect()
        try:
            cur = con.cursor()
            rows = cur.execute(
                """
                SELECT direction, signal, confidence, predicted
                FROM predictions
                WHERE postcode LIKE ?
                ORDER BY id DESC LIMIT 50
                """,
                (f"{district}%",),
            ).fetchall()
            if not rows:
                return {}
            directions = [r["direction"] for r in rows]
            signals = [r["signal"] for r in rows]
            avg_confidence = sum(r["confidence"] for r in rows) / len(rows)
            avg_price = sum(r["predicted"] for r in rows) / len(rows)
            return {
                "district": district,
                "sample_size": len(rows),
                "dominant_direction": max(set(directions), key=directions.count),
                "dominant_signal": max(set(signals), key=signals.count),
                "avg_confidence": round(avg_confidence, 1),
                "avg_predicted_price": round(avg_price, 0),
            }
        finally:
            con.close()

    def model_accuracy(self) -> Dict[str, Any]:
        """Compute MAE and direction accuracy over the last 20 predictions."""
        if not os.path.exists(self.db_path):
            return {"mae": None, "direction_accuracy": None, "sample_size": 0}
        con = self._connect()
        try:
            cur = con.cursor()
            rows = cur.execute(
                """
                SELECT predicted, actual, direction
                FROM predictions
                WHERE actual IS NOT NULL AND actual > 0
                ORDER BY id DESC LIMIT 20
                """
            ).fetchall()
            if not rows:
                return {"mae": None, "direction_accuracy": None, "sample_size": 0}

            errors = [abs(r["predicted"] - r["actual"]) for r in rows]
            mae = sum(errors) / len(errors)

            # Direction accuracy: did predicted direction match actual movement?
            correct = 0
            for r in rows:
                act = r["actual"]
                pred = r["predicted"]
                if act > 0 and pred > 0:
                    actual_dir = "UP" if act > pred * 1.005 else ("DOWN" if act < pred * 0.995 else "SIDEWAYS")
                    if actual_dir == r["direction"]:
                        correct += 1
            dir_acc = round(correct / len(rows) * 100, 1) if rows else 0.0

            return {
                "mae": round(mae, 0),
                "direction_accuracy": dir_acc,
                "sample_size": len(rows),
            }
        finally:
            con.close()

    def all_predictions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent predictions across all postcodes."""
        if not os.path.exists(self.db_path):
            return []
        con = self._connect()
        try:
            cur = con.cursor()
            rows = cur.execute(
                "SELECT * FROM predictions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            con.close()
