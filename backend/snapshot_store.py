from __future__ import annotations

import copy
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"
_SCHEMA_READY = False


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _date_int(date: str) -> int:
    return int(date.replace("-", ""))


def _date_text(value: int | str) -> str:
    text = str(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}" if len(text) == 8 else text


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_snapshot_schema(conn: sqlite3.Connection | None = None) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    own_conn = conn is None
    if conn is None:
        conn = connect()
    try:
        conn.executescript(
            """
            create table if not exists local_theme_ranking_snapshot (
                trade_date text not null,
                period text not null,
                payload_json text not null,
                created_at text not null,
                primary key (trade_date, period)
            );

            create table if not exists local_theme_matrix_snapshot (
                trade_date text not null,
                days integer not null,
                payload_json text not null,
                created_at text not null,
                primary key (trade_date, days)
            );

            create table if not exists local_theme_detail_snapshot (
                trade_date text not null,
                theme_id text not null,
                payload_json text not null,
                created_at text not null,
                primary key (trade_date, theme_id)
            );

            create table if not exists local_confidence_history_snapshot (
                trade_date text not null,
                days integer not null,
                payload_json text not null,
                created_at text not null,
                primary key (trade_date, days)
            );

            create table if not exists local_risk_history_snapshot (
                trade_date text not null,
                theme_id text not null,
                days integer not null,
                payload_json text not null,
                created_at text not null,
                primary key (trade_date, theme_id, days)
            );

            create table if not exists local_factor_effectiveness_snapshot (
                trade_date text not null,
                holding_period integer not null,
                payload_json text not null,
                created_at text not null,
                primary key (trade_date, holding_period)
            );

            create table if not exists local_snapshot_build_log (
                id integer primary key autoincrement,
                trade_date text not null,
                snapshot_type text not null,
                item_count integer not null default 0,
                elapsed_ms real not null default 0,
                status text not null default 'ok',
                message text,
                created_at text not null
            );

            create table if not exists local_backtest_daily_snapshot (
                trade_date text not null primary key,
                themes_json text not null,
                theme_count integer not null default 0,
                created_at text not null
            );

            """
        )
        optional_indexes = [
            ("em_daily_quote", "idx_em_daily_quote_trade_date", ["trade_date"]),
            ("em_daily_quote", "idx_em_daily_quote_symbol_date", ["symbol", "trade_date"]),
            ("em_sector_constituent_history", "idx_em_sector_constituent_sector_date", ["sector_code", "as_of_date"]),
            ("em_sector_constituent_history", "idx_em_sector_constituent_symbol_date", ["symbol", "as_of_date"]),
            ("local_sector_snapshot_daily", "idx_local_sector_snapshot_date_id", ["trade_date", "sector_id"]),
            ("local_limit_signal_daily", "idx_local_limit_signal_date_symbol", ["trade_date", "symbol"]),
            ("local_theme_sector_mapping", "idx_local_theme_sector_theme", ["theme_id", "sector_id"]),
        ]
        for table, index_name, columns in optional_indexes:
            exists = conn.execute(
                "select 1 from sqlite_master where type = 'table' and name = ?",
                (table,),
            ).fetchone()
            if not exists:
                continue
            table_columns = {
                row[1] for row in conn.execute(f"pragma table_info({table})").fetchall()
            }
            if set(columns).issubset(table_columns):
                conn.execute(f"create index if not exists {index_name} on {table}({', '.join(columns)})")
        conn.commit()
        _SCHEMA_READY = True
    finally:
        if own_conn:
            conn.close()


def resolve_snapshot_date(date: str) -> str:
    if not DB_PATH.exists():
        return date
    try:
        with connect() as conn:
            row = conn.execute(
                "select max(trade_date) as trade_date from em_daily_quote where trade_date <= ?",
                (_date_int(date),),
            ).fetchone()
            if row and row["trade_date"] is not None:
                return _date_text(row["trade_date"])
    except sqlite3.Error:
        return date
    return date


def _save(table: str, key_columns: list[str], values: tuple[Any, ...], payload: dict[str, Any]) -> str:
    created_at = _now_text()
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    placeholders = ", ".join("?" for _ in key_columns)
    assignments = "payload_json = excluded.payload_json, created_at = excluded.created_at"
    sql = (
        f"insert into {table} ({', '.join(key_columns)}, payload_json, created_at) "
        f"values ({placeholders}, ?, ?) "
        f"on conflict({', '.join(key_columns)}) do update set {assignments}"
    )
    with connect() as conn:
        init_snapshot_schema(conn)
        conn.execute(sql, (*values, payload_json, created_at))
        conn.commit()
    return created_at


