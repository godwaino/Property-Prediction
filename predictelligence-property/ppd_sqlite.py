from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List

DB_PATH = Path("data/property_prices.db")


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS property_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            postcode TEXT NOT NULL,
            property_type TEXT NOT NULL,
            price REAL NOT NULL,
            date_sold TEXT
        )
        """
    )
    cur.execute("SELECT COUNT(*) AS c FROM property_prices")
    if cur.fetchone()["c"] == 0:
        samples = [
            ("SW1A1AA", "semi-detached", 430000, "2025-04-01"),
            ("SW1A1AA", "semi-detached", 445000, "2025-02-10"),
            ("SW1A1AA", "semi-detached", 455000, "2024-11-18"),
            ("M11AE", "terraced", 245000, "2025-01-11"),
            ("B11AA", "flat", 180000, "2024-12-01"),
        ]
        cur.executemany(
            "INSERT INTO property_prices (postcode, property_type, price, date_sold) VALUES (?, ?, ?, ?)",
            samples,
        )
    conn.commit()
    conn.close()


def get_comparable_prices(postcode: str, property_type: str) -> List[float]:
    conn = get_connection()
    cur = conn.cursor()
    norm = postcode.replace(" ", "").upper()
    cur.execute(
        """
        SELECT price FROM property_prices
        WHERE postcode = ? AND LOWER(property_type) = LOWER(?)
        ORDER BY date_sold DESC
        LIMIT 20
        """,
        (norm, property_type),
    )
    prices = [row[0] for row in cur.fetchall()]
    conn.close()
    return prices
