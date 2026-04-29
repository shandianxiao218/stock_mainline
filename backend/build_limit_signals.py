from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from real_scoring import DB_PATH, date_text, limit_threshold, resolve_trade_date


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists local_limit_signal_daily (
          trade_date text not null,
          symbol text not null,
          pct_chg real not null,
          limit_threshold real not null,
          touched_limit integer not null,
          sealed_limit integer not null,
          limit_break integer not null,
          consecutive_boards integer not null,
          saved_at text not null,
          primary key (trade_date, symbol)
        );

        create index if not exists idx_local_limit_signal_date
          on local_limit_signal_daily(trade_date);
        """
    )


def build_limit_signals(end_date: str, days: int = 260) -> dict[str, Any]:
    saved_at = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        end = resolve_trade_date(conn, end_date)
        date_rows = conn.execute(
            """
            select distinct trade_date
            from em_daily_quote
            where trade_date <= ?
            order by trade_date desc
            limit ?
            """,
            (end, days),
        ).fetchall()
        dates = [row[0] for row in reversed(date_rows)]
        symbols = [row[0] for row in conn.execute("select symbol from em_stock where total_bars > 0 order by symbol")]
        board_streak: dict[str, int] = {symbol: 0 for symbol in symbols}
        rows_written = 0

        for trade_date in dates:
            rows = conn.execute(
                """
                select q.symbol, q.high, q.close, p.close
                from em_daily_quote q
                join em_daily_quote p on p.symbol = q.symbol
                where q.trade_date = ?
                  and p.trade_date = (
                    select max(trade_date) from em_daily_quote
                    where symbol = q.symbol and trade_date < ?
                  )
                  and q.close > 0 and p.close > 0
                """,
                (trade_date, trade_date),
            ).fetchall()
            payload = []
            for symbol, high, close, prev_close in rows:
                threshold = limit_threshold(symbol)
                pct = close / prev_close - 1
                high_pct = high / prev_close - 1
                touched = high_pct >= threshold
                sealed = pct >= threshold
                broken = touched and not sealed
                board_streak[symbol] = board_streak.get(symbol, 0) + 1 if sealed else 0
                payload.append(
                    (
                        date_text(trade_date),
                        symbol,
                        round(pct * 100, 4),
                        round(threshold * 100, 2),
                        int(touched),
                        int(sealed),
                        int(broken),
                        board_streak[symbol],
                        saved_at,
                    )
                )
            conn.executemany(
                """
                insert into local_limit_signal_daily(
                  trade_date, symbol, pct_chg, limit_threshold,
                  touched_limit, sealed_limit, limit_break, consecutive_boards, saved_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(trade_date, symbol) do update set
                  pct_chg = excluded.pct_chg,
                  limit_threshold = excluded.limit_threshold,
                  touched_limit = excluded.touched_limit,
                  sealed_limit = excluded.sealed_limit,
                  limit_break = excluded.limit_break,
                  consecutive_boards = excluded.consecutive_boards,
                  saved_at = excluded.saved_at
                """,
                payload,
            )
            rows_written += len(payload)
        conn.commit()
    return {
        "start_date": date_text(dates[0]) if dates else None,
        "end_date": date_text(dates[-1]) if dates else None,
        "trade_days": len(dates),
        "rows_written": rows_written,
        "saved_at": saved_at,
    }


def limit_signal_status() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"exists": False}
    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        row = conn.execute(
            """
            select count(*), min(trade_date), max(trade_date), max(saved_at),
                   sum(sealed_limit), sum(touched_limit), sum(limit_break), max(consecutive_boards)
            from local_limit_signal_daily
            """
        ).fetchone()
    return {
        "exists": bool(row and row[0]),
        "row_count": row[0] if row else 0,
        "min_trade_date": row[1] if row else None,
        "max_trade_date": row[2] if row else None,
        "saved_at": row[3] if row else None,
        "sealed_limit_count": row[4] if row else 0,
        "touched_limit_count": row[5] if row else 0,
        "limit_break_count": row[6] if row else 0,
        "max_consecutive_boards": row[7] if row else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="基于东方财富日线构建涨停/触板/炸板/连板信号。")
    parser.add_argument("--end-date", default="2026-04-29", help="截止日期 YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=260, help="向前生成的交易日数量")
    args = parser.parse_args()
    print(json.dumps(build_limit_signals(args.end_date, args.days), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