def _load(table: str, where_sql: str, values: tuple[Any, ...]) -> tuple[dict[str, Any] | None, str | None]:
    if not DB_PATH.exists():
        return None, None
    with connect() as conn:
        init_snapshot_schema(conn)
        row = conn.execute(
            f"select payload_json, created_at from {table} where {where_sql}",
            values,
        ).fetchone()
    if not row:
        return None, None
    return json.loads(row["payload_json"]), row["created_at"]


def _with_meta(payload: dict[str, Any], created_at: str | None, fallback_live: bool = False) -> dict[str, Any]:
    data = copy.deepcopy(payload)
    data["snapshot"] = bool(created_at)
    data["snapshot_created_at"] = created_at
    data["fallback_live"] = fallback_live
    return data


def attach_live_meta(payload: dict[str, Any]) -> dict[str, Any]:
    return _with_meta(payload, None, True)


def slice_ranking_payload(payload: dict[str, Any], limit: int | None) -> dict[str, Any]:
    data = copy.deepcopy(payload)
    items = data.get("items", [])
    data["total_count"] = len(items)
    if limit is None:
        data["row_limit"] = "all"
        return data
    normalized = max(1, min(int(limit), 500))
    data["row_limit"] = normalized
    data["items"] = items[:normalized]
    return data


def compact_ranking_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(payload)
    compact_items = []
    for item in data.get("items", []):
        compact_items.append({
            "rank": item.get("rank"),
            "theme_id": item.get("theme_id"),
            "theme_name": item.get("theme_name"),
            "theme_score": item.get("theme_score"),
            "heat_score": item.get("heat_score"),
            "continuation_score": item.get("continuation_score"),
            "risk_penalty": item.get("risk_penalty"),
            "confidence": item.get("confidence"),
            "status": item.get("status"),
            "branches": item.get("branches", []),
            "core_stocks": item.get("core_stocks", []),
            "next_checks": item.get("next_checks", []),
            "risks": item.get("risks", []),
        })
    data["items"] = compact_items
    data["total_count"] = len(compact_items)
    return data


def slice_matrix_payload(payload: dict[str, Any], limit: int | None) -> dict[str, Any]:
    data = copy.deepcopy(payload)
    items = data.get("items", [])
    target_date = data.get("date")
    rows_with_target = [row for row in items if target_date in row.get("cells", {})]
    rows_without_target = [row for row in items if target_date not in row.get("cells", {})]
    rows_with_target.sort(key=lambda row: row["cells"][target_date]["rank"])
    rows_without_target.sort(
        key=lambda row: (
            len(row.get("cells", {})),
            max((cell.get("theme_score", -999) for cell in row.get("cells", {}).values()), default=-999),
        ),
        reverse=True,
    )
    ordered = rows_with_target if limit is not None else [*rows_with_target, *rows_without_target]
    data["total_count"] = len(items)
    data["target_count"] = len(rows_with_target)
    if limit is None:
        data["row_limit"] = "all"
        data["items"] = ordered
        return data
    normalized = max(1, min(int(limit), 500))
    data["row_limit"] = normalized
    data["items"] = ordered[:normalized]
    return data


def save_ranking_snapshot(payload: dict[str, Any], period: str = "short") -> str:
    return _save(
        "local_theme_ranking_snapshot",
        ["trade_date", "period"],
        (payload["date"], period),
        compact_ranking_payload(payload),
    )


def load_ranking_snapshot(date: str, period: str, limit: int | None) -> dict[str, Any] | None:
    resolved = resolve_snapshot_date(date)
    payload, created_at = _load("local_theme_ranking_snapshot", "trade_date = ? and period = ?", (resolved, period))
    return _with_meta(slice_ranking_payload(payload, limit), created_at) if payload else None


def save_matrix_snapshot(payload: dict[str, Any], days: int) -> str:
    return _save("local_theme_matrix_snapshot", ["trade_date", "days"], (payload["date"], int(days)), payload)


