from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from real_scoring import DB_PATH, build_market_snapshot, date_text, resolve_trade_date, score_sector_from_db
from theme_universe import THEME_SECTORS


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists local_sector_snapshot_daily (
          trade_date text not null,
          sector_id text not null,
          sector_name text not null,
          branch text not null,
          category text not null,
          stock_count integer not null,
          avg_pct real not null,
          median_pct real not null,
          avg_pct3 real not null,
          avg_pct5 real not null,
          up_ratio real not null,
          amount real not null,
          amount_ratio real not null,
          limit_count integer not null,
          touched_limit_count integer not null,
          limit_break_count integer not null,
          heat_score real not null,
          continuation_score real not null,
          risk_penalty real not null,
          composite_score real not null,
          stats_json text not null,
          saved_at text not null,
          primary key (trade_date, sector_id)
        );

        create index if not exists idx_local_sector_snapshot_date
          on local_sector_snapshot_daily(trade_date);
        """
    )


def available_dates(conn: sqlite3.Connection, end_date: str, days: int) -> list[int]:
    end = resolve_trade_date(conn, end_date)
    rows = conn.execute(
        """
        select distinct trade_date
        from em_daily_quote
        where trade_date <= ?
        order by trade_date desc
        limit ?
        """,
        (end, days),
    ).fetchall()
    return [row[0] for row in reversed(rows)]


def build_snapshots(end_date: str, days: int = 260) -> dict[str, Any]:
    saved_at = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        dates = available_dates(conn, end_date, days)
        rows_written = 0
        for trade_date in dates:
            market = build_market_snapshot(conn, trade_date)
            for sector in THEME_SECTORS:
                scored = score_sector_from_db(conn, sector, trade_date, market["market_amount"])
                stats = scored.raw.get("stats", {})
                stock_metrics = scored.raw.get("stock_metrics", [])
                touched_count = sum(1 for stock in stock_metrics if stock.get("limit_up") or stock.get("limit_break"))
                break_count = sum(1 for stock in stock_metrics if stock.get("limit_break"))
                conn.execute(
                    """
                    insert into local_sector_snapshot_daily(
                      trade_date, sector_id, sector_name, branch, category, stock_count,
                      avg_pct, median_pct, avg_pct3, avg_pct5, up_ratio,
                      amount, amount_ratio, limit_count, touched_limit_count, limit_break_count,
                      heat_score, continuation_score, risk_penalty, composite_score,
                      stats_json, saved_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(trade_date, sector_id) do update set
                      sector_name = excluded.sector_name,
                      branch = excluded.branch,
                      category = excluded.category,
                      stock_count = excluded.stock_count,
                      avg_pct = excluded.avg_pct,
                      median_pct = excluded.median_pct,
                      avg_pct3 = excluded.avg_pct3,
                      avg_pct5 = excluded.avg_pct5,
                      up_ratio = excluded.up_ratio,
                      amount = excluded.amount,
                      amount_ratio = excluded.amount_ratio,
                      limit_count = excluded.limit_count,
                      touched_limit_count = excluded.touched_limit_count,
                      limit_break_count = excluded.limit_break_count,
                      heat_score = excluded.heat_score,
                      continuation_score = excluded.continuation_score,
                      risk_penalty = excluded.risk_penalty,
                      composite_score = excluded.composite_score,
                      stats_json = excluded.stats_json,
                      saved_at = excluded.saved_at
                    """,
                    (
                        date_text(trade_date),
                        scored.raw["sector_id"],
                        scored.raw["sector_name"],
                        scored.raw["branch"],
                        scored.raw["category"],
                        stats.get("stock_count", 0),
                        stats.get("avg_pct", 0),
                        stats.get("median_pct", 0),
                        stats.get("avg_pct3", 0),
                        stats.get("avg_pct5", 0),
                        stats.get("up_ratio", 0),
                        stats.get("amount", 0),
                        stats.get("amount_ratio", 0),
                        stats.get("limit_count", 0),
                        touched_count,
                        break_count,
                        scored.heat_score,
                        scored.continuation_score,
                        scored.risk_penalty,
                        scored.composite_score,
                        json.dumps({"stats": stats, "stock_metrics": stock_metrics}, ensure_ascii=False),
                        saved_at,
                    ),
                )
                rows_written += 1
        conn.commit()
    return {
        "start_date": date_text(dates[0]) if dates else None,
        "end_date": date_text(dates[-1]) if dates else None,
        "trade_days": len(dates),
        "sector_count": len(THEME_SECTORS),
        "rows_written": rows_written,
        "saved_at": saved_at,
    }


def snapshot_status() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"exists": False}
    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        row = conn.execute(
            """
            select count(*), min(trade_date), max(trade_date), max(saved_at)
            from local_sector_snapshot_daily
            """
        ).fetchone()
    return {
        "exists": bool(row and row[0]),
        "row_count": row[0] if row else 0,
        "min_trade_date": row[1] if row else None,
        "max_trade_date": row[2] if row else None,
        "saved_at": row[3] if row else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="构建本地主线/板块日度行情快照。")
    parser.add_argument("--end-date", default="2026-04-29", help="截止日期 YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=260, help="向前生成的交易日数量")
    args = parser.parse_args()
    print(json.dumps(build_snapshots(args.end_date, args.days), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

