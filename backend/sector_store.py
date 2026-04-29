from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"


def list_sectors(query: str = "", limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(500, int(limit)))
    pattern = f"%{query.strip()}%"
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            select s.sector_code, s.sector_name, s.source, count(c.symbol) as stock_count
            from em_sector s
            left join em_sector_constituent_history c on c.sector_code = s.sector_code
            where (? = '%%' or s.sector_code like ? or s.sector_name like ?)
            group by s.sector_code, s.sector_name, s.source
            order by stock_count desc, s.sector_code
            limit ?
            """,
            (pattern, pattern, pattern, limit),
        ).fetchall()
    return [
        {"sector_code": row[0], "sector_name": row[1], "source": row[2], "stock_count": row[3]}
        for row in rows
    ]


def sector_constituents(sector_code: str, limit: int = 500) -> dict[str, Any]:
    limit = max(1, min(2000, int(limit)))
    with sqlite3.connect(DB_PATH) as conn:
        sector = conn.execute(
            "select sector_code, sector_name, source from em_sector where sector_code = ?",
            (sector_code,),
        ).fetchone()
        rows = conn.execute(
            """
            select c.symbol, coalesce(s.name, c.symbol), c.market, c.as_of_date
            from em_sector_constituent_history c
            left join em_stock s on s.symbol = c.symbol
            where c.sector_code = ?
            order by c.symbol
            limit ?
            """,
            (sector_code, limit),
        ).fetchall()
    return {
        "sector_code": sector_code,
        "sector_name": sector[1] if sector else None,
        "source": sector[2] if sector else None,
        "items": [
            {"symbol": row[0], "name": row[1], "market": row[2], "as_of_date": row[3]}
            for row in rows
        ],
    }