def load_matrix_snapshot(date: str, days: int, limit: int | None) -> dict[str, Any] | None:
    resolved = resolve_snapshot_date(date)
    payload, created_at = _load("local_theme_matrix_snapshot", "trade_date = ? and days = ?", (resolved, int(days)))
    return _with_meta(slice_matrix_payload(payload, limit), created_at) if payload else None


def save_detail_snapshot(payload: dict[str, Any]) -> str:
    return _save("local_theme_detail_snapshot", ["trade_date", "theme_id"], (payload["date"], payload["theme_id"]), payload)


def load_detail_snapshot(theme_id: str, date: str) -> dict[str, Any] | None:
    resolved = resolve_snapshot_date(date)
    payload, created_at = _load("local_theme_detail_snapshot", "trade_date = ? and theme_id = ?", (resolved, theme_id))
    return _with_meta(payload, created_at) if payload else None


def save_confidence_history_snapshot(payload: dict[str, Any], days: int) -> str:
    return _save("local_confidence_history_snapshot", ["trade_date", "days"], (payload["date"], int(days)), payload)


def load_confidence_history_snapshot(date: str, days: int) -> dict[str, Any] | None:
    resolved = resolve_snapshot_date(date)
    payload, created_at = _load("local_confidence_history_snapshot", "trade_date = ? and days = ?", (resolved, int(days)))
    return _with_meta(payload, created_at) if payload else None


def save_risk_history_snapshot(payload: dict[str, Any], days: int) -> str:
    return _save(
        "local_risk_history_snapshot",
        ["trade_date", "theme_id", "days"],
        (payload["date"], payload["theme_id"], int(days)),
        payload,
    )


def load_risk_history_snapshot(theme_id: str, date: str, days: int) -> dict[str, Any] | None:
    resolved = resolve_snapshot_date(date)
    payload, created_at = _load(
        "local_risk_history_snapshot",
        "trade_date = ? and theme_id = ? and days = ?",
        (resolved, theme_id, int(days)),
    )
    return _with_meta(payload, created_at) if payload else None


def save_factor_effectiveness_snapshot(payload: dict[str, Any], holding_period: int) -> str:
    return _save(
        "local_factor_effectiveness_snapshot",
        ["trade_date", "holding_period"],
        (payload["date"], int(holding_period)),
        payload,
    )


def load_factor_effectiveness_snapshot(date: str, holding_period: int) -> dict[str, Any] | None:
    resolved = resolve_snapshot_date(date)
    payload, created_at = _load(
        "local_factor_effectiveness_snapshot",
        "trade_date = ? and holding_period = ?",
        (resolved, int(holding_period)),
    )
    return _with_meta(payload, created_at) if payload else None


