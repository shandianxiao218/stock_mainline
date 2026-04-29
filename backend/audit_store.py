from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists local_audit_log (
          id integer primary key autoincrement,
          event_time text not null,
          actor text not null,
          event_type text not null,
          method text,
          path text,
          target text,
          detail_json text
        )
        """
    )


def write_audit(
    event_type: str,
    *,
    method: str | None = None,
    path: str | None = None,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
    actor: str = "local_user",
) -> None:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            init_schema(conn)
            conn.execute(
                """
                insert into local_audit_log(event_time, actor, event_type, method, path, target, detail_json)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    actor,
                    event_type,
                    method,
                    path,
                    target,
                    json.dumps(detail or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
    except sqlite3.Error:
        pass


def list_audit_logs(limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(500, int(limit)))
    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        rows = conn.execute(
            """
            select id, event_time, actor, event_type, method, path, target, detail_json
            from local_audit_log
            order by id desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": row[0],
            "event_time": row[1],
            "actor": row[2],
            "event_type": row[3],
            "method": row[4],
            "path": row[5],
            "target": row[6],
            "detail": json.loads(row[7] or "{}"),
        }
        for row in rows
    ]
