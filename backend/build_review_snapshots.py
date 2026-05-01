from __future__ import annotations

import argparse
import time
from typing import Any, Callable

from real_scoring import (
    confidence_history_payload,
    db_ready,
    detail_payload,
    factor_effectiveness_payload,
    ranking_payload,
    risk_history_payload,
    theme_matrix_payload,
)
from snapshot_store import (
    init_snapshot_schema,
    resolve_snapshot_date,
    save_confidence_history_snapshot,
    save_detail_snapshot,
    save_factor_effectiveness_snapshot,
    save_matrix_snapshot,
    save_ranking_snapshot,
    save_risk_history_snapshot,
    snapshot_status,
    write_build_log,
)


def timed_build(trade_date: str, snapshot_type: str, fn: Callable[[], tuple[int, Any]]) -> Any:
    started = time.perf_counter()
    try:
        item_count, payload = fn()
        elapsed_ms = (time.perf_counter() - started) * 1000
        write_build_log(trade_date, snapshot_type, item_count, elapsed_ms)
        print(f"{snapshot_type}: {item_count} 项，{elapsed_ms:.1f} ms")
        return payload
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        write_build_log(trade_date, snapshot_type, 0, elapsed_ms, "failed", str(exc))
        raise


def build_snapshots(date: str, days: int = 20, holding_period: int = 3, detail_limit: int = 100) -> dict[str, Any]:
    if not db_ready():
        raise RuntimeError("本地 SQLite 数据库不存在，不能构建快照")
    init_snapshot_schema()
    trade_date = resolve_snapshot_date(date)

    def build_ranking() -> tuple[int, dict[str, Any]]:
        payload = ranking_payload(trade_date, "short", None)
        save_ranking_snapshot(payload, "short")
        return len(payload.get("items", [])), payload

    ranking = timed_build(trade_date, "ranking", build_ranking)

    def build_matrix() -> tuple[int, dict[str, Any]]:
        payload = theme_matrix_payload(trade_date, days, None)
        save_matrix_snapshot(payload, days)
        return len(payload.get("items", [])), payload

    timed_build(trade_date, "matrix", build_matrix)

    def build_confidence() -> tuple[int, dict[str, Any]]:
        payload = confidence_history_payload(trade_date, days)
        save_confidence_history_snapshot(payload, days)
        return len(payload.get("items", [])), payload

    timed_build(trade_date, "confidence_history", build_confidence)

    def build_factors() -> tuple[int, dict[str, Any]]:
        payload = factor_effectiveness_payload(trade_date, holding_period)
        save_factor_effectiveness_snapshot(payload, holding_period)
        return len(payload.get("items", [])), payload

    timed_build(trade_date, "factor_effectiveness", build_factors)

    detail_items = ranking.get("items", [])[: max(1, min(int(detail_limit), 500))]

    def build_details() -> tuple[int, list[dict[str, Any]]]:
        payloads = []
        for item in detail_items:
            detail = detail_payload(item["theme_id"], trade_date)
            if detail:
                save_detail_snapshot(detail)
                payloads.append(detail)
        return len(payloads), payloads

    timed_build(trade_date, "detail", build_details)

    def build_risks() -> tuple[int, list[dict[str, Any]]]:
        payloads = []
        for item in detail_items:
            payload = risk_history_payload(item["theme_id"], trade_date, days)
            save_risk_history_snapshot(payload, days)
            payloads.append(payload)
        return len(payloads), payloads

    timed_build(trade_date, "risk_history", build_risks)
    return snapshot_status(trade_date)


def retry_failed_snapshots(date: str, days: int = 20, holding_period: int = 3, detail_limit: int = 100) -> None:
    """读取构建日志中失败记录，仅重试失败步骤。"""
    if not db_ready():
        raise RuntimeError("本地 SQLite 数据库不存在")
    init_snapshot_schema()
    trade_date = resolve_snapshot_date(date)

    import sqlite3
    from snapshot_store import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        failed = conn.execute(
            """
            select snapshot_type from local_snapshot_build_log
            where trade_date = ? and status = 'failed'
            order by id desc
            """,
            (trade_date,),
        ).fetchall()
    failed_types = list({row[0] for row in failed})
    if not failed_types:
        print(f"{trade_date}: 无失败快照，无需重试")
        return
    print(f"{trade_date}: 发现失败快照类型 {failed_types}，开始重试...")
    build_snapshots(date, days, holding_period, detail_limit)


def main() -> None:
    parser = argparse.ArgumentParser(description="构建收盘复盘预计算快照")
    parser.add_argument("--date", default="2026-04-29", help="目标交易日，非交易日会自动回退到最近交易日")
    parser.add_argument("--days", type=int, default=20, help="历史窗口交易日数量")
    parser.add_argument("--holding-period", type=int, default=3, help="因子有效性持有期")
    parser.add_argument("--detail-limit", type=int, default=100, help="为前 N 条主线构建详情和风险历史")
    parser.add_argument("--retry-failed", action="store_true", help="仅重试上次失败的快照类型")
    args = parser.parse_args()

    if args.retry_failed:
        retry_failed_snapshots(args.date, args.days, args.holding_period, args.detail_limit)
    else:
        status = build_snapshots(args.date, args.days, args.holding_period, args.detail_limit)
        print("快照状态：")
        for item in status["items"]:
            print(f"- {item['name']}: {item['count']} 条，ready={item['ready']}，created_at={item['created_at']}")


if __name__ == "__main__":
    main()
