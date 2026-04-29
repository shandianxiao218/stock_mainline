from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from eastmoney_data import eastmoney_status
from real_scoring import DB_PATH


def data_quality_payload() -> dict[str, Any]:
    status = eastmoney_status()
    checks = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "ok" if ok else "warn", "detail": detail})

    source_files = status["source_files"]
    add_check("上海日线源文件", source_files["sh_day"]["exists"], source_files["sh_day"]["path"])
    add_check("深圳日线源文件", source_files["sz_day"]["exists"], source_files["sz_day"]["path"])

    generated = status["generated_files"]
    add_check("股票 CSV", generated["stocks_csv"]["exists"] and generated["stocks_csv"]["rows"] > 0, f"{generated['stocks_csv']['rows']} 行")
    add_check("日线 CSV", generated["daily_quotes_csv"]["exists"] and generated["daily_quotes_csv"]["rows"] > 0, f"{generated['daily_quotes_csv']['rows']} 行")

    database = status.get("database") or {}
    add_check("SQLite 数据库", database.get("exists", False), database.get("path", "不存在"))
    add_check("股票入库", (database.get("stock_count") or 0) > 0, f"{database.get('stock_count') or 0} 条")
    add_check("日线入库", (database.get("quote_count") or 0) > 0, f"{database.get('quote_count') or 0} 条")

    sector_snapshot = status.get("sector_snapshot") or {}
    add_check("板块快照", sector_snapshot.get("exists", False), f"{sector_snapshot.get('row_count') or 0} 行")

    limit_signal = status.get("limit_signal") or {}
    add_check("涨停信号", limit_signal.get("exists", False), f"{limit_signal.get('row_count') or 0} 行")

    latest_review = status.get("latest_saved_review")
    add_check("最近复盘保存", latest_review is not None, latest_review.get("trade_date") if latest_review else "暂无")

    date_health = {}
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as conn:
            quote_dates = conn.execute(
                "select count(distinct trade_date), min(trade_date), max(trade_date) from em_daily_quote"
            ).fetchone()
            import_rows = conn.execute(
                "select imported_at, stock_count, quote_count from import_batch order by id desc limit 5"
            ).fetchall()
            date_health = {
                "trade_day_count": quote_dates[0],
                "min_trade_date": quote_dates[1],
                "max_trade_date": quote_dates[2],
                "recent_import_batches": [
                    {"imported_at": row[0], "stock_count": row[1], "quote_count": row[2]}
                    for row in import_rows
                ],
            }

    warn_count = sum(1 for check in checks if check["status"] != "ok")
    return {
        "status": "ok" if warn_count == 0 else "warn",
        "warn_count": warn_count,
        "checks": checks,
        "date_health": date_health,
        "source_status": status,
    }

