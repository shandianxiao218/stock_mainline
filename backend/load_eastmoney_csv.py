from __future__ import annotations

import argparse
import csv
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = ROOT_DIR / "backend" / "data" / "eastmoney"
DEFAULT_DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"
BATCH_SIZE = 5000


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        pragma journal_mode = wal;
        pragma synchronous = normal;

        create table if not exists import_batch (
          id integer primary key autoincrement,
          source text not null,
          input_dir text not null,
          imported_at text not null,
          stock_count integer not null,
          quote_count integer not null
        );

        create table if not exists em_stock (
          symbol text primary key,
          name text not null,
          market text not null,
          last_date integer,
          last_close real,
          last_volume integer,
          total_bars integer not null
        );

        create table if not exists em_daily_quote (
          symbol text not null,
          trade_date integer not null,
          open real not null,
          high real not null,
          low real not null,
          close real not null,
          volume integer not null,
          amount real not null,
          primary key (symbol, trade_date)
        );

        create index if not exists idx_em_daily_quote_date
          on em_daily_quote(trade_date);

        create index if not exists idx_em_daily_quote_symbol_date_desc
          on em_daily_quote(symbol, trade_date desc);
        """
    )


def reset_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        delete from em_daily_quote;
        delete from em_stock;
        """
    )


def load_stocks(conn: sqlite3.Connection, path: Path) -> int:
    count = 0
    rows: list[tuple[str, str, str, int | None, float | None, int | None, int]] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                (
                    row["symbol"],
                    row["name"],
                    row["market"],
                    int(row["last_date"]) if row["last_date"] else None,
                    float(row["last_close"]) if row["last_close"] else None,
                    int(row["last_volume"]) if row["last_volume"] else None,
                    int(row["total_bars"]) if row["total_bars"] else 0,
                )
            )
            if len(rows) >= BATCH_SIZE:
                count += insert_stocks(conn, rows)
                rows.clear()
    if rows:
        count += insert_stocks(conn, rows)
    return count


def insert_stocks(conn: sqlite3.Connection, rows: list[tuple[str, str, str, int | None, float | None, int | None, int]]) -> int:
    conn.executemany(
        """
        insert into em_stock(symbol, name, market, last_date, last_close, last_volume, total_bars)
        values (?, ?, ?, ?, ?, ?, ?)
        on conflict(symbol) do update set
          name = excluded.name,
          market = excluded.market,
          last_date = excluded.last_date,
          last_close = excluded.last_close,
          last_volume = excluded.last_volume,
          total_bars = excluded.total_bars
        """,
        rows,
    )
    return len(rows)


def load_quotes(conn: sqlite3.Connection, path: Path) -> int:
    count = 0
    rows: list[tuple[str, int, float, float, float, float, int, float]] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                (
                    row["symbol"],
                    int(row["date"]),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    int(row["volume"]),
                    float(row["amount"]),
                )
            )
            if len(rows) >= BATCH_SIZE:
                count += insert_quotes(conn, rows)
                rows.clear()
    if rows:
        count += insert_quotes(conn, rows)
    return count


def insert_quotes(conn: sqlite3.Connection, rows: list[tuple[str, int, float, float, float, float, int, float]]) -> int:
    conn.executemany(
        """
        insert into em_daily_quote(symbol, trade_date, open, high, low, close, volume, amount)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(symbol, trade_date) do update set
          open = excluded.open,
          high = excluded.high,
          low = excluded.low,
          close = excluded.close,
          volume = excluded.volume,
          amount = excluded.amount
        """,
        rows,
    )
    return len(rows)


def load_eastmoney_csv(input_dir: Path, db_path: Path) -> dict[str, int | str]:
    stocks_csv = input_dir / "stocks.csv"
    quotes_csv = input_dir / "daily_quotes.csv"
    if not stocks_csv.exists():
        raise FileNotFoundError(f"缺少股票文件：{stocks_csv}")
    if not quotes_csv.exists():
        raise FileNotFoundError(f"缺少日线文件：{quotes_csv}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        init_schema(conn)
        reset_tables(conn)
        stock_count = load_stocks(conn, stocks_csv)
        quote_count = load_quotes(conn, quotes_csv)
        conn.execute(
            """
            insert into import_batch(source, input_dir, imported_at, stock_count, quote_count)
            values (?, ?, ?, ?, ?)
            """,
            ("eastmoney_csv", str(input_dir), datetime.now().isoformat(timespec="seconds"), stock_count, quote_count),
        )
        conn.commit()
        conn.execute("vacuum")

    return {
        "db_path": str(db_path),
        "stock_count": stock_count,
        "quote_count": quote_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="将东方财富 C 导入器导出的 CSV 装载进本地 SQLite。")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR), help="包含 stocks.csv 与 daily_quotes.csv 的目录")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="输出 SQLite 数据库路径")
    args = parser.parse_args()

    result = load_eastmoney_csv(Path(args.input_dir), Path(args.db))
    print(f"导入完成：股票 {result['stock_count']} 条，日线 {result['quote_count']} 条，数据库 {result['db_path']}")


if __name__ == "__main__":
    main()

