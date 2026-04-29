from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_EASTMONEY_ROOT = Path("C:/eastmoney")
DEFAULT_OUTPUT_DIR = ROOT_DIR / "backend" / "data" / "eastmoney"


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        return sum(1 for _ in reader)


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
        "import_command": "tools\\eastmoney_import.exe C:\\eastmoney backend\\data\\eastmoney 20200101",
        "build_command": (
            "clang --target=x86_64-w64-windows-gnu --sysroot=C:\\ProgramData\\mingw64\\mingw64 "
            "-O2 -std=c11 -Wall -Wextra -o tools\\eastmoney_import.exe tools\\eastmoney_import.c"
        ),
    }

