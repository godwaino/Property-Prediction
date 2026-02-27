from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional


def init_db(db_path: str) -> None:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at_utc TEXT NOT NULL,
            url TEXT NOT NULL,
            property_id TEXT,
            facts_json TEXT,
            comps_json TEXT,
            valuation_json TEXT,
            md_report TEXT
        )
        """
    )
    con.commit()
    con.close()


def save_analysis(db_path: str, result: Dict[str, Any]) -> int:
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    facts = result.get("facts") or {}
    valuation = result.get("valuation") or {}
    comps = result.get("comps") or []
    cur.execute(
        """
        INSERT INTO analyses (created_at_utc, url, property_id, facts_json, comps_json, valuation_json, md_report)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.get("created_at_utc") or "",
            facts.get("url") or result.get("url") or "",
            facts.get("property_id") or "",
            json.dumps(facts),
            json.dumps(comps),
            json.dumps(valuation),
            result.get("md_report") or "",
        ),
    )
    con.commit()
    new_id = cur.lastrowid
    con.close()
    return int(new_id)


def list_analyses(db_path: str, limit: int = 30) -> List[Dict[str, Any]]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT id, created_at_utc, url, property_id, valuation_json
        FROM analyses ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        valuation: Dict[str, Any] = {}
        try:
            valuation = json.loads(r["valuation_json"] or "{}")
        except Exception:
            pass
        out.append(
            {
                "id": r["id"],
                "created_at_utc": r["created_at_utc"],
                "url": r["url"],
                "property_id": r["property_id"],
                "valuation": valuation,
            }
        )
    con.close()
    return out


def get_analysis(db_path: str, analysis_id: int) -> Optional[Dict[str, Any]]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    r = cur.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    con.close()
    if not r:
        return None

    facts: Dict[str, Any] = {}
    comps: List[Any] = []
    valuation: Dict[str, Any] = {}
    try:
        facts = json.loads(r["facts_json"] or "{}")
    except Exception:
        pass
    try:
        comps = json.loads(r["comps_json"] or "[]")
    except Exception:
        pass
    try:
        valuation = json.loads(r["valuation_json"] or "{}")
    except Exception:
        pass

    return {
        "id": r["id"],
        "created_at_utc": r["created_at_utc"],
        "url": r["url"],
        "property_id": r["property_id"],
        "facts": facts,
        "comps": comps,
        "valuation": valuation,
        "md_report": r["md_report"] or "",
    }
