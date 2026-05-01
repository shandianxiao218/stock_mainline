from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Callable

from snapshot_store import (
    load_confidence_history_snapshot,
    load_detail_snapshot,
    load_matrix_snapshot,
    load_ranking_snapshot,
    load_risk_history_snapshot,
    snapshot_status,
)


def measure(name: str, fn: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
    started = time.perf_counter()
    payload = fn()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "name": name,
        "elapsed_ms": round(elapsed_ms, 3),
        "hit": bool(payload and payload.get("snapshot")),
        "items": len(payload.get("items", [])) if payload else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查快照读取是否满足页面 100ms 目标")
    parser.add_argument("--date", default="2026-04-29")
    parser.add_argument("--days", type=int, default=20)
    parser.add_argument("--threshold-ms", type=float, default=100.0)
    args = parser.parse_args()

    ranking = load_ranking_snapshot(args.date, "short", 10)
    top_theme_id = None
    if ranking and ranking.get("items"):
        top_theme_id = ranking["items"][0]["theme_id"]

    checks = [
        measure("ranking_top10", lambda: load_ranking_snapshot(args.date, "short", 10)),
        measure("matrix_top10", lambda: load_matrix_snapshot(args.date, args.days, 10)),
        measure("confidence_history", lambda: load_confidence_history_snapshot(args.date, args.days)),
    ]
    if top_theme_id:
        checks.extend([
            measure("detail_top1", lambda: load_detail_snapshot(top_theme_id, args.date)),
            measure("risk_history_top1", lambda: load_risk_history_snapshot(top_theme_id, args.date, args.days)),
        ])

    print("快照状态：", snapshot_status(args.date))
    failed = False
    for row in checks:
        ok = row["hit"] and row["elapsed_ms"] <= args.threshold_ms
        failed = failed or not ok
        print(
            f"{row['name']}: hit={row['hit']} elapsed_ms={row['elapsed_ms']} "
            f"items={row['items']} ok={ok}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
