from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

try:
    from review_store import latest_saved_review
except ImportError:
    latest_saved_review = None

try:
    from build_sector_snapshots import snapshot_status
except ImportError:
    snapshot_status = None


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_EASTMONEY_ROOT = Path("C:/eastmoney")
DEFAULT_OUTPUT_DIR = ROOT_DIR / "backend" / "data" / "eastmoney"
DEFAULT_DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        return sum(1 for _ in reader)


def database_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    try:
        with sqlite3.connect(path) as conn:
            stock_count = conn.execute("select count(*) from em_stock").fetchone()[0]
            quote_count = conn.execute("select count(*) from em_daily_quote").fetchone()[0]
            date_range = conn.execute("select min(trade_date), max(trade_date) from em_daily_quote").fetchone()
            latest_batch = conn.execute(
                """
                select imported_at, stock_count, quote_count
                from import_batch
                order by id desc
                limit 1
                """
            ).fetchone()
        return {
            "path": str(path),
            "exists": True,
            "stock_count": stock_count,
            "quote_count": quote_count,
            "min_trade_date": date_range[0],
            "max_trade_date": date_range[1],
            "latest_batch": {
                "imported_at": latest_batch[0],
                "stock_count": latest_batch[1],
                "quote_count": latest_batch[2],
            } if latest_batch else None,
        }
    except sqlite3.Error as exc:
        return {"path": str(path), "exists": True, "error": str(exc)}


def eastmoney_status() -> dict[str, Any]:
    sh_day = DEFAULT_EASTMONEY_ROOT / "swc8" / "data" / "SHANGHAI" / "DayData_SH_V43.dat"
    sz_day = DEFAULT_EASTMONEY_ROOT / "swc8" / "data" / "SHENZHEN" / "DayData_SZ_V43.dat"
    stocks_csv = DEFAULT_OUTPUT_DIR / "stocks.csv"
    quotes_csv = DEFAULT_OUTPUT_DIR / "daily_quotes.csv"
    progress_json = DEFAULT_OUTPUT_DIR / "eastmoney_import.progress.json"

    return {
        "provider": "东方财富本地客户端",
        "eastmoney_root": str(DEFAULT_EASTMONEY_ROOT),
        "binary_reader": "tools/eastmoney_import.c",
        "python_reads_binary": False,
        "source_files": {
            "sh_day": {"path": str(sh_day), "exists": sh_day.exists()},
            "sz_day": {"path": str(sz_day), "exists": sz_day.exists()},
        },
        "generated_files": {
            "stocks_csv": {"path": str(stocks_csv), "exists": stocks_csv.exists(), "rows": count_csv_rows(stocks_csv)},
            "daily_quotes_csv": {"path": str(quotes_csv), "exists": quotes_csv.exists(), "rows": count_csv_rows(quotes_csv)},
            "progress_json": {"path": str(progress_json), "exists": progress_json.exists()},
        },
        "database": database_status(DEFAULT_DB_PATH),
        "latest_saved_review": latest_saved_review() if latest_saved_review else None,
        "sector_snapshot": snapshot_status() if snapshot_status else None,
        "import_command": "tools\\eastmoney_import.exe C:\\eastmoney backend\\data\\eastmoney 20200101",
        "load_command": "python backend\\load_eastmoney_csv.py",
        "snapshot_command": "python backend\\build_sector_snapshots.py --end-date 2026-04-29 --days 260",
        "build_command": (
            "clang --target=x86_64-w64-windows-gnu --sysroot=C:\\ProgramData\\mingw64\\mingw64 "
            "-O2 -std=c11 -Wall -Wextra -o tools\\eastmoney_import.exe tools\\eastmoney_import.c"
        ),
    }
