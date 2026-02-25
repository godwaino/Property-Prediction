"""
EvaluatorAgent — logs every prediction to the predictions SQLite database.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from predictelligence.agents.base_agent import BaseAgent
from predictelligence.pipeline_state import PipelineState

_APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(_APP_DIR, "data", "predictions.db")


def _init_predictions_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS predictions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            cycle       INTEGER NOT NULL,
            postcode    TEXT,
            predicted   REAL,
            actual      REAL,
            direction   TEXT,
            signal      TEXT,
            confidence  REAL,
            error       REAL
        )
        """
    )
    con.commit()
    con.close()


class EvaluatorAgent(BaseAgent):
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        super().__init__("EvaluatorAgent")
        self.db_path = db_path
        _init_predictions_db(db_path)

    def run(self, state: PipelineState) -> PipelineState:
        if not state.model_ready:
            return state  # Don't log warming-up cycles

        ts = datetime.now(timezone.utc).isoformat()
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            cur.execute(
                """
                INSERT INTO predictions
                  (timestamp, cycle, postcode, predicted, actual, direction, signal, confidence, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    state.cycle,
                    state.postcode,
                    state.prediction,
                    state.target,
                    state.direction,
                    state.investment_signal,
                    state.confidence,
                    state.error,
                ),
            )
            con.commit()
            con.close()
            self.logger.debug("Prediction logged: cycle=%d postcode=%s", state.cycle, state.postcode)
        except Exception as exc:
            self.logger.warning("Failed to log prediction: %s", exc)

        return state
