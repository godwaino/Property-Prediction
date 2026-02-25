from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState


class EvaluatorAgent(BaseAgent):
    def __init__(self, db_path: str = "data/predictions.db"):
        super().__init__("EvaluatorAgent")
        self.db_path = Path(db_path)
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
                predicted REAL,
                actual REAL,
                direction TEXT,
                signal TEXT,
                confidence REAL,
                error REAL
            )
            """
        )
        conn.commit()
        conn.close()

    def run(self, state: PipelineState) -> PipelineState:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO predictions(timestamp, cycle, postcode, predicted, actual, direction, signal, confidence, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.utcnow().isoformat(),
                state.cycle,
                state.postcode,
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
