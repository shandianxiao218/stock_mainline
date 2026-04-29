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

from scoring import backtest_result, daily_report, detail_payload, find_theme, portfolio_risk, ranking_payload
from eastmoney_data import eastmoney_status


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
            theme = find_theme(theme_id)
            return self.send_json({"date": date, "theme_id": theme_id, "items": theme["risks"]}) if theme else self.send_error_json(404, "Theme not found")

        if path.startswith("/api/v1/themes/") and path.endswith("/factor-contribution"):
            theme_id = unquote(path.split("/")[4])
            theme = find_theme(theme_id)
            if not theme:
                return self.send_error_json(404, "Theme not found")
            return self.send_json({"date": date, "theme_id": theme_id, "factor_contribution": theme["factor_contribution"]})

        if path == "/api/v1/reports/daily":
            return self.send_json(daily_report(date))

        if path == "/api/v1/portfolio/risk":
            return self.send_json(portfolio_risk(date))

        if path == "/api/v1/data/eastmoney/status":
            return self.send_json(eastmoney_status())

        if path == "/api/v1/export/themes.xlsx":
            return self.send_excel(date)

        return self.send_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/backtest/run":
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                return self.send_error_json(400, "Invalid JSON body")
            return self.send_json(backtest_result(body))
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
