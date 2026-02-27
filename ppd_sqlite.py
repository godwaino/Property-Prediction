from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional


@dataclass
class Comp:
    price: int
    date: str
    postcode: str
    property_type: str
    street: Optional[str] = None
    town: Optional[str] = None


def postcode_sector(pc: str) -> str:
    pc = (pc or "").strip().upper()
    m = re.match(r"^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})$", pc)
    if not m:
        return pc.split(" ")[0]
    outward = m.group(1)
    sector_digit = m.group(2)[:1]
    return f"{outward} {sector_digit}"


def looks_like_flat(property_type: Optional[str]) -> bool:
    t = (property_type or "").lower()
    return ("flat" in t) or ("apartment" in t)


def find_comps_sqlite(
    ppd_sqlite_path: str,
    postcode: Optional[str],
    property_type: Optional[str],
    months: int = 18,
    limit: int = 12,
) -> List[Comp]:
    if not postcode:
        return []

    sector = postcode_sector(postcode)
    like = sector + "%"

    cutoff = (datetime.utcnow() - timedelta(days=30 * months)).date().isoformat()

    ptype_filter = None
    if looks_like_flat(property_type):
        ptype_filter = "F"

    con = sqlite3.connect(ppd_sqlite_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    sql = """
      SELECT price, date, postcode, ptype, street, town
      FROM ppd_sales
      WHERE UPPER(postcode) LIKE ?
        AND date >= ?
    """
    params: list = [like, cutoff]

    if ptype_filter:
        sql += " AND ptype = ?"
        params.append(ptype_filter)

    sql += " ORDER BY date DESC LIMIT ?"
    params.append(limit)

    rows = cur.execute(sql, params).fetchall()
    con.close()

    comps: List[Comp] = []
    for r in rows:
        comps.append(
            Comp(
                price=int(r["price"]),
                date=str(r["date"]),
                postcode=str(r["postcode"]),
                property_type=str(r["ptype"]),
                street=r["street"],
                town=r["town"],
            )
        )
    return comps
