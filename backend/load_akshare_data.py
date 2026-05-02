"""AKShare 数据拉取和入库脚本。

从 AKShare 拉取龙虎榜详情和东财热度排行，存入本地 SQLite。
龙虎榜表: ak_dragon_tiger_daily
热度表:   ak_hot_rank_daily

用法:
  python backend/load_akshare_data.py --type lhb --start-date 20260420 --end-date 20260430
  python backend/load_akshare_data.py --type hot
  python backend/load_akshare_data.py --type all --start-date 20260420 --end-date 20260430
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"
BATCH_SIZE = 2000


def _require_akshare():
    try:
        import akshare as ak  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("未安装 akshare，无法同步 AKShare 数据；本地已入库数据仍可正常读取") from exc
    return ak


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists ak_dragon_tiger_daily (
            trade_date text not null,
            symbol text not null,
            stock_name text,
            close_price real,
            pct_change real,
            net_buy_amount real,
            buy_amount real,
            sell_amount real,
            total_amount real,
            market_total_amount real,
            net_buy_ratio real,
            turnover_ratio real,
            float_cap real,
            reason text,
            saved_at text not null,
            primary key (trade_date, symbol)
        );

        create index if not exists idx_ak_lhb_date on ak_dragon_tiger_daily(trade_date);
        create index if not exists idx_ak_lhb_symbol on ak_dragon_tiger_daily(symbol);

        create table if not exists ak_hot_rank_daily (
            trade_date text not null,
            symbol text not null,
            stock_name text,
            hot_rank integer,
            current_price real,
            pct_change real,
            saved_at text not null,
            primary key (trade_date, symbol)
        );

        create index if not exists idx_ak_hot_date on ak_hot_rank_daily(trade_date);
        create index if not exists idx_ak_hot_symbol on ak_hot_rank_daily(symbol);

        create table if not exists ak_import_batch (
            id integer primary key autoincrement,
            source text not null,
            start_date text,
            end_date text,
            record_count integer not null,
            imported_at text not null
        );
        """
    )
    conn.commit()


def _normalize_symbol(raw: str) -> str:
    """将 AKShare 返回的纯数字代码转为 SH/SZ 前缀格式。"""
    code = str(raw).strip()
    if code.startswith(("SH", "SZ")):
        return code
    if len(code) == 6:
        prefix = "SH" if code.startswith(("6", "5")) else "SZ"
        return f"{prefix}{code}"
    return code


