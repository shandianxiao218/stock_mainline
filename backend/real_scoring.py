from __future__ import annotations

import math
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

from theme_universe import CATEGORY_LABELS, PORTFOLIO, THEME_SECTORS, WATCHLIST

try:
    from watchlist_store import list_positions, list_watchlist
except ImportError:
    list_positions = None
    list_watchlist = None


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"

HEAT_WEIGHTS = {
    "成交活跃度": 26,
    "涨停与短线情绪": 24,
    "当日价格强度": 14,
    "板块广度": 14,
    "舆情边际变化率": 8,
    "舆情绝对热度": 4,
    "催化强度": 6,
    "容量与可交易性": 4,
}

CONTINUATION_WEIGHTS = {
    "成交额持续性": 22,
    "板块广度持续性": 20,
    "核心股结构": 18,
    "涨停质量": 14,
    "价格相对强度": 12,
    "催化持续性": 8,
    "舆情边际变化": 4,
    "容量与中军承接": 2,
}


@dataclass
class SectorScore:
    raw: dict[str, Any]
    heat_score: float
    continuation_score: float
    risk_penalty: float
    composite_score: float


def db_ready() -> bool:
    return DB_PATH.exists()


def parse_date(date: str) -> int:
    return int(date.replace("-", ""))


def date_text(date_int: int) -> str:
    text = str(date_int)
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def safe_mean(values: list[float], default: float = 0.0) -> float:
    return mean(values) if values else default


def pct_score(pct: float, scale: float = 0.08) -> float:
    return clamp(50 + pct / scale * 50)


def weighted_score(factors: dict[str, float], weights: dict[str, int]) -> float:
    total = sum(weights.values())
    return round(sum(float(factors.get(name, 50)) * weight for name, weight in weights.items()) / total, 2)


def limit_threshold(symbol: str) -> float:
    if symbol.startswith(("300", "301", "688", "689")):
        return 0.195
    if symbol.startswith(("8", "4")):
        return 0.295
    return 0.095


def resolve_trade_date(conn: sqlite3.Connection, requested: str) -> int:
    requested_int = parse_date(requested)
    row = conn.execute(
        "select max(trade_date) from em_daily_quote where trade_date <= ?",
        (requested_int,),
    ).fetchone()
    if not row or row[0] is None:
        row = conn.execute("select max(trade_date) from em_daily_quote").fetchone()
    if not row or row[0] is None:
        raise RuntimeError("本地数据库没有可用日线数据")
    return int(row[0])


def load_histories(conn: sqlite3.Connection, symbols: list[str], trade_date: int, window: int = 25) -> dict[str, list[dict[str, Any]]]:
    histories: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols:
        rows = conn.execute(
            """
            select symbol, trade_date, open, high, low, close, volume, amount
            from em_daily_quote
            where symbol = ? and trade_date <= ?
            order by trade_date desc
            limit ?
            """,
            (symbol, trade_date, window),
        ).fetchall()
        history = [
            {
                "symbol": row[0],
                "trade_date": row[1],
                "open": row[2],
                "high": row[3],
                "low": row[4],
                "close": row[5],
                "volume": row[6],
                "amount": row[7],
            }
            for row in reversed(rows)
        ]
        if history:
            histories[symbol] = history
    return histories


