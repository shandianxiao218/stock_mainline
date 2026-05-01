from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_backtest_schema(conn: sqlite3.Connection | None = None) -> None:
    own_conn = conn is None
    if conn is None:
        conn = _conn()
    try:
        conn.executescript(
            """
            create table if not exists local_backtest_run (
                task_id text primary key,
                status text not null,
                request_json text not null,
                metrics_json text,
                samples_json text,
                note text,
                error text,
                started_at text not null,
                finished_at text,
                result_file text
            );

            create index if not exists idx_local_backtest_run_started
              on local_backtest_run(started_at desc);

            create index if not exists idx_local_backtest_run_status
              on local_backtest_run(status);
            """
        )
        conn.commit()
    finally:
        if own_conn:
            conn.close()


def create_backtest_run(request: dict[str, Any]) -> str:
    task_id = f"bt_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    with _conn() as conn:
        init_backtest_schema(conn)
        conn.execute(
            """
            insert into local_backtest_run(task_id, status, request_json, started_at)
            values (?, ?, ?, ?)
            """,
            (task_id, "running", json.dumps(request, ensure_ascii=False), _now()),
        )
        conn.commit()
    return task_id


def finish_backtest_run(task_id: str, result: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get("status", "completed"))
    result = {**result, "task_id": task_id}
    with _conn() as conn:
        init_backtest_schema(conn)
        conn.execute(
            """
            update local_backtest_run
            set status = ?, metrics_json = ?, samples_json = ?, note = ?, finished_at = ?
            where task_id = ?
            """,
            (
                status,
                json.dumps(result.get("metrics", {}), ensure_ascii=False),
                json.dumps(result.get("samples", []), ensure_ascii=False),
                str(result.get("note", "")),
                _now(),
                task_id,
            ),
        )
        conn.commit()
    return result


def fail_backtest_run(task_id: str, error: str) -> None:
    with _conn() as conn:
        init_backtest_schema(conn)
        conn.execute(
            """
            update local_backtest_run
            set status = ?, error = ?, finished_at = ?
            where task_id = ?
            """,
            ("failed", error, _now(), task_id),
        )
        conn.commit()


def list_backtest_runs(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    with _conn() as conn:
        init_backtest_schema(conn)
        rows = conn.execute(
            """
            select task_id, status, request_json, metrics_json, note, error, started_at, finished_at, result_file
            from local_backtest_run
            order by started_at desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "task_id": row["task_id"],
            "status": row["status"],
            "request": json.loads(row["request_json"] or "{}"),
            "metrics": json.loads(row["metrics_json"] or "{}"),
            "note": row["note"],
            "error": row["error"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "result_file": row["result_file"],
        }
        for row in rows
    ]