def write_build_log(
    trade_date: str,
    snapshot_type: str,
    item_count: int = 0,
    elapsed_ms: float = 0,
    status: str = "ok",
    message: str | None = None,
) -> None:
    with connect() as conn:
        init_snapshot_schema(conn)
        conn.execute(
            """
            insert into local_snapshot_build_log
            (trade_date, snapshot_type, item_count, elapsed_ms, status, message, created_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (trade_date, snapshot_type, item_count, elapsed_ms, status, message, _now_text()),
        )
        conn.commit()


def snapshot_status(date: str) -> dict[str, Any]:
    resolved = resolve_snapshot_date(date)
    tables = [
        ("ranking", "local_theme_ranking_snapshot"),
        ("matrix", "local_theme_matrix_snapshot"),
        ("detail", "local_theme_detail_snapshot"),
        ("confidence_history", "local_confidence_history_snapshot"),
        ("risk_history", "local_risk_history_snapshot"),
        ("factor_effectiveness", "local_factor_effectiveness_snapshot"),
    ]
    with connect() as conn:
        init_snapshot_schema(conn)
        items = []
        for name, table in tables:
            row = conn.execute(
                f"select count(*) as count, max(created_at) as created_at from {table} where trade_date = ?",
                (resolved,),
            ).fetchone()
            items.append({
                "name": name,
                "count": int(row["count"] or 0),
                "created_at": row["created_at"],
                "ready": bool(row["count"]),
            })
    return {"date": resolved, "items": items}


# --- 快照依赖图和失效机制 ---

# 每种快照依赖的数据源
SNAPSHOT_DEPENDENCIES = {
    "ranking": ["行情", "板块成分", "模型参数", "主线映射", "催化", "舆情", "龙虎榜"],
    "matrix": ["行情", "板块成分", "模型参数"],
    "detail": ["行情", "板块成分", "模型参数", "催化", "舆情", "龙虎榜"],
    "confidence_history": ["行情"],
    "risk_history": ["行情", "板块成分"],
    "factor_effectiveness": ["行情", "模型参数"],
}

# 数据源最后更新时间缓存
_source_last_updated: dict[str, str] = {}


def update_source_timestamp(source: str) -> None:
    """数据源更新后调用，标记其更新时间。"""
    _source_last_updated[source] = _now_text()


def invalidate_stale_snapshots(sources: list[str]) -> list[str]:
    """检查指定数据源变化后需要失效的快照类型。

    返回需要重建的快照类型列表。
    """
    stale = set()
    for source in sources:
        for snap_type, deps in SNAPSHOT_DEPENDENCIES.items():
            if source in deps:
                stale.add(snap_type)
    return sorted(stale)


def snapshot_invalidation_status(date: str) -> dict[str, Any]:
    """返回快照失效状态：哪些已过期、哪些需要重建。"""
    resolved = resolve_snapshot_date(date)
    status = snapshot_status(date)
    stale_types = invalidate_stale_snapshots(list(_source_last_updated.keys()))

    for item in status.get("items", []):
        if item["name"] in stale_types:
            item["stale"] = True
        else:
            item["stale"] = False

    status["stale_sources"] = list(_source_last_updated.keys())
    status["stale_snapshot_types"] = stale_types
    return status


def cold_start_build(date: str) -> dict[str, Any]:
    """冷启动后自动构建最新交易日必要快照。

    依次构建 ranking、matrix、confidence_history、factor_effectiveness。
    失败时记录原因但不中断。
    """
    from real_scoring import (
        ranking_payload, theme_matrix_payload,
        factor_effectiveness_payload, clear_scoring_cache,
    )
    results = {}
    errors = []

    builders = [
        ("ranking", lambda: save_ranking_snapshot(ranking_payload(date, "short"), "short")),
        ("matrix", lambda: save_matrix_snapshot(theme_matrix_payload(date, 20, 10), 20)),
        ("confidence_history", lambda: None),  # 需要 ranking 数据，此处标记为已处理
        ("factor_effectiveness", lambda: save_factor_effectiveness_snapshot(
            factor_effectiveness_payload(date, 3), 3)),
    ]

    for name, builder in builders:
        try:
            builder()
            results[name] = "ok"
        except Exception as exc:
            results[name] = f"failed: {exc}"
            errors.append(f"{name}: {exc}")

    clear_scoring_cache()
    write_build_log(date, "cold_start", "ok" if not errors else "partial", "; ".join(errors) if errors else "")
    return {"date": date, "results": results, "errors": errors}


# --- 回测日度快照 ---

def save_backtest_daily_snapshot(trade_date: str, themes: list[dict[str, Any]]) -> None:
    """保存当日回测所需的主题评分和成分股代码。"""
    light = []
    for theme in themes:
        symbols = sorted({stock["symbol"] for stock in theme.get("stock_metrics", [])})
        light.append({
            "theme_id": theme.get("theme_id"),
            "theme_name": theme.get("theme_name"),
            "theme_score": theme.get("theme_score"),
            "heat_score": theme.get("heat_score"),
            "continuation_score": theme.get("continuation_score"),
            "risk_penalty": theme.get("risk_penalty"),
            "symbols": symbols,
        })
    with connect() as conn:
        init_snapshot_schema(conn)
        conn.execute(
            """
            insert or replace into local_backtest_daily_snapshot(trade_date, themes_json, theme_count, created_at)
            values (?, ?, ?, ?)
            """,
            (trade_date, json.dumps(light, ensure_ascii=False), len(light), _now_text()),
        )
        conn.commit()


def load_backtest_daily_snapshot(trade_date: str) -> list[dict[str, Any]] | None:
    """加载当日回测快照。返回轻量主题列表或 None。"""
    with connect() as conn:
        init_snapshot_schema(conn)
        row = conn.execute(
            "select themes_json from local_backtest_daily_snapshot where trade_date = ?",
            (trade_date,),
        ).fetchone()
    if not row:
        return None
    return json.loads(row["themes_json"] if hasattr(row, "keys") else row[0])