def fetch_dragon_tiger(start_date: str, end_date: str) -> pd.DataFrame:
    """从 AKShare 拉取龙虎榜数据。

    start_date/end_date: YYYYMMDD 格式。
    """
    ak = _require_akshare()
    df = ak.stock_lhb_detail_em(start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        return pd.DataFrame()
    # 重命名中文列
    rename_map = {
        "代码": "symbol_raw",
        "名称": "stock_name",
        "上榜日": "trade_date",
        "收盘价": "close_price",
        "涨跌幅": "pct_change",
        "龙虎榜净买额": "net_buy_amount",
        "龙虎榜买入额": "buy_amount",
        "龙虎榜卖出额": "sell_amount",
        "龙虎榜成交额": "total_amount",
        "市场总成交额": "market_total_amount",
        "净买额占总成交比": "net_buy_ratio",
        "成交额占总成交比": "turnover_ratio",
        "换手率": "turnover",
        "流通市值": "float_cap",
        "上榜原因": "reason",
    }
    df = df.rename(columns=rename_map)
    df["symbol"] = df["symbol_raw"].apply(_normalize_symbol)
    df["trade_date"] = df["trade_date"].astype(str).str.replace("-", "")
    df["pct_change"] = pd.to_numeric(df.get("pct_change"), errors="coerce")
    # 保留需要的列
    keep = [
        "trade_date", "symbol", "stock_name", "close_price", "pct_change",
        "net_buy_amount", "buy_amount", "sell_amount", "total_amount",
        "market_total_amount", "net_buy_ratio", "turnover_ratio", "float_cap", "reason",
    ]
    keep = [c for c in keep if c in df.columns]
    return df[keep]


def fetch_hot_rank() -> pd.DataFrame:
    """从 AKShare 拉取当日东财人气排行。"""
    ak = _require_akshare()
    df = ak.stock_hot_rank_em()
    if df is None or df.empty:
        return pd.DataFrame()
    rename_map = {
        "当前排名": "hot_rank",
        "代码": "symbol_raw",
        "股票简称": "stock_name",
        "最新价": "current_price",
        "涨跌幅": "pct_change",
    }
    df = df.rename(columns=rename_map)
    df["symbol"] = df["symbol_raw"].apply(_normalize_symbol)
    today = datetime.now().strftime("%Y%m%d")
    df["trade_date"] = today
    df["pct_change"] = pd.to_numeric(df.get("pct_change"), errors="coerce")
    keep = ["trade_date", "symbol", "stock_name", "hot_rank", "current_price", "pct_change"]
    keep = [c for c in keep if c in df.columns]
    return df[keep]


def save_dragon_tiger(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    """将龙虎榜数据 upsert 到 SQLite。返回插入/更新行数。"""
    if df is None or df.empty:
        return 0
    count = 0
    rows: list[tuple[Any, ...]] = []
    now = _now()
    for _, row in df.iterrows():
        rows.append((
            str(row.get("trade_date", "")),
            str(row.get("symbol", "")),
            str(row.get("stock_name", "")),
            float(row.get("close_price", 0) or 0),
            float(row.get("pct_change", 0) or 0),
            float(row.get("net_buy_amount", 0) or 0),
            float(row.get("buy_amount", 0) or 0),
            float(row.get("sell_amount", 0) or 0),
            float(row.get("total_amount", 0) or 0),
            float(row.get("market_total_amount", 0) or 0),
            float(row.get("net_buy_ratio", 0) or 0),
            float(row.get("turnover_ratio", 0) or 0),
            float(row.get("float_cap", 0) or 0),
            str(row.get("reason", "")),
            now,
        ))
        if len(rows) >= BATCH_SIZE:
            _upsert_lhb(conn, rows)
            count += len(rows)
            rows.clear()
    if rows:
        _upsert_lhb(conn, rows)
        count += len(rows)
    conn.commit()
    return count


def _upsert_lhb(conn: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> None:
    conn.executemany(
        """
        insert or replace into ak_dragon_tiger_daily
        (trade_date, symbol, stock_name, close_price, pct_change,
         net_buy_amount, buy_amount, sell_amount, total_amount,
         market_total_amount, net_buy_ratio, turnover_ratio,
         float_cap, reason, saved_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def save_hot_rank(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    """将热度排行数据 upsert 到 SQLite。"""
    if df is None or df.empty:
        return 0
    now = _now()
    rows = [
        (
            str(row.get("trade_date", "")),
            str(row.get("symbol", "")),
            str(row.get("stock_name", "")),
            int(row.get("hot_rank", 0) or 0),
            float(row.get("current_price", 0) or 0),
            float(row.get("pct_change", 0) or 0),
            now,
        )
        for _, row in df.iterrows()
    ]
    conn.executemany(
        """
        insert or replace into ak_hot_rank_daily
        (trade_date, symbol, stock_name, hot_rank, current_price, pct_change, saved_at)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def akshare_status(conn: sqlite3.Connection) -> dict[str, Any]:
    """返回 AKShare 数据覆盖状态。"""
    lhb_count = conn.execute("select count(*) from ak_dragon_tiger_daily").fetchone()[0]
    lhb_dates = conn.execute(
        "select min(trade_date), max(trade_date) from ak_dragon_tiger_daily"
    ).fetchone()
    hot_count = conn.execute("select count(*) from ak_hot_rank_daily").fetchone()[0]
    hot_dates = conn.execute(
        "select min(trade_date), max(trade_date) from ak_hot_rank_daily"
    ).fetchone()
    return {
        "dragon_tiger": {
            "total_records": lhb_count,
            "date_range": [lhb_dates[0], lhb_dates[1]] if lhb_count else [],
        },
        "hot_rank": {
            "total_records": hot_count,
            "date_range": [hot_dates[0], hot_dates[1]] if hot_count else [],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="从 AKShare 拉取龙虎榜和热度数据")
    parser.add_argument("--type", default="all", choices=["lhb", "hot", "all"], help="数据类型")
    parser.add_argument("--start-date", default="", help="龙虎榜起始日期 YYYYMMDD")
    parser.add_argument("--end-date", default="", help="龙虎榜结束日期 YYYYMMDD")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite 路径")
    args = parser.parse_args()

    with sqlite3.connect(args.db) as conn:
        init_schema(conn)

        if args.type in ("lhb", "all"):
            start = args.start_date or datetime.now().strftime("%Y%m%d")
            end = args.end_date or start
            print(f"拉取龙虎榜 {start} ~ {end} ...")
            try:
                df = fetch_dragon_tiger(start, end)
                count = save_dragon_tiger(conn, df)
                print(f"龙虎榜: {count} 条已入库")
                conn.execute(
                    "insert into ak_import_batch(source, start_date, end_date, record_count, imported_at) values (?, ?, ?, ?, ?)",
                    ("lhb", start, end, count, _now()),
                )
                conn.commit()
            except Exception as exc:
                print(f"龙虎榜拉取失败: {exc}")

        if args.type in ("hot", "all"):
            print("拉取东财热度排行 ...")
            try:
                df = fetch_hot_rank()
                count = save_hot_rank(conn, df)
                print(f"热度排行: {count} 条已入库")
                conn.execute(
                    "insert into ak_import_batch(source, start_date, end_date, record_count, imported_at) values (?, ?, ?, ?, ?)",
                    ("hot", datetime.now().strftime("%Y%m%d"), datetime.now().strftime("%Y%m%d"), count, _now()),
                )
                conn.commit()
            except Exception as exc:
                print(f"热度拉取失败: {exc}")

        status = akshare_status(conn)
        print(f"\n数据状态: {status}")


if __name__ == "__main__":
    main()
