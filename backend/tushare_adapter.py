from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class TushareAdapter:
    token: str | None = None

    def __post_init__(self) -> None:
        self.token = self.token or os.getenv("TUSHARE_TOKEN")

    def is_configured(self) -> bool:
        return bool(self.token)

    def fetch_daily_snapshot(self, trade_date: str) -> dict[str, Any]:
        """Future Tushare integration entry point.

        The runnable demo intentionally avoids importing `tushare` so startup does not fail
        on machines without the package or token. Real implementation should normalize
        Tushare frames into the sector snapshot shape consumed by `scoring.py`.
        """
        if not self.is_configured():
            return {
                "configured": False,
                "trade_date": trade_date,
                "message": "Set TUSHARE_TOKEN and install tushare to enable live data collection.",
            }
        return {
            "configured": True,
            "trade_date": trade_date,
            "message": "Tushare adapter placeholder is ready for collector implementation.",
        }

