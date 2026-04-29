from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"

LEVEL_SCORES = {"S": 9.0, "A": 7.0, "B": 4.0, "C": 1.0}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists local_catalyst_event (
          id integer primary key autoincrement,
          trade_date text not null,
          theme_id text,
          theme_name text,
          title text not null,
          source text,
          level text not null,
          score real not null,
          note text,
          created_at text not null
        )
        """
    )


def list_catalysts(date: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(500, int(limit)))
    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        if date:
            rows = conn.execute(
                """
                select id, trade_date, theme_id, theme_name, title, source, level, score, note, created_at
                from local_catalyst_event
                where trade_date = ?
                order by id desc
                limit ?
                """,
                (date, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                select id, trade_date, theme_id, theme_name, title, source, level, score, note, created_at
                from local_catalyst_event
                order by id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
    return [row_to_dict(row) for row in rows]


def add_catalyst(body: dict[str, Any]) -> dict[str, Any]:
    trade_date = str(body.get("trade_date") or body.get("date") or "").strip()
    title = str(body.get("title") or "").strip()
    level = str(body.get("level") or "C").upper().strip()
    if not trade_date:
        raise ValueError("交易日期不能为空")
    if not title:
        raise ValueError("催化标题不能为空")
    if level not in LEVEL_SCORES:
        raise ValueError("催化等级必须为 S/A/B/C")
    score = float(body.get("score") or LEVEL_SCORES[level])
    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        cur = conn.execute(
            """
            insert into local_catalyst_event(trade_date, theme_id, theme_name, title, source, level, score, note, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_date,
                body.get("theme_id"),
                body.get("theme_name"),
                title,
                body.get("source"),
                level,
                score,
                body.get("note"),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        row = conn.execute(
            """
            select id, trade_date, theme_id, theme_name, title, source, level, score, note, created_at
            from local_catalyst_event
            where id = ?
            """,
            (cur.lastrowid,),
        ).fetchone()
    return row_to_dict(row)


def row_to_dict(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "trade_date": row[1],
        "theme_id": row[2],
        "theme_name": row[3],
        "title": row[4],
        "source": row[5],
        "level": row[6],
        "score": row[7],
        "note": row[8],
        "created_at": row[9],
    }
