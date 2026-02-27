from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from ppd_sqlite import get_data_dir
from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState


class EvaluatorAgent(BaseAgent):
    def __init__(self, db_path: str | None = None):
        super().__init__("EvaluatorAgent")
        self.db_path = Path(db_path) if db_path else (get_data_dir() / "predictions.db")
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS predictions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                cycle INTEGER,
                postcode TEXT,
                property_type TEXT,
                bedrooms INTEGER,
                predicted REAL,
                actual REAL,
                direction TEXT,
                signal TEXT,
                confidence REAL,
                error REAL
            )
            """
        )

        cols = {r[1] for r in conn.execute("PRAGMA table_info(predictions)").fetchall()}
        if "property_type" not in cols:
            conn.execute("ALTER TABLE predictions ADD COLUMN property_type TEXT")
        if "bedrooms" not in cols:
            conn.execute("ALTER TABLE predictions ADD COLUMN bedrooms INTEGER")

        conn.commit()
        conn.close()

    def run(self, state: PipelineState) -> PipelineState:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO predictions(timestamp, cycle, postcode, property_type, bedrooms, predicted, actual, direction, signal, confidence, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.utcnow().isoformat(),
                state.cycle,
                state.postcode,
                state.property_type,
                state.bedrooms,
                state.prediction,
                state.current_valuation,
                state.direction,
                state.investment_signal,
                state.confidence,
                state.error,
            ),
        )
        conn.commit()
        conn.close()
        return state
