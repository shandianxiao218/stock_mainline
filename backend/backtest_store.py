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


def get_backtest_run(task_id: str) -> dict[str, Any] | None:
    with _conn() as conn:
        init_backtest_schema(conn)
        row = conn.execute(
            """
            select task_id, status, request_json, metrics_json, samples_json, note, error,
                   started_at, finished_at, result_file
            from local_backtest_run
            where task_id = ?
            """,
            (task_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "task_id": row["task_id"],
        "status": row["status"],
        "request": json.loads(row["request_json"] or "{}"),
        "metrics": json.loads(row["metrics_json"] or "{}"),
        "samples": json.loads(row["samples_json"] or "[]"),
        "note": row["note"],
        "error": row["error"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "result_file": row["result_file"],
    }


def cancel_backtest_run(task_id: str) -> bool:
    """取消一个运行中的回测任务。仅 status=running 时可取消。"""
    with _conn() as conn:
        init_backtest_schema(conn)
        row = conn.execute(
            "SELECT status FROM local_backtest_run WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if not row or row["status"] != "running":
            return False
        conn.execute(
            "UPDATE local_backtest_run SET status = ?, error = ?, finished_at = ? WHERE task_id = ?",
            ("cancelled", "用户手动取消", _now(), task_id),
        )
        conn.commit()
    return True


def estimate_progress(task_id: str) -> float:
    """估算回测进度百分比（0.0~1.0）。

    基于已运行时间和请求数据区间长度做粗略估算。
    """
    with _conn() as conn:
        init_backtest_schema(conn)
        row = conn.execute(
            "SELECT status, request_json, started_at FROM local_backtest_run WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    if not row:
        return 0.0
    if row["status"] != "running":
        return 1.0 if row["status"] == "completed" else 0.0
    try:
        request = json.loads(row["request_json"] or "{}")
        start = request.get("start_date", "20210101")
        end = request.get("end_date", "20991231")
        # 计算总天数
        start_int = int(str(start).replace("-", ""))
        end_int = int(str(end).replace("-", ""))
        total_days = max(1, (end_int // 10000 * 365 + (end_int % 10000 // 100) * 30 + end_int % 100)
                         - (start_int // 10000 * 365 + (start_int % 10000 // 100) * 30 + start_int % 100))
        # 已运行时间估算
        started = datetime.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S")
        elapsed_seconds = max(1, (datetime.now() - started).total_seconds())
        # 假设每天回测约 0.3 秒（经验值）
        estimated_total_seconds = total_days * 0.3
        progress = min(0.95, elapsed_seconds / max(estimated_total_seconds, 1))
        return round(progress, 2)
    except Exception:
        return 0.5  # 无法估算时返回 50%


def save_result_file(task_id: str, content: bytes, filename: str) -> str:
    """保存回测结果到文件，返回文件路径。"""
    result_dir = ROOT_DIR / "backend" / "data" / "backtest_results"
    result_dir.mkdir(parents=True, exist_ok=True)
    filepath = result_dir / filename
    filepath.write_bytes(content)
    with _conn() as conn:
        init_backtest_schema(conn)
        conn.execute(
            "UPDATE local_backtest_run SET result_file = ? WHERE task_id = ?",
            (str(filepath), task_id),
        )
        conn.commit()
    return str(filepath)
