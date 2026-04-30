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


def sector_constituents(sector_code: str, limit: int = 500, as_of_date: str | None = None) -> dict[str, Any]:
    limit = max(1, min(2000, int(limit)))
    with sqlite3.connect(DB_PATH) as conn:
        sector = conn.execute(
            "select sector_code, sector_name, source from em_sector where sector_code = ?",
            (sector_code,),
        ).fetchone()
        if as_of_date:
            rows = conn.execute(
                """
                select c.symbol, coalesce(s.name, c.symbol), c.market, c.as_of_date
                from em_sector_constituent_history c
                left join em_stock s on s.symbol = c.symbol
                where c.sector_code = ? and c.as_of_date <= ?
                group by c.symbol
                having c.as_of_date = max(c.as_of_date)
                order by c.symbol
                limit ?
                """,
                (sector_code, as_of_date, limit),
            ).fetchall()
        else:
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
        "as_of_date": as_of_date,
        "items": [
            {"symbol": row[0], "name": row[1], "market": row[2], "as_of_date": row[3]}
            for row in rows
        ],
    }


def sector_constituent_dates(sector_code: str) -> list[str]:
    """返回板块成分的所有快照日期。"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            select distinct as_of_date
            from em_sector_constituent_history
            where sector_code = ? and as_of_date is not null
            order by as_of_date desc
            """,
            (sector_code,),
        ).fetchall()
    return [row[0] for row in rows]


def sector_diff(sector_code: str, date_a: str, date_b: str) -> dict[str, Any]:
    """对比板块在两个日期的成分差异。"""
    with sqlite3.connect(DB_PATH) as conn:
        sector = conn.execute(
            "select sector_code, sector_name, source from em_sector where sector_code = ?",
            (sector_code,),
        ).fetchone()
        symbols_a = set(
            row[0] for row in conn.execute(
                "select symbol from em_sector_constituent_history where sector_code = ? and as_of_date = ?",
                (sector_code, date_a),
            ).fetchall()
        )
        symbols_b = set(
            row[0] for row in conn.execute(
                "select symbol from em_sector_constituent_history where sector_code = ? and as_of_date = ?",
                (sector_code, date_b),
            ).fetchall()
        )
    added = sorted(symbols_b - symbols_a)
    removed = sorted(symbols_a - symbols_b)
    unchanged = sorted(symbols_a & symbols_b)
    return {
        "sector_code": sector_code,
        "sector_name": sector[1] if sector else None,
        "date_a": date_a,
        "date_b": date_b,
        "count_a": len(symbols_a),
        "count_b": len(symbols_b),
        "added": added,
        "removed": removed,
        "unchanged": unchanged,
        "change_rate": round(len(added) + len(removed), 2) / max(len(symbols_a), 1),
    }
