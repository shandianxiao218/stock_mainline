"""预警提醒系统（SRS FR-015）。

基于当前和前一个交易日的榜单数据对比，生成预警信号。
"""
from __future__ import annotations

from typing import Any

from real_scoring import build_themes_for_date, db_ready, resolve_trade_date, date_text
import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"


def compute_alerts(date: str) -> list[dict[str, Any]]:
    """计算指定日期的所有预警信号。"""
    if not db_ready():
        return []

    with sqlite3.connect(DB_PATH) as conn:
        trade_date = resolve_trade_date(conn, date)
        # 获取前一个交易日
        prev_row = conn.execute(
            "select max(trade_date) from em_daily_quote where trade_date < ?",
            (trade_date,),
        ).fetchone()
        if not prev_row or prev_row[0] is None:
            return []
        prev_date = date_text(int(prev_row[0]))

    today_themes = build_themes_for_date(date)[0]
    prev_themes = build_themes_for_date(prev_date)[0]

    alerts: list[dict[str, Any]] = []

    today_map = {t["theme_id"]: t for t in today_themes}
    prev_map = {t["theme_id"]: t for t in prev_themes}

    # 1. 新主线进入前 10
    today_top_ids = {t["theme_id"] for t in today_themes[:10]}
    prev_top_ids = {t["theme_id"] for t in prev_themes[:10]}
    for theme_id in today_top_ids - prev_top_ids:
        theme = today_map[theme_id]
        alerts.append({
            "alert_type": "new_top10",
            "severity": "medium",
            "theme_id": theme_id,
            "theme_name": theme["theme_name"],
            "message": f"新主线「{theme['theme_name']}」进入前10，当前排名第{theme['rank']}",
        })

    # 2. 排名快速上升（>=3 位）
    for theme in today_themes[:15]:
        prev_theme = prev_map.get(theme["theme_id"])
        if prev_theme and prev_theme["rank"] - theme["rank"] >= 3:
            alerts.append({
                "alert_type": "rank_surge",
                "severity": "medium",
                "theme_id": theme["theme_id"],
                "theme_name": theme["theme_name"],
                "message": f"「{theme['theme_name']}」排名从第{prev_theme['rank']}升至第{theme['rank']}",
            })

    # 3. 头部主线风险扣分快速上升（>=3）
    for theme in today_themes[:10]:
        prev_theme = prev_map.get(theme["theme_id"])
        if prev_theme and theme["risk_penalty"] - prev_theme["risk_penalty"] >= 3:
            alerts.append({
                "alert_type": "risk_surge",
                "severity": "high",
                "theme_id": theme["theme_id"],
                "theme_name": theme["theme_name"],
                "message": f"「{theme['theme_name']}」风险扣分从{prev_theme['risk_penalty']}升至{theme['risk_penalty']}",
            })

    # 4. 核心股炸板
    for theme in today_themes[:10]:
        for stock in theme.get("stock_metrics", [])[:5]:
            if stock.get("limit_break"):
                alerts.append({
                    "alert_type": "core_break",
                    "severity": "high",
                    "theme_id": theme["theme_id"],
                    "theme_name": theme["theme_name"],
                    "message": f"「{theme['theme_name']}」核心股{stock['name']}({stock['symbol']})炸板",
                })

    # 5. 资金接力断裂
    for theme in today_themes[:10]:
        for sector in theme.get("sectors", []):
            relay = sector.get("stats", {}).get("relay_break", {})
            if relay.get("lead_continue_rate") is not None and relay["lead_continue_rate"] < 0.4:
                alerts.append({
                    "alert_type": "relay_break",
                    "severity": "high",
                    "theme_id": theme["theme_id"],
                    "theme_name": theme["theme_name"],
                    "message": f"「{theme['theme_name']}」板块{sector['sector_name']}资金接力断裂，领涨延续率{relay['lead_continue_rate'] * 100:.0f}%",
                })
                break

    # 6. 置信度下降（高→中 或 中→低）
    today_conf = _overall_confidence(today_themes)
    prev_conf = _overall_confidence(prev_themes)
    conf_order = {"high": 3, "medium": 2, "low": 1}
    if prev_conf and today_conf and conf_order.get(today_conf, 0) < conf_order.get(prev_conf, 0):
        alerts.append({
            "alert_type": "confidence_drop",
            "severity": "medium",
            "theme_id": None,
            "theme_name": None,
            "message": f"模型置信度从「{_level_cn(prev_conf)}」降至「{_level_cn(today_conf)}」",
        })

    # 7. 高位放量滞涨
    for theme in today_themes[:10]:
        for risk in theme.get("risks", []):
            if risk["risk_type"] == "高位放量滞涨":
                alerts.append({
                    "alert_type": "high_vol_stagnation",
                    "severity": "medium",
                    "theme_id": theme["theme_id"],
                    "theme_name": theme["theme_name"],
                    "message": f"「{theme['theme_name']}」高位放量滞涨，扣分{risk['penalty']}",
                })

    # 按严重程度排序
    severity_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: (severity_order.get(a["severity"], 3), a.get("theme_id") or ""))
    return alerts


def _overall_confidence(themes: list[dict[str, Any]]) -> str | None:
    if not themes:
        return None
    from real_scoring import confidence
    # 需要重新构建 market 数据来计算置信度，简化处理取第一条的置信度
    return themes[0].get("confidence", "medium") if themes else None


def _level_cn(level: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(level, level)
