from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from statistics import mean
from typing import Dict, Iterable, List, Tuple


def get_data_dir() -> Path:
    explicit = os.getenv("PREDICTELLIGENCE_DATA_DIR")
    if explicit:
        p = Path(explicit)
    elif os.getenv("VERCEL"):
        p = Path("/tmp/predictelligence-data")
    else:
        p = Path("data")
    p.mkdir(parents=True, exist_ok=True)
    return p


DB_PATH = get_data_dir() / "property_prices.db"


def _normalize_postcode(postcode: str) -> str:
    return postcode.replace(" ", "").upper()


def _postcode_district(postcode: str) -> str:
    pc = _normalize_postcode(postcode)
    return "".join(ch for ch in pc if not ch.isdigit())[:3] or pc[:2]


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
            postcode_district TEXT NOT NULL,
            property_type TEXT NOT NULL,
            bedrooms INTEGER NOT NULL,
            floor_area_sqft REAL,
            tenure TEXT,
            new_build INTEGER DEFAULT 0,
            price REAL NOT NULL,
            date_sold TEXT
        )
        """
    )

    cur.execute("PRAGMA table_info(property_prices)")
    cols = {row[1] for row in cur.fetchall()}
    if "postcode_district" not in cols:
        cur.execute("ALTER TABLE property_prices ADD COLUMN postcode_district TEXT")
        cur.execute("UPDATE property_prices SET postcode_district = '' WHERE postcode_district IS NULL")
    if "bedrooms" not in cols:
        cur.execute("ALTER TABLE property_prices ADD COLUMN bedrooms INTEGER DEFAULT 2")
    if "floor_area_sqft" not in cols:
        cur.execute("ALTER TABLE property_prices ADD COLUMN floor_area_sqft REAL")
    if "tenure" not in cols:
        cur.execute("ALTER TABLE property_prices ADD COLUMN tenure TEXT")
    if "new_build" not in cols:
        cur.execute("ALTER TABLE property_prices ADD COLUMN new_build INTEGER DEFAULT 0")

    cur.execute("SELECT COUNT(*) AS c FROM property_prices")
    if cur.fetchone()["c"] == 0:
        samples = [
            ("SW1A1AA", _postcode_district("SW1A1AA"), "semi-detached", 3, 1100, "freehold", 0, 430000, "2025-04-01"),
            ("SW1A1AA", _postcode_district("SW1A1AA"), "semi-detached", 3, 1120, "freehold", 0, 445000, "2025-02-10"),
            ("SW1A1AA", _postcode_district("SW1A1AA"), "semi-detached", 4, 1240, "freehold", 0, 455000, "2024-11-18"),
            ("SW1A2AA", _postcode_district("SW1A2AA"), "terraced", 3, 1020, "freehold", 0, 418000, "2024-09-02"),
            ("SW1A0AA", _postcode_district("SW1A0AA"), "flat", 2, 760, "leasehold", 0, 365000, "2025-01-20"),
            ("M11AE", _postcode_district("M11AE"), "terraced", 3, 980, "freehold", 0, 245000, "2025-01-11"),
            ("B11AA", _postcode_district("B11AA"), "flat", 2, 690, "leasehold", 0, 180000, "2024-12-01"),
            ("LS11AA", _postcode_district("LS11AA"), "detached", 4, 1500, "freehold", 0, 350000, "2025-03-15"),
            ("LS12AA", _postcode_district("LS12AA"), "semi-detached", 3, 1050, "freehold", 0, 270000, "2024-08-22"),
        ]
        cur.executemany(
            """
            INSERT INTO property_prices
            (postcode, postcode_district, property_type, bedrooms, floor_area_sqft, tenure, new_build, price, date_sold)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            samples,
        )

    cur.execute("SELECT id, postcode FROM property_prices WHERE postcode_district IS NULL OR postcode_district = ''")
    for row in cur.fetchall():
        cur.execute("UPDATE property_prices SET postcode_district = ? WHERE id = ?", (_postcode_district(row["postcode"]), row["id"]))

    conn.commit()
    conn.close()


def _to_bool_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    txt = str(value or "").strip().lower()
    return 1 if txt in {"1", "true", "yes", "y"} else 0


def ingest_comparable_rows(rows: Iterable[Dict]) -> Tuple[int, int]:
    conn = get_connection()
    cur = conn.cursor()
    inserted = 0
    failed = 0
    for row in rows:
        try:
            postcode = _normalize_postcode(str(row.get("postcode") or ""))
            property_type = str(row.get("property_type") or "").strip().lower()
            bedrooms = int(float(row.get("bedrooms") or 0))
            price = float(row.get("price") or 0)
            date_sold = str(row.get("date_sold") or "").strip() or None
            if not postcode or not property_type or bedrooms <= 0 or price <= 0:
                failed += 1
                continue

            floor_area = row.get("floor_area_sqft")
            floor_area_val = float(floor_area) if str(floor_area or "").strip() else None
            tenure = str(row.get("tenure") or "").strip() or None
            new_build = _to_bool_int(row.get("new_build", 0))

            cur.execute(
                """
                INSERT INTO property_prices
                (postcode, postcode_district, property_type, bedrooms, floor_area_sqft, tenure, new_build, price, date_sold)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (postcode, _postcode_district(postcode), property_type, bedrooms, floor_area_val, tenure, new_build, price, date_sold),
            )
            inserted += 1
        except Exception:
            failed += 1
    conn.commit()
    conn.close()
    return inserted, failed


def get_comparable_records(postcode: str, property_type: str, bedrooms: int, limit: int = 60) -> List[Dict]:
    conn = get_connection()
    cur = conn.cursor()
    norm = _normalize_postcode(postcode)
    district = _postcode_district(norm)
    cur.execute(
        """
        SELECT postcode, postcode_district, property_type, bedrooms, floor_area_sqft, tenure, new_build, price, date_sold
        FROM property_prices
        WHERE LOWER(property_type) = LOWER(?)
           OR postcode = ?
           OR postcode_district = ?
        ORDER BY date_sold DESC
        LIMIT ?
        """,
        (property_type, norm, district, int(limit)),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def postcode_property_benchmark(postcode: str, property_type: str, bedrooms: int) -> Dict[str, float]:
    rows = get_comparable_records(postcode, property_type, bedrooms, limit=120)
    if not rows:
        return {"mean_price": 285000.0, "median_price": 285000.0, "count": 0.0}
    prices = sorted(float(r["price"]) for r in rows if float(r.get("price") or 0) > 0)
    n = len(prices)
    median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2
    return {
        "mean_price": float(mean(prices)),
        "median_price": float(median),
        "count": float(n),
    }


def get_comparable_prices(postcode: str, property_type: str) -> List[float]:
    rows = get_comparable_records(postcode, property_type, bedrooms=2, limit=20)
    return [float(r["price"]) for r in rows]
