from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from real_scoring import daily_report, ranking_payload


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"


def init_review_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists local_theme_score_daily (
          trade_date text not null,
          theme_id text not null,
          theme_name text not null,
          rank integer not null,
          theme_score real not null,
          heat_score real not null,
          continuation_score real not null,
          risk_penalty real not null,
          confidence text not null,
          status text not null,
          payload_json text not null,
          saved_at text not null,
          primary key (trade_date, theme_id)
        );

        create table if not exists local_confidence_daily (
          trade_date text primary key,
          confidence text not null,
          confidence_score real not null,
          reason text not null,
          component_json text not null,
          saved_at text not null
        );

        create table if not exists local_risk_signal_daily (
          trade_date text not null,
          theme_id text not null,
          risk_type text not null,
          penalty real not null,
          severity text not null,
          reason text not null,
          saved_at text not null
        );

        create index if not exists idx_local_risk_signal_date
          on local_risk_signal_daily(trade_date);

        create table if not exists local_daily_report (
          trade_date text primary key,
          report text not null,
          payload_json text not null,
          saved_at text not null
        );
        """
    )


def save_daily_review(date: str) -> dict[str, Any]:
    ranking = ranking_payload(date)
    report = daily_report(date)
    trade_date = ranking["date"]
    saved_at = datetime.now().isoformat(timespec="seconds")

    with sqlite3.connect(DB_PATH) as conn:
        init_review_schema(conn)
        conn.execute("delete from local_risk_signal_daily where trade_date = ?", (trade_date,))
        for item in ranking["items"]:
            conn.execute(
                """
                insert into local_theme_score_daily(
                  trade_date, theme_id, theme_name, rank, theme_score, heat_score,
                  continuation_score, risk_penalty, confidence, status, payload_json, saved_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(trade_date, theme_id) do update set
                  theme_name = excluded.theme_name,
                  rank = excluded.rank,
                  theme_score = excluded.theme_score,
                  heat_score = excluded.heat_score,
                  continuation_score = excluded.continuation_score,
                  risk_penalty = excluded.risk_penalty,
                  confidence = excluded.confidence,
                  status = excluded.status,
                  payload_json = excluded.payload_json,
                  saved_at = excluded.saved_at
                """,
                (
                    trade_date,
                    item["theme_id"],
                    item["theme_name"],
                    item["rank"],
                    item["theme_score"],
                    item["heat_score"],
                    item["continuation_score"],
                    item["risk_penalty"],
                    item["confidence"],
                    item["status"],
                    json.dumps(item, ensure_ascii=False),
                    saved_at,
                ),
            )
            for risk in item.get("risks", []):
                conn.execute(
                    """
                    insert into local_risk_signal_daily(trade_date, theme_id, risk_type, penalty, severity, reason, saved_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (trade_date, item["theme_id"], risk["risk_type"], risk["penalty"], risk["severity"], risk["reason"], saved_at),
                )

        conn.execute(
            """
            insert into local_confidence_daily(trade_date, confidence, confidence_score, reason, component_json, saved_at)
            values (?, ?, ?, ?, ?, ?)
            on conflict(trade_date) do update set
              confidence = excluded.confidence,
              confidence_score = excluded.confidence_score,
              reason = excluded.reason,
              component_json = excluded.component_json,
              saved_at = excluded.saved_at
            """,
            (
                trade_date,
                ranking["confidence"],
                ranking["confidence_score"],
                ranking["reason"],
                json.dumps(ranking["components"], ensure_ascii=False),
                saved_at,
            ),
        )
        conn.execute(
            """
            insert into local_daily_report(trade_date, report, payload_json, saved_at)
            values (?, ?, ?, ?)
            on conflict(trade_date) do update set
              report = excluded.report,
              payload_json = excluded.payload_json,
              saved_at = excluded.saved_at
            """,
            (trade_date, report["report"], json.dumps(report, ensure_ascii=False), saved_at),
        )
        conn.commit()

    return {
        "trade_date": trade_date,
        "theme_count": len(ranking["items"]),
        "risk_count": sum(len(item.get("risks", [])) for item in ranking["items"]),
        "confidence": ranking["confidence"],
        "confidence_score": ranking["confidence_score"],
        "saved_at": saved_at,
    }


def latest_saved_review() -> dict[str, Any] | None:
    if not DB_PATH.exists():
        return None
    with sqlite3.connect(DB_PATH) as conn:
        init_review_schema(conn)
        row = conn.execute(
            """
            select trade_date, confidence, confidence_score, saved_at
            from local_confidence_daily
            order by trade_date desc
            limit 1
            """
        ).fetchone()
    if not row:
        return None
    return {
        "trade_date": row[0],
        "confidence": row[1],
        "confidence_score": row[2],
        "saved_at": row[3],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="保存某日主线复盘结果到本地 SQLite。")
    parser.add_argument("--date", default="2026-04-29", help="交易日，格式 YYYY-MM-DD")
    args = parser.parse_args()
    result = save_daily_review(args.date)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

