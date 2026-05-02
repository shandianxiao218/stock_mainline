from __future__ import annotations

import json
import mimetypes
import sys
import threading
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
from audit_store import list_audit_logs, write_audit
from backtest_store import (
    create_backtest_run,
    fail_backtest_run,
    finish_backtest_run,
    get_backtest_run,
    list_backtest_runs,
)
from catalyst_store import add_catalyst, list_catalysts
from cluster_store import load_clusters, list_cluster_dates
from load_akshare_data import akshare_status, fetch_dragon_tiger, fetch_hot_rank, save_dragon_tiger, save_hot_rank, init_schema as init_akshare_schema
from data_quality import data_quality_payload
from data_validation import data_coverage_payload, no_future_guard_payload
from model_config_store import get_active_config, list_configs, save_config
from permissions import has_permission, roles_payload
from theme_stage_store import load_stage_history
from review_store import save_daily_review
from sector_store import list_sectors, sector_constituents, sector_constituent_dates, sector_diff
from alert_store import compute_alerts
from snapshot_store import (
    init_snapshot_schema,
    attach_live_meta,
    load_confidence_history_snapshot,
    load_detail_snapshot,
    load_factor_effectiveness_snapshot,
    load_matrix_snapshot,
    load_ranking_snapshot,
    load_risk_history_snapshot,
    snapshot_status,
)
from theme_store import (
    archive_theme,
    delete_custom_sector,
    get_theme,
    list_custom_sectors,
    list_themes,
    merge_themes,
    save_custom_sector,
    save_theme,
    theme_history,
)
from watchlist_store import add_position, add_watchlist, delete_position, delete_watchlist, list_positions, list_watchlist
from theme_universe import PORTFOLIO

try:
    from real_scoring import (
        backtest_result,
        clear_scoring_cache,
        confidence_history_payload,
        daily_report,
        db_ready,
        detail_payload,
        factor_effectiveness_payload,
        find_theme,
        kline_payload,
        portfolio_risk,
        ranking_payload,
        risk_history_payload,
        theme_matrix_payload,
    )
    if not db_ready():
        raise ImportError("本地 SQLite 数据库不存在")
except ImportError:
    from scoring import backtest_result, daily_report, detail_payload, find_theme, portfolio_risk, ranking_payload as sample_ranking_payload

    def clear_scoring_cache() -> None:
        return None

    def ranking_payload(date: str, period: str = "short", limit: int | None = None) -> dict[str, object]:
        payload = sample_ranking_payload(date, period)
        items = payload.get("items", [])
        payload["total_count"] = len(items)
        payload["row_limit"] = "all" if limit is None else limit
        if limit is not None:
            payload["items"] = items[: max(1, min(int(limit), 500))]
        return payload

    def theme_matrix_payload(date: str, days: int = 20, limit: int | None = 10) -> dict[str, object]:
        return {"date": date, "dates": [], "items": []}

    def kline_payload(symbol: str, date: str, window: int = 80) -> dict[str, object]:
        return {"symbol": symbol, "bars": []}

    def factor_effectiveness_payload(date: str, holding_period: int = 3) -> dict[str, object]:
        return {"date": date, "holding_period": holding_period, "status": "unavailable", "items": []}

    def confidence_history_payload(date: str, days: int = 20) -> dict[str, object]:
        return {"date": date, "days": 0, "items": []}

    def risk_history_payload(theme_id: str, date: str, days: int = 20) -> dict[str, object]:
        return {"date": date, "theme_id": theme_id, "days": 0, "items": []}


def run_backtest_task(task_id: str, body: dict[str, object], max_retries: int = 2) -> None:
    """异步执行回测任务，失败时最多重试 max_retries 次。"""
    import time as _time
    last_error = ""
    for attempt in range(1 + max_retries):
        try:
            result = finish_backtest_run(task_id, backtest_result(body))
            write_audit("backtest_run", method="POST", path="/api/v1/backtest/run", target=task_id, detail=result.get("metrics", {}))
            return
        except Exception as exc:
            last_error = str(exc)
            if attempt < max_retries:
                _time.sleep(10)
    fail_backtest_run(task_id, last_error)
    write_audit("backtest_run_failed", method="POST", path="/api/v1/backtest/run", target=task_id, detail={"error": last_error})