def stock_metrics(symbol: str, history: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(history) < 2:
        return None
    latest = history[-1]
    prev = history[-2]
    pct1 = latest["close"] / prev["close"] - 1 if prev["close"] else 0
    pct3 = latest["close"] / history[-4]["close"] - 1 if len(history) >= 4 and history[-4]["close"] else pct1
    pct5 = latest["close"] / history[-6]["close"] - 1 if len(history) >= 6 and history[-6]["close"] else pct3
    prev_amounts = [row["amount"] for row in history[-6:-1] if row["amount"] > 0]
    amount_ratio = latest["amount"] / safe_mean(prev_amounts, latest["amount"]) if prev_amounts else 1
    pos = (latest["close"] - latest["low"]) / (latest["high"] - latest["low"]) if latest["high"] > latest["low"] else 0.5
    limit_up = pct1 >= limit_threshold(symbol)
    touched_limit = latest["high"] / prev["close"] - 1 >= limit_threshold(symbol) if prev["close"] else False
    limit_break = touched_limit and not limit_up
    drawdown = latest["close"] / max(row["close"] for row in history[-10:]) - 1 if history[-10:] else 0
    return {
        **latest,
        "prev_close": prev["close"],
        "pct1": pct1,
        "pct3": pct3,
        "pct5": pct5,
        "amount_ratio": amount_ratio,
        "close_position": pos,
        "limit_up": limit_up,
        "touched_limit": touched_limit,
        "limit_break": limit_break,
        "drawdown_10": drawdown,
    }


def build_market_snapshot(conn: sqlite3.Connection, trade_date: int) -> dict[str, Any]:
    rows = conn.execute(
        """
        select q.symbol, q.close, q.amount, p.close
        from em_daily_quote q
        join em_daily_quote p on p.symbol = q.symbol
        where q.trade_date = ?
          and p.trade_date = (
            select max(trade_date) from em_daily_quote
            where symbol = q.symbol and trade_date < ?
          )
          and q.close > 0 and p.close > 0
        """,
        (trade_date, trade_date),
    ).fetchall()
    pcts = [row[1] / row[3] - 1 for row in rows if row[3]]
    amounts = [row[2] for row in rows if row[2]]
    market_amount = sum(amounts)

    prev_amount_rows = conn.execute(
        """
        select trade_date, sum(amount)
        from em_daily_quote
        where trade_date < ?
        group by trade_date
        order by trade_date desc
        limit 20
        """,
        (trade_date,),
    ).fetchall()
    avg_amount_20 = safe_mean([row[1] for row in prev_amount_rows], market_amount)
    turnover_ratio = market_amount / avg_amount_20 if avg_amount_20 else 1
    up_ratio = sum(1 for pct in pcts if pct > 0) / len(pcts) if pcts else 0
    median_pct = median(pcts) if pcts else 0
    limit_count = sum(1 for symbol, close, amount, prev_close in rows if prev_close and close / prev_close - 1 >= limit_threshold(symbol))
    return {
        "date": date_text(trade_date),
        "trade_date": trade_date,
        "stock_count": len(rows),
        "market_amount": round(market_amount, 2),
        "turnover_ratio_20d": round(turnover_ratio, 3),
        "up_ratio": round(up_ratio, 4),
        "median_pct_chg": round(median_pct * 100, 2),
        "limit_up_count": limit_count,
        "limit_break_rate": None,
        "summary": (
            f"本地东方财富日线覆盖{len(rows)}只股票，成交额为近20日均值的{turnover_ratio:.2f}倍，"
            f"上涨家数占比{up_ratio:.0%}，市场中位涨跌幅{median_pct * 100:.2f}%。"
        ),
    }


def score_sector_from_db(conn: sqlite3.Connection, sector: dict[str, Any], trade_date: int, market_amount: float) -> SectorScore:
    symbols = [code for code, _name in sector["stocks"]]
    histories = load_histories(conn, symbols, trade_date)
    metrics = [stock_metrics(symbol, history) for symbol, history in histories.items()]
    metrics = [item for item in metrics if item]

    if not metrics:
        raw = {**sector, "core_stocks": [name for _code, name in sector["stocks"]], "factors": {}, "risks": {"数据缺失": 12.0}}
        return SectorScore(raw, 35.0, 30.0, 12.0, 20.0)

    pcts = [item["pct1"] for item in metrics]
    pct3s = [item["pct3"] for item in metrics]
    pct5s = [item["pct5"] for item in metrics]
    amount = sum(item["amount"] for item in metrics)
    amount_ratio = safe_mean([item["amount_ratio"] for item in metrics], 1)
    up_ratio = sum(1 for pct in pcts if pct > 0) / len(pcts)
    limit_count = sum(1 for item in metrics if item["limit_up"])
    limit_rate = limit_count / len(metrics)
    median_pct = median(pcts)
    avg_pct = safe_mean(pcts)
    avg_pct3 = safe_mean(pct3s)
    avg_pct5 = safe_mean(pct5s)
    close_pos = safe_mean([item["close_position"] for item in metrics], 0.5)
    core_pcts = pcts[: min(3, len(pcts))]
    core_avg = safe_mean(core_pcts, avg_pct)
    tail_avg = safe_mean(pcts[min(3, len(pcts)):], avg_pct)
    amount_share = amount / market_amount if market_amount else 0

    heat_factors = {
        "成交活跃度": clamp(42 + math.log1p(amount / 1_000_000_000) * 14 + (amount_ratio - 1) * 22),
        "涨停与短线情绪": clamp(35 + limit_rate * 150 + max(avg_pct, 0) * 280),
        "当日价格强度": pct_score(avg_pct, 0.08),
        "板块广度": clamp(35 + up_ratio * 55 + max(median_pct, 0) * 180),
        "舆情边际变化率": 50,
        "舆情绝对热度": 45,
        "催化强度": 58 if sector.get("catalysts") else 45,
        "容量与可交易性": clamp(35 + amount_share * 800 + math.log1p(amount / 500_000_000) * 12),
    }
    continuation_factors = {
        "成交额持续性": clamp(45 + (amount_ratio - 1) * 25 + max(avg_pct3, 0) * 120),
        "板块广度持续性": clamp(35 + up_ratio * 45 + max(avg_pct3, 0) * 120),
        "核心股结构": clamp(50 + core_avg * 220 - max(tail_avg - core_avg, 0) * 180),
        "涨停质量": clamp(45 + limit_rate * 110 - max(0, 0.45 - close_pos) * 45),
        "价格相对强度": pct_score(avg_pct5, 0.14),
        "催化持续性": 58 if sector.get("catalysts") else 48,
        "舆情边际变化": 50,
        "容量与中军承接": clamp(40 + amount_share * 600 + math.log1p(amount / 800_000_000) * 12),
    }

    risks: dict[str, float] = {}
    if avg_pct5 > 0.18 and amount_ratio > 1.8:
        risks["板块连续高潮"] = min(4.0, 1.5 + avg_pct5 * 10)
    if close_pos < 0.35 and amount_ratio > 1.3:
        risks["高位放量滞涨"] = min(4.0, 1.0 + (1.4 - close_pos) * 2)
    if core_avg < tail_avg - 0.015:
        risks["核心股走弱"] = min(5.0, 2.0 + (tail_avg - core_avg) * 70)
        risks["资金接力断裂"] = min(5.0, 1.0 + (tail_avg - core_avg) * 60)
    if up_ratio < 0.35 and avg_pct > 0:
        risks["后排不跟/广度不足"] = min(3.0, 1.0 + (0.35 - up_ratio) * 5)
    if amount_ratio > 2.2 and avg_pct < 0.01:
        risks["舆情/成交过热"] = min(3.0, 1.0 + (amount_ratio - 2.2))

    heat = weighted_score(heat_factors, HEAT_WEIGHTS)
    continuation = weighted_score(continuation_factors, CONTINUATION_WEIGHTS)
    risk = min(20.0, sum(risks.values()))
    composite = round(0.4 * heat + 0.6 * continuation - risk, 2)
    raw = {
        **sector,
        "core_stocks": [name for _code, name in sector["stocks"]],
        "stock_metrics": [
            {
                "symbol": item["symbol"],
                "name": next((name for code, name in sector["stocks"] if code == item["symbol"]), item["symbol"]),
                "pct1": round(item["pct1"] * 100, 2),
                "pct3": round(item["pct3"] * 100, 2),
                "pct5": round(item["pct5"] * 100, 2),
                "open": item["open"],
                "high": item["high"],
                "low": item["low"],
                "close": item["close"],
                "volume": item["volume"],
                "amount": round(item["amount"], 2),
                "limit_up": item["limit_up"],
                "limit_break": item["limit_break"],
                "hot_money": "未接入",
            }
            for item in sorted(metrics, key=lambda row: row["amount"], reverse=True)
        ],
        "factors": {**heat_factors, **continuation_factors},
        "risks": risks,
        "stats": {
            "stock_count": len(metrics),
            "avg_pct": round(avg_pct * 100, 2),
            "median_pct": round(median_pct * 100, 2),
            "avg_pct3": round(avg_pct3 * 100, 2),
            "avg_pct5": round(avg_pct5 * 100, 2),
            "up_ratio": round(up_ratio, 4),
            "amount": round(amount, 2),
            "amount_ratio": round(amount_ratio, 3),
            "limit_count": limit_count,
            "close_position": round(close_pos, 3),
        },
    }
    return SectorScore(raw, heat, continuation, round(risk, 2), composite)


def similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    keyword_union = set(left["keywords"]) | set(right["keywords"])
    keyword_score = len(set(left["keywords"]) & set(right["keywords"])) / len(keyword_union) if keyword_union else 0
    stock_union = {code for code, _name in left["stocks"]} | {code for code, _name in right["stocks"]}
    stock_score = len({code for code, _name in left["stocks"]} & {code for code, _name in right["stocks"]}) / len(stock_union) if stock_union else 0
    category_score = 1.0 if left["category"] == right["category"] else 0
    return 0.50 * category_score + 0.30 * keyword_score + 0.20 * stock_score


def aggregate_sectors(scored: list[SectorScore]) -> list[list[SectorScore]]:
    graph: dict[int, set[int]] = defaultdict(set)
    for i, left in enumerate(scored):
        for j, right in enumerate(scored):
            if i >= j:
                continue
            if similarity(left.raw, right.raw) >= 0.48:
                graph[i].add(j)
                graph[j].add(i)
    visited: set[int] = set()
    clusters: list[list[SectorScore]] = []
    for idx in range(len(scored)):
        if idx in visited:
            continue
        component: list[SectorScore] = []
        queue: deque[int] = deque([idx])
        visited.add(idx)
        while queue:
            current = queue.popleft()
            component.append(scored[current])
            for nxt in graph[current]:
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        clusters.append(component)
    return clusters


def risk_items(cluster: list[SectorScore]) -> list[dict[str, Any]]:
    totals: dict[str, float] = defaultdict(float)
    reasons: dict[str, list[str]] = defaultdict(list)
    for item in cluster:
        for risk_type, penalty in item.raw.get("risks", {}).items():
            totals[risk_type] += float(penalty)
            reasons[risk_type].append(item.raw["sector_name"])
    rows = []
    for risk_type, penalty in sorted(totals.items(), key=lambda pair: pair[1], reverse=True):
        rows.append({
            "risk_type": risk_type,
            "penalty": round(min(penalty, 5.0), 2),
            "severity": "high" if penalty >= 4 else "medium" if penalty >= 2 else "low",
            "reason": f"{'、'.join(reasons[risk_type])}触发{risk_type}信号",
        })
    return rows


def theme_status(score: float, heat: float, continuation: float, risk: float) -> str:
    if risk >= 10 and heat >= 78:
        return "高位分歧主线"
    if heat >= 72 and continuation >= 66 and risk < 7:
        return "强势延续主线"
    if heat >= 68 and risk < 8:
        return "新晋观察主线"
    if continuation >= 68 and heat < 65:
        return "防御延续主线"
    if risk >= 8:
        return "退潮风险主线"
    if score >= 58:
        return "活跃轮动主线"
    return "观察支线"


def factor_contribution(cluster: list[SectorScore]) -> dict[str, Any]:
    count = len(cluster)
    heat = defaultdict(float)
    continuation = defaultdict(float)
    risk = defaultdict(float)
    for item in cluster:
        for key in HEAT_WEIGHTS:
            heat[key] += item.raw["factors"].get(key, 50)
        for key in CONTINUATION_WEIGHTS:
            continuation[key] += item.raw["factors"].get(key, 50)
        for key, value in item.raw.get("risks", {}).items():
            risk[key] += value
    return {
        "heat": [{"name": key, "score": round(value / count, 2), "weight": HEAT_WEIGHTS[key]} for key, value in heat.items()],
        "continuation": [{"name": key, "score": round(value / count, 2), "weight": CONTINUATION_WEIGHTS[key]} for key, value in continuation.items()],
        "risk": [{"name": key, "penalty": round(value, 2)} for key, value in sorted(risk.items(), key=lambda pair: pair[1], reverse=True)],
    }


def build_themes_for_date(date: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        trade_date = resolve_trade_date(conn, date)
        market = build_market_snapshot(conn, trade_date)
        scored = [score_sector_from_db(conn, sector, trade_date, market["market_amount"]) for sector in THEME_SECTORS]
    clusters = aggregate_sectors(scored)
    themes: list[dict[str, Any]] = []
    for idx, cluster in enumerate(clusters, start=1):
        cluster = sorted(cluster, key=lambda item: item.composite_score, reverse=True)
        categories = [item.raw["category"] for item in cluster]
        category = max(set(categories), key=categories.count)
        total_weight = sum(max(item.composite_score, 1) for item in cluster)

        def avg(attr: str) -> float:
            return sum(getattr(item, attr) * max(item.composite_score, 1) for item in cluster) / total_weight

        heat = round(avg("heat_score"), 2)
        continuation = round(avg("continuation_score"), 2)
        risk = round(min(20.0, avg("risk_penalty")), 2)
        theme_score = round(0.4 * heat + 0.6 * continuation - risk, 2)
        branches = [item.raw["branch"] for item in cluster]
        core_stocks = []
        stock_metrics = []
        for item in cluster:
            stock_metrics.extend(item.raw.get("stock_metrics", []))
            for stock in item.raw["core_stocks"]:
                if stock not in core_stocks:
                    core_stocks.append(stock)

        themes.append({
            "theme_id": f"theme_{category}_{idx}",
            "theme_name": CATEGORY_LABELS.get(category, cluster[0].raw["sector_name"]),
            "theme_score": theme_score,
            "heat_score": heat,
            "continuation_score": continuation,
            "risk_penalty": risk,
            "confidence": "medium_high" if theme_score >= 68 and risk < 10 else "medium" if theme_score >= 55 else "low",
            "status": theme_status(theme_score, heat, continuation, risk),
            "branches": branches,
            "core_stocks": core_stocks[:10],
            "sectors": [
                {
                    "sector_id": item.raw["sector_id"],
                    "sector_name": item.raw["sector_name"],
                    "branch": item.raw["branch"],
                    "contribution": round(item.composite_score / total_weight * 100, 2),
                    "heat_score": item.heat_score,
                    "continuation_score": item.continuation_score,
                    "risk_penalty": item.risk_penalty,
                    "composite_score": item.composite_score,
                    "stats": item.raw.get("stats", {}),
                }
                for item in cluster
            ],
            "risks": risk_items(cluster),
            "catalysts": sorted({c for item in cluster for c in item.raw.get("catalysts", [])}),
            "next_checks": build_next_checks(cluster),
            "factor_contribution": factor_contribution(cluster),
            "stock_metrics": sorted(stock_metrics, key=lambda row: row["amount"], reverse=True),
        })
    themes.sort(key=lambda item: item["theme_score"], reverse=True)
    for rank, theme in enumerate(themes, start=1):
        theme["rank"] = rank
    return themes, market


def build_next_checks(cluster: list[SectorScore]) -> list[str]:
    strongest = max(cluster, key=lambda item: item.heat_score)
    weakest = max(cluster, key=lambda item: item.risk_penalty)
    return [
        f"观察{strongest.raw['sector_name']}成交额能否继续放大且上涨家数保持扩散",
        f"观察{weakest.raw['sector_name']}风险扣分是否下降",
        "观察核心股是否继续强于板块中位数，避免后排补涨替代主升",
    ]


def confidence(themes: list[dict[str, Any]], market: dict[str, Any]) -> dict[str, Any]:
    top = themes[:3]
    spread = top[0]["theme_score"] - top[2]["theme_score"] if len(top) >= 3 else 12
    liquidity = min(100, market["turnover_ratio_20d"] * 72)
    spread_score = min(100, 45 + spread * 4)
    avg_risk = sum(item["risk_penalty"] for item in themes[:10]) / max(1, min(10, len(themes)))
    risk_stability = max(20, 100 - avg_risk * 5)
    breadth = market["up_ratio"] * 100
    consistency = min(100, 50 + sum(len(item["sectors"]) for item in top) * 8)
    score = round(0.30 * liquidity + 0.25 * spread_score + 0.20 * risk_stability + 0.15 * breadth + 0.10 * consistency, 2)
    level = "high" if score >= 75 else "medium" if score >= 55 else "low"
    reason = (
        f"全市场成交额约为20日均值的{market['turnover_ratio_20d']:.2f}倍，"
        f"前三主线分差约{spread:.1f}分；头部风险均值{avg_risk:.1f}，"
        f"上涨家数占比{market['up_ratio']:.0%}。"
    )
    return {
        "confidence": level,
        "confidence_score": score,
        "components": {
            "liquidity": round(liquidity, 2),
            "theme_spread": round(spread_score, 2),
            "risk_stability": round(risk_stability, 2),
            "market_breadth": round(breadth, 2),
            "theme_consistency": round(consistency, 2),
        },
        "reason": reason,
    }


def ranking_payload(date: str, period: str = "short") -> dict[str, Any]:
    themes, market = build_themes_for_date(date)
    conf = confidence(themes, market)
    return {"date": market["date"], "requested_date": date, "period": period, "market": market, **conf, "items": themes}


def theme_matrix_payload(date: str, days: int = 20) -> dict[str, Any]:
    days = max(1, min(days, 60))
    with sqlite3.connect(DB_PATH) as conn:
        trade_date = resolve_trade_date(conn, date)
        rows = conn.execute(
            """
            select distinct trade_date
            from em_daily_quote
            where trade_date <= ?
            order by trade_date desc
            limit ?
            """,
            (trade_date, days),
        ).fetchall()
    dates = [date_text(row[0]) for row in reversed(rows)]
    matrix: dict[str, dict[str, Any]] = {}
    for day in dates:
        themes, _market = build_themes_for_date(day)
        for theme in themes:
            item = matrix.setdefault(
                theme["theme_id"],
                {
                    "theme_id": theme["theme_id"],
                    "theme_name": theme["theme_name"],
                    "cells": {},
                },
            )
            item["cells"][day] = {
                "rank": theme["rank"],
                "theme_score": theme["theme_score"],
                "heat_score": theme["heat_score"],
                "continuation_score": theme["continuation_score"],
                "risk_penalty": theme["risk_penalty"],
                "status": theme["status"],
            }
    rows_out = sorted(
        matrix.values(),
        key=lambda row: row["cells"].get(dates[-1], {}).get("theme_score", -999),
        reverse=True,
    )
    return {"date": dates[-1] if dates else date, "dates": dates, "items": rows_out}


def kline_payload(symbol: str, date: str, window: int = 80) -> dict[str, Any]:
    window = max(10, min(window, 240))
    with sqlite3.connect(DB_PATH) as conn:
        trade_date = resolve_trade_date(conn, date)
        rows = conn.execute(
            """
            select trade_date, open, high, low, close, volume, amount
            from em_daily_quote
            where symbol = ? and trade_date <= ?
            order by trade_date desc
            limit ?
            """,
            (symbol, trade_date, window),
        ).fetchall()
    bars = [
        {
            "date": date_text(row[0]),
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume": row[5],
            "amount": row[6],
        }
        for row in reversed(rows)
    ]
    return {"symbol": symbol, "bars": bars}


def find_theme(theme_id: str, date: str = "2026-04-29") -> dict[str, Any] | None:
    return next((theme for theme in build_themes_for_date(date)[0] if theme["theme_id"] == theme_id), None)


def detail_payload(theme_id: str, date: str) -> dict[str, Any] | None:
    theme = find_theme(theme_id, date)
    if not theme:
        return None
    return {
        "date": date,
        **theme,
        "model_explanation": (
            f"{theme['theme_name']}由{'、'.join(theme['branches'])}聚合形成，行情来自本地东方财富日线 SQLite。"
            f"当前热度{theme['heat_score']}，延续性{theme['continuation_score']}，"
            f"风险扣分{theme['risk_penalty']}，状态判断为{theme['status']}。"
        ),
    }


def daily_report(date: str) -> dict[str, Any]:
    payload = ranking_payload(date)
    items = payload["items"]
    top = items[0]
    high_risk = [item for item in items if item["risk_penalty"] >= 8]
    warming = [item for item in items if "新晋" in item["status"] or item["heat_score"] >= 68]
    text = (
        f"{payload['date']} 复盘：今日模型置信度为{payload['confidence']}，置信度分{payload['confidence_score']}。"
        f"本地东方财富日线显示，市场上涨家数占比{payload['market']['up_ratio']:.0%}，"
        f"成交额为近20日均值的{payload['market']['turnover_ratio_20d']:.2f}倍。"
        f"排名第一为{top['theme_name']}，主线分{top['theme_score']}，状态为{top['status']}。"
        f"高风险方向包括：{format_names(high_risk)}。"
        f"升温方向包括：{format_names(warming)}。"
        f"次日验证重点：{'; '.join(top['next_checks'][:3])}。"
        "本系统仅用于复盘研究，不构成投资建议。"
    )
    return {
        "date": payload["date"],
        "confidence": payload["confidence"],
        "confidence_score": payload["confidence_score"],
        "top_themes": items[:5],
        "high_risk_themes": high_risk,
        "warming_themes": warming,
        "report": text,
    }


def format_names(items: list[dict[str, Any]]) -> str:
    return "、".join(item["theme_name"] for item in items[:5]) if items else "暂无"


def portfolio_risk(date: str) -> dict[str, Any]:
    themes, _market = build_themes_for_date(date)
    stock_to_theme = {}
    for theme in themes:
        for sector in theme["sectors"]:
            pass
        for stock in theme.get("stock_metrics", []):
            stock_to_theme[stock["symbol"]] = theme

    def enrich(row: dict[str, Any]) -> dict[str, Any]:
        theme = stock_to_theme.get(row["symbol"])
        if not theme:
            return {**row, "theme_name": None, "risk_level": "unknown", "risk_note": "未匹配到当前主线成分"}
        risk_level = "high" if theme["risk_penalty"] >= 9 else "medium" if theme["risk_penalty"] >= 5 else "low"
        return {
            **row,
            "theme_id": theme["theme_id"],
            "theme_name": theme["theme_name"],
            "theme_score": theme["theme_score"],
            "theme_status": theme["status"],
            "risk_penalty": theme["risk_penalty"],
            "risk_level": risk_level,
            "risk_note": f"暴露于{theme['status']}，风险扣分{theme['risk_penalty']}",
        }

    source_watchlist = list_watchlist() if list_watchlist else WATCHLIST
    enriched_watchlist = [enrich(row) for row in source_watchlist]
    source_positions = list_positions(PORTFOLIO) if list_positions else PORTFOLIO
    enriched_portfolio = [enrich(row) for row in source_positions]
    return {
        "date": date,
        "watchlist": enriched_watchlist,
        "portfolio": enriched_portfolio,
        "summary": {
            "watchlist_high_risk_count": sum(1 for row in enriched_watchlist if row["risk_level"] == "high"),
            "portfolio_high_risk_count": sum(1 for row in enriched_portfolio if row["risk_level"] == "high"),
        },
    }


def backtest_result(body: dict[str, Any]) -> dict[str, Any]:
    start_date = int(str(body.get("start_date", "20210101")).replace("-", ""))
    end_date = int(str(body.get("end_date", "20991231")).replace("-", ""))
    holding_period = max(1, int(body.get("holding_period", 3)))
    top_n = max(1, int(body.get("top_n", 5)))

    with sqlite3.connect(DB_PATH) as conn:
        dates = [
            row[0]
            for row in conn.execute(
                """
                select distinct trade_date
                from em_daily_quote
                where trade_date between ? and ?
                order by trade_date
                """,
                (start_date, end_date),
            )
        ]
        if len(dates) <= holding_period:
            return {
                "task_id": "local_sqlite_backtest",
                "status": "insufficient_data",
                "request": body,
                "metrics": {},
                "note": "可用交易日数量不足，无法完成指定持有周期回测。",
            }

        samples = []
        all_rank_scores: list[float] = []
        all_future_returns: list[float] = []
        equity = 1.0
        equity_curve = []
        for idx, trade_date in enumerate(dates[:-holding_period]):
            exit_date = dates[idx + holding_period]
            themes, _market = build_themes_for_date(date_text(trade_date))
            theme_returns = []
            for theme in themes:
                symbols = sorted({stock["symbol"] for stock in theme.get("stock_metrics", [])})
                future_return = future_theme_return(conn, symbols, trade_date, exit_date)
                if future_return is None:
                    continue
                theme_returns.append((theme, future_return))
                all_rank_scores.append(theme["theme_score"])
                all_future_returns.append(future_return)

            if not theme_returns:
                continue
            ranked = sorted(theme_returns, key=lambda pair: pair[0]["theme_score"], reverse=True)
            selected = ranked[:top_n]
            selected_return = safe_mean([ret for _theme, ret in selected])
            benchmark_return = safe_mean([ret for _theme, ret in theme_returns])
            excess_return = selected_return - benchmark_return
            equity *= 1 + selected_return
            equity_curve.append(equity)
            samples.append({
                "trade_date": date_text(trade_date),
                "exit_date": date_text(exit_date),
                "selected_return": selected_return,
                "benchmark_return": benchmark_return,
                "excess_return": excess_return,
                "selected_themes": [theme["theme_name"] for theme, _ret in selected],
            })

    returns = [sample["selected_return"] for sample in samples]
    excess_returns = [sample["excess_return"] for sample in samples]
    metrics = {
        "sample_count": len(samples),
        "start_date": date_text(dates[0]),
        "end_date": date_text(dates[-1]),
        "holding_period": holding_period,
        "top_n": top_n,
        "avg_return": round(safe_mean(returns) * 100, 3),
        "avg_excess_return": round(safe_mean(excess_returns) * 100, 3),
        "win_rate": round(sum(1 for ret in returns if ret > 0) / len(returns), 4) if returns else None,
        "excess_win_rate": round(sum(1 for ret in excess_returns if ret > 0) / len(excess_returns), 4) if excess_returns else None,
        "max_drawdown": round(max_drawdown(equity_curve) * 100, 3),
        "rank_ic": round(pearson(all_rank_scores, all_future_returns), 4) if len(all_rank_scores) >= 3 else None,
    }
    return {
        "task_id": "local_sqlite_backtest",
        "status": "completed",
        "request": body,
        "metrics": metrics,
        "samples": samples[-20:],
        "note": "回测基于当前 SQLite 可用日线区间逐日重放；不会使用评分日之后的数据计算当日排名。",
    }


def future_theme_return(conn: sqlite3.Connection, symbols: list[str], entry_date: int, exit_date: int) -> float | None:
    returns = []
    for symbol in symbols:
        row = conn.execute(
            """
            select e.close, x.close
            from em_daily_quote e
            join em_daily_quote x on x.symbol = e.symbol
            where e.symbol = ? and e.trade_date = ? and x.trade_date = ?
            """,
            (symbol, entry_date, exit_date),
        ).fetchone()
        if row and row[0] and row[1]:
            returns.append(row[1] / row[0] - 1)
    return safe_mean(returns) if returns else None


def max_drawdown(equity_curve: list[float]) -> float:
    peak = 1.0
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak:
            max_dd = min(max_dd, value / peak - 1)
    return max_dd


def pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx = mean(xs)
    my = mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)
