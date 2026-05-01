from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"


def _date_text(value: int | str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}" if len(text) == 8 else text


def _parse_date(value: int | str | None) -> datetime | None:
    text = _date_text(value)
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d")


def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f"select count(*) from {table}").fetchone()[0])
    except sqlite3.Error:
        return 0


def data_coverage_payload(required_years: float = 5.0) -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"status": "missing_db", "db_path": str(DB_PATH), "items": []}
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        quote = conn.execute(
            """
            select min(trade_date) as min_date,
                   max(trade_date) as max_date,
                   count(*) as quote_count,
                   count(distinct trade_date) as trade_day_count,
                   count(distinct symbol) as symbol_count
            from em_daily_quote
            """
        ).fetchone()
        sector_versions = conn.execute(
            """
            select min(as_of_date) as min_as_of,
                   max(as_of_date) as max_as_of,
                   count(*) as row_count,
                   count(distinct as_of_date) as version_count
            from em_sector_constituent_history
            """
        ).fetchone()

        min_date = _parse_date(quote["min_date"])
        max_date = _parse_date(quote["max_date"])
        span_days = (max_date - min_date).days + 1 if min_date and max_date else 0
        span_years = round(span_days / 365.25, 2) if span_days else 0
        required_days = int(required_years * 365.25)

        snapshot_counts = {
            "ranking": _count(conn, "local_theme_ranking_snapshot"),
            "matrix": _count(conn, "local_theme_matrix_snapshot"),
            "detail": _count(conn, "local_theme_detail_snapshot"),
            "confidence_history": _count(conn, "local_confidence_history_snapshot"),
            "risk_history": _count(conn, "local_risk_history_snapshot"),
            "factor_effectiveness": _count(conn, "local_factor_effectiveness_snapshot"),
        }

    coverage_ok = span_days >= required_days
    has_sector_versions = int(sector_versions["version_count"] or 0) > 1
    status = "ok" if coverage_ok and has_sector_versions else "warning"
    return {
        "status": status,
        "required_years": required_years,
        "coverage": {
            "start_date": _date_text(quote["min_date"]),
            "end_date": _date_text(quote["max_date"]),
            "calendar_span_days": span_days,
            "span_years": span_years,
            "trade_day_count": int(quote["trade_day_count"] or 0),
            "symbol_count": int(quote["symbol_count"] or 0),
            "quote_count": int(quote["quote_count"] or 0),
            "five_year_ready": coverage_ok,
        },
        "sector_constituents": {
            "row_count": int(sector_versions["row_count"] or 0),
            "version_count": int(sector_versions["version_count"] or 0),
            "min_as_of_date": sector_versions["min_as_of"],
            "max_as_of_date": sector_versions["max_as_of"],
            "historical_version_ready": has_sector_versions,
        },
        "snapshots": snapshot_counts,
        "warnings": [
            *([] if coverage_ok else [f"当前日线跨度 {span_years} 年，不足 {required_years} 年。"]),
            *([] if has_sector_versions else ["板块成分缺少多历史版本，长周期回测存在成分未来函数风险。"]),
        ],
    }


def no_future_guard_payload() -> dict[str, Any]:
    payload = data_coverage_payload()
    warnings = list(payload.get("warnings", []))
    checks = [
        {
            "name": "日线评分日期",
            "status": "pass" if payload.get("coverage", {}).get("quote_count", 0) > 0 else "fail",
            "detail": "评分入口按交易日读取当日及以前日线；未来收益只在回测收益计算阶段读取。",
        },
        {
            "name": "板块成分历史版本",
            "status": "pass" if payload.get("sector_constituents", {}).get("historical_version_ready") else "warning",
            "detail": "回测应使用当时可用的板块成分版本；当前库缺多版本时只能给出风险提示。",
        },
        {
            "name": "预计算快照",
            "status": "pass" if payload.get("snapshots", {}).get("ranking", 0) > 0 else "warning",
            "detail": "页面默认读快照，回测若要完全复现应继续扩展为逐日评分快照。",
        },
    ]
    return {
        "status": "pass" if all(item["status"] == "pass" for item in checks) else "warning",
        "checks": checks,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="检查本地数据覆盖和未来函数风险")
    parser.add_argument("--required-years", type=float, default=5.0)
    args = parser.parse_args()
    payload = data_coverage_payload(args.required_years)
    guard = no_future_guard_payload()
    print(payload)
    print(guard)


if __name__ == "__main__":
    main()