class RadarHandler(BaseHTTPRequestHandler):
    server_version = "AStockThemeRadar/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        date = query.get("date", ["2026-04-29"])[0]
        use_snapshot = query.get("refresh", ["0"])[0] not in ("1", "true", "yes") and query.get("live", ["0"])[0] not in ("1", "true", "yes")
        self.audit_access("GET", path, query)

        if path == "/api/v1/themes/ranking":
            limit_arg = query.get("limit", ["10"])[0]
            limit = None if limit_arg == "all" else int(limit_arg)
            period = query.get("period", ["short"])[0]
            if use_snapshot:
                snapshot = load_ranking_snapshot(date, period, limit)
                if snapshot:
                    return self.send_json(snapshot)
            return self.send_json(attach_live_meta(ranking_payload(date, period, limit)))

        if path.startswith("/api/v1/themes/") and path.endswith("/detail"):
            theme_id = unquote(path.split("/")[4])
            if use_snapshot:
                snapshot = load_detail_snapshot(theme_id, date)
                if snapshot:
                    return self.send_json(snapshot)
            data = detail_payload(theme_id, date)
            return self.send_json(attach_live_meta(data)) if data else self.send_error_json(404, "Theme not found")

        if path.startswith("/api/v1/themes/") and path.endswith("/risks"):
            theme_id = unquote(path.split("/")[4])
            theme = find_theme(theme_id, date)
            return self.send_json({"date": date, "theme_id": theme_id, "items": theme["risks"]}) if theme else self.send_error_json(404, "Theme not found")

        if path.startswith("/api/v1/themes/") and path.endswith("/risk-history"):
            theme_id = unquote(path.split("/")[4])
            days = int(query.get("days", ["20"])[0])
            if use_snapshot:
                snapshot = load_risk_history_snapshot(theme_id, date, days)
                if snapshot:
                    return self.send_json(snapshot)
            return self.send_json(attach_live_meta(risk_history_payload(theme_id, date, days)))

        if path.startswith("/api/v1/themes/") and path.endswith("/relay-break"):
            theme_id = unquote(path.split("/")[4])
            theme = find_theme(theme_id, date)
            if not theme:
                return self.send_error_json(404, "Theme not found")
            relay_items = []
            for sector in theme.get("sectors", []):
                relay = sector.get("stats", {}).get("relay_break", {})
                relay_items.append({
                    "sector_id": sector["sector_id"],
                    "sector_name": sector["sector_name"],
                    "relay_break": relay,
                })
            return self.send_json({"date": date, "theme_id": theme_id, "theme_name": theme["theme_name"], "sectors": relay_items})

        if path.startswith("/api/v1/themes/") and path.endswith("/stage-history"):
            theme_id = unquote(path.split("/")[4])
            days = int(query.get("days", ["20"])[0])
            import sqlite3 as _sql3s
            with _sql3s.connect(DB_PATH) as _conn:
                history = load_stage_history(_conn, theme_id, date, days)
            return self.send_json({"date": date, "theme_id": theme_id, "days": days, "items": history})

        if path.startswith("/api/v1/themes/") and path.endswith("/factor-contribution"):
            theme_id = unquote(path.split("/")[4])
            theme = find_theme(theme_id, date)
            if not theme:
                return self.send_error_json(404, "Theme not found")
            return self.send_json({"date": date, "theme_id": theme_id, "factor_contribution": theme["factor_contribution"]})

        if path.startswith("/api/v1/themes/") and path.endswith("/sentiment-history"):
            theme_id = unquote(path.split("/")[4])
            days = int(query.get("days", ["20"])[0])
            theme = find_theme(theme_id, date)
            if not theme:
                return self.send_error_json(404, "Theme not found")
            sector_codes = [s["sector_id"] for s in theme.get("sectors", [])]
            import sqlite3 as _sql3sh
            from sentiment_store import sentiment_history
            with _sql3sh.connect(DB_PATH) as _conn:
                items = sentiment_history(_conn, sector_codes, date, days)
            return self.send_json({"date": date, "theme_id": theme_id, "days": days, "items": items})

        if path == "/api/v1/reports/daily":
            return self.send_json(daily_report(date))

        if path == "/api/v1/portfolio/risk":
            return self.send_json(portfolio_risk(date))

        if path == "/api/v1/data/eastmoney/status":
            return self.send_json(eastmoney_status())

        if path == "/api/v1/data/quality":
            return self.send_json(data_quality_payload())

        if path == "/api/v1/data/coverage":
            required_years = float(query.get("required_years", ["5"])[0])
            return self.send_json(data_coverage_payload(required_years))

        if path == "/api/v1/data/no-future-guard":
            return self.send_json(no_future_guard_payload())

        if path == "/api/v1/tasks/status":
            import sqlite3 as _sqlite3
            _db = CURRENT_DIR / "data" / "radar.db"
            result: dict[str, Any] = {"snapshots": {}, "backtest": []}
            with _sqlite3.connect(_db) as conn:
                # 快照构建日志：最近每种类型的状态
                rows = conn.execute(
                    """
                    select trade_date, snapshot_type, status, message, created_at
                    from local_snapshot_build_log
                    where id in (
                        select max(id) from local_snapshot_build_log group by trade_date, snapshot_type
                    )
                    order by created_at desc
                    limit 30
                    """
                ).fetchall()
                for r in rows:
                    key = f"{r[0]}:{r[1]}"
                    result["snapshots"][key] = {
                        "trade_date": r[0],
                        "type": r[1],
                        "status": r[2],
                        "message": r[3],
                        "created_at": r[4],
                    }
                # 最近回测任务
                bt_rows = conn.execute(
                    """
                    select task_id, status, error, started_at, finished_at
                    from local_backtest_run
                    order by started_at desc
                    limit 10
                    """
                ).fetchall()
                for r in bt_rows:
                    result["backtest"].append({
                        "task_id": r[0],
                        "status": r[1],
                        "error": r[2],
                        "started_at": r[3],
                        "finished_at": r[4],
                    })
            return self.send_json(result)

        if path == "/api/v1/catalysts":
            limit = int(query.get("limit", ["100"])[0])
            return self.send_json({"items": list_catalysts(date, limit)})

        # AKShare 数据状态
        if path == "/api/v1/data/akshare/status":
            import sqlite3 as _sql3
            _db = CURRENT_DIR / "data" / "radar.db"
            with _sql3.connect(_db) as _c:
                return self.send_json(akshare_status(_c))

        if path == "/api/v1/sectors":
            limit = int(query.get("limit", ["100"])[0])
            keyword = query.get("q", [""])[0]
            return self.send_json({"items": list_sectors(keyword, limit)})

        if path.startswith("/api/v1/sectors/") and path.endswith("/constituents"):
            sector_code = unquote(path.split("/")[4])
            limit = int(query.get("limit", ["500"])[0])
            as_of = query.get("as_of_date", [None])[0]
            return self.send_json(sector_constituents(sector_code, limit, as_of))

        if path.startswith("/api/v1/sectors/") and path.endswith("/dates"):
            sector_code = unquote(path.split("/")[4])
            return self.send_json({"sector_code": sector_code, "dates": sector_constituent_dates(sector_code)})

        if path.startswith("/api/v1/sectors/") and path.endswith("/diff"):
            sector_code = unquote(path.split("/")[4])
            date_a = query.get("date_a", [""])[0]
            date_b = query.get("date_b", [""])[0]
            if not date_a or not date_b:
                return self.send_error_json(400, "需要 date_a 和 date_b 参数")
            return self.send_json(sector_diff(sector_code, date_a, date_b))

        # --- 主线管理 (FR-003) ---
        if path == "/api/v1/themes/manage" and method == "GET":
            status_filter = query.get("status", [None])[0]
            return self.send_json({"items": list_themes(status_filter)})

        if path.startswith("/api/v1/themes/manage/") and path.endswith("/history"):
            theme_id = unquote(path.split("/")[4])
            return self.send_json({"theme_id": theme_id, "items": theme_history(theme_id)})

        # 自动聚合结果查询
        if path == "/api/v1/themes/auto-clusters":
            import sqlite3 as _sqlite3
            date_param = query.get("date", [""])[0]
            version_param = query.get("version", [None])[0]
            version = int(version_param) if version_param else None
            _db = CURRENT_DIR / "data" / "radar.db"
            with _sqlite3.connect(_db) as conn:
                if date_param:
                    items = load_clusters(conn, date_param, version)
                else:
                    items = list_cluster_dates(conn)
            return self.send_json({"items": items})

        if path == "/api/v1/custom-sectors" and method == "GET":
            return self.send_json({"items": list_custom_sectors()})

        if path.startswith("/api/v1/sectors/") and path.endswith("/diff"):
            sector_code = unquote(path.split("/")[4])
            date_a = query.get("date_a", [""])[0]
            date_b = query.get("date_b", [""])[0]
            if not date_a or not date_b:
                return self.send_error_json(400, "需要 date_a 和 date_b 参数")

        if path == "/api/v1/model/config":
            return self.send_json({"active": get_active_config(), "items": list_configs()})

        if path == "/api/v1/auth/roles":
            return self.send_json(roles_payload(self.current_role()))

        if path == "/api/v1/alerts":
            return self.send_json({"date": date, "items": compute_alerts(date)})

        if path == "/api/v1/factors/effectiveness":
            holding_period = int(query.get("holding_period", ["3"])[0])
            if use_snapshot:
                snapshot = load_factor_effectiveness_snapshot(date, holding_period)
                if snapshot:
                    return self.send_json(snapshot)
            return self.send_json(attach_live_meta(factor_effectiveness_payload(date, holding_period)))

        if path == "/api/v1/themes/matrix":
            days = int(query.get("days", ["20"])[0])
            limit_arg = query.get("limit", ["10"])[0]
            limit = None if limit_arg == "all" else int(limit_arg)
            if use_snapshot:
                snapshot = load_matrix_snapshot(date, days, limit)
                if snapshot:
                    return self.send_json(snapshot)
            return self.send_json(attach_live_meta(theme_matrix_payload(date, days, limit)))

        if path == "/api/v1/confidence/history":
            days = int(query.get("days", ["20"])[0])
            if use_snapshot:
                snapshot = load_confidence_history_snapshot(date, days)
                if snapshot:
                    return self.send_json(snapshot)
            return self.send_json(attach_live_meta(confidence_history_payload(date, days)))

        if path == "/api/v1/snapshots/status":
            return self.send_json(snapshot_status(date))

        if path == "/api/v1/backtest/runs":
            if not self.require_permission("run_backtest"):
                return
            limit = int(query.get("limit", ["50"])[0])
            return self.send_json({"items": list_backtest_runs(limit)})

        if path.startswith("/api/v1/backtest/runs/"):
            if not self.require_permission("run_backtest"):
                return
            task_id = unquote(path.split("/")[5])
            run = get_backtest_run(task_id)
            return self.send_json(run) if run else self.send_error_json(404, "Backtest run not found")

        if path == "/api/v1/audit/logs":
            if not self.require_permission("view_audit"):
                return
            limit = int(query.get("limit", ["100"])[0])
            return self.send_json({"items": list_audit_logs(limit)})

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
        self.audit_access("POST", parsed.path, query)
        if parsed.path == "/api/v1/backtest/run":
            if not self.require_permission("run_backtest"):
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                return self.send_error_json(400, "Invalid JSON body")
            task_id = create_backtest_run(body)
            is_async = bool(body.get("async")) or query.get("async", ["0"])[0] in ("1", "true", "yes")
            if is_async:
                worker = threading.Thread(target=run_backtest_task, args=(task_id, body), daemon=True)
                worker.start()
                return self.send_json({"task_id": task_id, "status": "running", "request": body})
            try:
                result = finish_backtest_run(task_id, backtest_result(body))
            except Exception as exc:
                fail_backtest_run(task_id, str(exc))
                return self.send_error_json(500, f"回测失败：{exc}")
            write_audit("backtest_run", method="POST", path=parsed.path, target=result.get("task_id"), detail=result.get("metrics", {}))
            return self.send_json(result)

        # AKShare 数据同步
        if parsed.path == "/api/v1/data/akshare/sync":
            if not self.require_permission("run_backtest"):
                return
            import sqlite3 as _sql3
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {}
            sync_type = body.get("type", "all")
            _db = CURRENT_DIR / "data" / "radar.db"
            results: dict[str, Any] = {}
            with _sql3.connect(_db) as _c:
                init_akshare_schema(_c)
                if sync_type in ("lhb", "all"):
                    start = body.get("start_date", date.replace("-", ""))
                    end = body.get("end_date", start)
                    try:
                        df = fetch_dragon_tiger(start, end)
                        count = save_dragon_tiger(_c, df)
                        results["dragon_tiger"] = count
                    except Exception as exc:
                        results["dragon_tiger_error"] = str(exc)
                if sync_type in ("hot", "all"):
                    try:
                        df = fetch_hot_rank()
                        count = save_hot_rank(_c, df)
                        results["hot_rank"] = count
                    except Exception as exc:
                        results["hot_rank_error"] = str(exc)
            return self.send_json({"status": "completed", "results": results})
        if parsed.path == "/api/v1/reviews/save":
            if not self.require_permission("save_review"):
                return
            result = save_daily_review(date)
            write_audit("review_save", method="POST", path=parsed.path, target=date, detail=result)
            return self.send_json(result)
        if parsed.path == "/api/v1/watchlist":
            if not self.require_permission("manage_own_watchlist"):
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
                result = add_watchlist(str(body.get("symbol", "")), body.get("name"), body.get("tag"))
                write_audit("watchlist_add", method="POST", path=parsed.path, target=result.get("symbol"), detail=result)
                return self.send_json(result)
            except (json.JSONDecodeError, ValueError) as exc:
                return self.send_error_json(400, str(exc))
        if parsed.path == "/api/v1/positions":
            if not self.require_permission("manage_own_watchlist"):
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
                result = add_position(
                    str(body.get("symbol", "")),
                    body.get("name"),
                    float(body.get("quantity", 0)),
                    float(body["cost_price"]) if body.get("cost_price") not in (None, "") else None,
                    body.get("tag"),
                )
                write_audit("position_save", method="POST", path=parsed.path, target=result.get("symbol"), detail=result)
                return self.send_json(result)
            except (json.JSONDecodeError, ValueError) as exc:
                return self.send_error_json(400, str(exc))
        if parsed.path == "/api/v1/model/config":
            if not self.require_permission("manage_model"):
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
                result = save_config(body)
                clear_scoring_cache()
                write_audit("model_config_save", method="POST", path=parsed.path, target=result.get("config_version"), detail=result)
                return self.send_json(result)
            except (json.JSONDecodeError, ValueError) as exc:
                return self.send_error_json(400, str(exc))
        if parsed.path == "/api/v1/catalysts":
            if not self.require_permission("manage_model"):
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
                result = add_catalyst(body)
                write_audit("catalyst_add", method="POST", path=parsed.path, target=str(result.get("id")), detail=result)
                return self.send_json(result)
            except (json.JSONDecodeError, ValueError) as exc:
                return self.send_error_json(400, str(exc))
        # --- 主线管理 POST ---
        if parsed.path == "/api/v1/themes/manage":
            if not self.require_permission("manage_model"):
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
                theme_id = str(body.get("theme_id", ""))
                theme_name = str(body.get("theme_name", ""))
                category = str(body.get("category", ""))
                if not theme_id or not theme_name:
                    return self.send_error_json(400, "theme_id 和 theme_name 不能为空")
                result = save_theme(theme_id, theme_name, category, body.get("sectors"), self.current_role())
                write_audit("theme_save", method="POST", path=parsed.path, target=theme_id, detail=result)
                return self.send_json(result)
            except (json.JSONDecodeError, ValueError) as exc:
                return self.send_error_json(400, str(exc))
        if parsed.path == "/api/v1/themes/merge":
            if not self.require_permission("manage_model"):
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
                target_id = str(body.get("target_id", ""))
                source_ids = body.get("source_ids", [])
                if not target_id or not source_ids:
                    return self.send_error_json(400, "target_id 和 source_ids 不能为空")
                result = merge_themes(target_id, source_ids, self.current_role())
                write_audit("theme_merge", method="POST", path=parsed.path, target=target_id, detail={"source_ids": source_ids})
                return self.send_json(result) if result else self.send_error_json(404, "目标主线不存在")
            except (json.JSONDecodeError, ValueError) as exc:
                return self.send_error_json(400, str(exc))
        if parsed.path == "/api/v1/themes/archive":
            if not self.require_permission("manage_model"):
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
                theme_id = str(body.get("theme_id", ""))
                archive_theme(theme_id, self.current_role())
                write_audit("theme_archive", method="POST", path=parsed.path, target=theme_id)
                return self.send_json({"theme_id": theme_id, "status": "ok"})
            except (json.JSONDecodeError, ValueError) as exc:
                return self.send_error_json(400, str(exc))
        if parsed.path == "/api/v1/custom-sectors":
            if not self.require_permission("manage_model"):
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw)
                result = save_custom_sector(
                    str(body.get("sector_id", "")),
                    str(body.get("sector_name", "")),
                    str(body.get("category", "")),
                    str(body.get("keywords", "")),
                    body.get("symbols", []),
                )
                write_audit("custom_sector_save", method="POST", path=parsed.path, target=result["sector_id"])
                return self.send_json(result)
            except (json.JSONDecodeError, ValueError) as exc:
                return self.send_error_json(400, str(exc))
        return self.send_error_json(404, "Not found")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        self.audit_access("DELETE", parsed.path, {})
        if parsed.path.startswith("/api/v1/watchlist/"):
            if not self.require_permission("manage_own_watchlist"):
                return
            symbol = unquote(parsed.path.split("/")[4])
            result = delete_watchlist(symbol)
            write_audit("watchlist_delete", method="DELETE", path=parsed.path, target=symbol, detail=result)
            return self.send_json(result)
        if parsed.path.startswith("/api/v1/positions/"):
            if not self.require_permission("manage_own_watchlist"):
                return
            symbol = unquote(parsed.path.split("/")[4])
            result = delete_position(symbol)
            write_audit("position_delete", method="DELETE", path=parsed.path, target=symbol, detail=result)
            return self.send_json(result)
        if parsed.path.startswith("/api/v1/custom-sectors/"):
            if not self.require_permission("manage_model"):
                return
            sector_id = unquote(parsed.path.split("/")[4])
            result = delete_custom_sector(sector_id)
            write_audit("custom_sector_delete", method="DELETE", path=parsed.path, target=sector_id)
            return self.send_json({"deleted": result})
        return self.send_error_json(404, "Not found")

    def audit_access(self, method: str, path: str, query: dict[str, list[str]]) -> None:
        if path.startswith("/api/v1/") and path != "/api/v1/audit/logs":
            write_audit("api_access", method=method, path=path, detail={"query": query, "role": self.current_role()})

    def current_role(self) -> str:
        return self.headers.get("X-User-Role") or "admin"

    def require_permission(self, permission: str) -> bool:
        role = self.current_role()
        if has_permission(role, permission):
            return True
        self.send_error_json(403, f"当前角色无权限：{permission}")
        write_audit("permission_denied", method=self.command, path=urlparse(self.path).path, target=permission, detail={"role": role})
        return False

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
        ranking = ranking_payload(date, limit=None)
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

        disclaimer_text = "本系统为个人研究辅助工具，所有数据、评分和排序仅供学习参考，不构成任何投资建议。请勿据此做出投资决策。"

        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            pd.DataFrame([{"免责声明": disclaimer_text}]).to_excel(writer, index=False, sheet_name="免责声明")
            pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="主线榜单")
            pd.DataFrame(risk_rows).to_excel(writer, index=False, sheet_name="风险明细")
            pd.DataFrame([ranking["components"]]).to_excel(writer, index=False, sheet_name="置信度")
            report = daily_report(date)
            pd.DataFrame([{"日期": report["date"], "复盘": report["report"]}]).to_excel(writer, index=False, sheet_name="复盘报告")
            matrix = theme_matrix_payload(date, 20, None)
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
    if (CURRENT_DIR / "data" / "radar.db").exists():
        init_snapshot_schema()
    httpd = ThreadingHTTPServer((host, port), RadarHandler)
    print(f"A股板块主线雷达 demo running at http://{host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
