from __future__ import annotations

import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
sys.path.insert(0, str(CURRENT_DIR))

from eastmoney_data import eastmoney_status
from data_quality import data_quality_payload
from model_config_store import get_active_config, list_configs, save_config
from review_store import save_daily_review
from watchlist_store import add_position, add_watchlist, delete_position, delete_watchlist, list_positions, list_watchlist
from theme_universe import PORTFOLIO

try:
    from real_scoring import (
        backtest_result,
        daily_report,
        db_ready,
        detail_payload,
        find_theme,
        kline_payload,
        portfolio_risk,
        ranking_payload,
        theme_matrix_payload,
    )
    if not db_ready():
        raise ImportError("本地 SQLite 数据库不存在")
except ImportError:
    from scoring import backtest_result, daily_report, detail_payload, find_theme, portfolio_risk, ranking_payload

    def theme_matrix_payload(date: str, days: int = 20) -> dict[str, object]:
        return {"date": date, "dates": [], "items": []}

    def kline_payload(symbol: str, date: str, window: int = 80) -> dict[str, object]:
        return {"symbol": symbol, "bars": []}


class RadarHandler(BaseHTTPRequestHandler):
    server_version = "AStockThemeRadar/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        date = query.get("date", ["2026-04-29"])[0]

        if path == "/api/v1/themes/ranking":
            return self.send_json(ranking_payload(date, query.get("period", ["short"])[0]))

        if path.startswith("/api/v1/themes/") and path.endswith("/detail"):
            theme_id = unquote(path.split("/")[4])
            data = detail_payload(theme_id, date)
            return self.send_json(data) if data else self.send_error_json(404, "Theme not found")

        if path.startswith("/api/v1/themes/") and path.endswith("/risks"):
            theme_id = unquote(path.split("/")[4])
            theme = find_theme(theme_id, date)
            return self.send_json({"date": date, "theme_id": theme_id, "items": theme["risks"]}) if theme else self.send_error_json(404, "Theme not found")

        if path.startswith("/api/v1/themes/") and path.endswith("/factor-contribution"):
            theme_id = unquote(path.split("/")[4])
            theme = find_theme(theme_id, date)
            if not theme:
                return self.send_error_json(404, "Theme not found")
            return self.send_json({"date": date, "theme_id": theme_id, "factor_contribution": theme["factor_contribution"]})

        if path == "/api/v1/reports/daily":
            return self.send_json(daily_report(date))

        if path == "/api/v1/portfolio/risk":
            return self.send_json(portfolio_risk(date))

        if path == "/api/v1/data/eastmoney/status":
            return self.send_json(eastmoney_status())

        if path == "/api/v1/data/quality":
            return self.send_json(data_quality_payload())

        if path == "/api/v1/model/config":
            return self.send_json({"active": get_active_config(), "items": list_configs()})

        if path == "/api/v1/themes/matrix":
            days = int(query.get("days", ["20"])[0])
            return self.send_json(theme_matrix_payload(date, days))

        if path.startswith("/api/v1/stocks/") and path.endswith("/kline"):
            symbol = unquote(path.split("/")[4])
            window = int(query.get("window", ["80"])[0])
            return self.send_json(kline_payload(symbol, date, window))

        if path == "/api/v1/watchlist":
            return self.send_json({"items": list_watchlist()})

        if path == "/api/v1/positions":
            return self.send_json({"items": list_positions(PORTFOLIO)})

        if path in ("/api/v1/export/themes.xlsx", "/api/v1/export/full.xlsx"):
            return self.send_excel_full(date)

        return self.send_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        date = query.get("date", ["2026-04-29"])[0]
        if parsed.path == "/api/v1/backtest/run":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                return self.send_error_json(400, "Invalid JSON body")
            return self.send_json(backtest_result(body))
        if parsed.path == "/api/v1/reviews/save":
            return self.send_json(save_daily_review(date))
        if parsed.path == "/api/v1/watchlist":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
                return self.send_json(add_watchlist(str(body.get("symbol", "")), body.get("name"), body.get("tag")))
            except (json.JSONDecodeError, ValueError) as exc:
                return self.send_error_json(400, str(exc))
        if parsed.path == "/api/v1/positions":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
                return self.send_json(
                    add_position(
                        str(body.get("symbol", "")),
                        body.get("name"),
                        float(body.get("quantity", 0)),
                        float(body["cost_price"]) if body.get("cost_price") not in (None, "") else None,
                        body.get("tag"),
                    )
                )
            except (json.JSONDecodeError, ValueError) as exc:
                return self.send_error_json(400, str(exc))
        if parsed.path == "/api/v1/model/config":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
                return self.send_json(save_config(body))
            except (json.JSONDecodeError, ValueError) as exc:
                return self.send_error_json(400, str(exc))
        return self.send_error_json(404, "Not found")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/watchlist/"):
            symbol = unquote(parsed.path.split("/")[4])
            return self.send_json(delete_watchlist(symbol))
        if parsed.path.startswith("/api/v1/positions/"):
            symbol = unquote(parsed.path.split("/")[4])
            return self.send_json(delete_position(symbol))
        return self.send_error_json(404, "Not found")

    def send_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        target = (FRONTEND_DIR / path.lstrip("/")).resolve()
        if not str(target).startswith(str(FRONTEND_DIR.resolve())) or not target.exists() or target.is_dir():
            return self.send_error_json(404, "Not found")
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, data: object, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json({"error": message, "status": status}, status)

    def send_excel(self, date: str) -> None:
        self.send_excel_full(date)

    def send_excel_full(self, date: str) -> None:
        ranking = ranking_payload(date)
        rows = []
        risk_rows = []
        for item in ranking["items"]:
            rows.append({
                "排名": item["rank"],
                "主线": item["theme_name"],
                "主线分": item["theme_score"],
                "热度分": item["heat_score"],
                "延续性分": item["continuation_score"],
                "风险扣分": item["risk_penalty"],
                "状态": item["status"],
                "强分支": "、".join(item["branches"]),
                "核心股": "、".join(item["core_stocks"]),
            })
            for risk in item["risks"]:
                risk_rows.append({
                    "主线": item["theme_name"],
                    "风险项": risk["risk_type"],
                    "扣分": risk["penalty"],
                    "级别": risk["severity"],
                    "原因": risk["reason"],
                })

        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="主线榜单")
            pd.DataFrame(risk_rows).to_excel(writer, index=False, sheet_name="风险明细")
            pd.DataFrame([ranking["components"]]).to_excel(writer, index=False, sheet_name="置信度")
            report = daily_report(date)
            pd.DataFrame([{"日期": report["date"], "复盘": report["report"]}]).to_excel(writer, index=False, sheet_name="复盘报告")
            matrix = theme_matrix_payload(date, 20)
            matrix_rows = []
            for item in matrix["items"]:
                row = {"主线": item["theme_name"]}
                for day in matrix["dates"]:
                    cell = item["cells"].get(day)
                    row[day] = cell["theme_score"] if cell else None
                matrix_rows.append(row)
            pd.DataFrame(matrix_rows).to_excel(writer, index=False, sheet_name="20日矩阵")
            component_rows = []
            for item in ranking["items"]:
                detail = detail_payload(item["theme_id"], date)
                if not detail:
                    continue
                for stock in detail.get("stock_metrics", []):
                    component_rows.append({
                        "主线": item["theme_name"],
                        "名称": stock["name"],
                        "代码": stock["symbol"],
                        "开": stock.get("open"),
                        "收": stock.get("close"),
                        "高": stock.get("high"),
                        "低": stock.get("low"),
                        "涨幅": stock.get("pct1"),
                        "近5日涨幅": stock.get("pct5"),
                        "成交量": stock.get("volume"),
                        "成交额": stock.get("amount"),
                        "是否炸板": "是" if stock.get("limit_break") else "否",
                        "游资参与": stock.get("hot_money", "未接入"),
                    })
            pd.DataFrame(component_rows).to_excel(writer, index=False, sheet_name="成分股明细")
        content = output.getvalue()

        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f'attachment; filename="theme_ranking_{date}.xlsx"')
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[server] {self.address_string()} - {format % args}")


def main() -> None:
    host = "127.0.0.1"
    port = 8000
    httpd = ThreadingHTTPServer((host, port), RadarHandler)
    print(f"A股板块主线雷达 demo running at http://{host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
