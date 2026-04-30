from __future__ import annotations

import math
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

from theme_universe import CATEGORY_LABELS, PORTFOLIO, THEME_SECTORS, WATCHLIST
from model_config_store import get_active_config, save_config

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

# 无真实舆情数据时需要排除的因子
_SENTIMENT_FACTORS = {"舆情边际变化率", "舆情绝对热度", "舆情边际变化"}


def effective_weights(base: dict[str, int], exclude: set[str] | None = None) -> dict[str, float]:
    """当排除部分因子时，将排除因子的权重按比例分配给剩余因子。"""
    exclude = exclude or set()
    remaining = {k: v for k, v in base.items() if k not in exclude}
    excluded_total = sum(v for k, v in base.items() if k in exclude)
    remaining_total = sum(remaining.values())
    if not excluded_total or not remaining_total:
        return {k: float(v) for k, v in base.items()}
    scale = (remaining_total + excluded_total) / remaining_total
    return {k: round(v * scale, 4) for k, v in remaining.items()}


def _apply_dynamic(weights: dict[str, float], dynamic: dict[str, float]) -> dict[str, float]:
    """SRS 10.1/10.4: 将动态权重应用到有效权重上。

    公式：final = 0.85 * base + 0.15 * dynamic
    约束：单因子最大调整不超过基础权重 25%。
    """
    result = {}
    for name, base_w in weights.items():
        dyn_w = dynamic.get(name, base_w)
        # 约束：动态权重在基础权重的 ±25% 范围内
        dyn_w = max(base_w * 0.75, min(base_w * 1.25, dyn_w))
        result[name] = round(0.85 * base_w + 0.15 * dyn_w, 4)
    return result


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
    signal_map = load_limit_signals(conn, symbols, date_text(trade_date))
    for item in metrics:
        signal = signal_map.get(item["symbol"])
        if signal:
            item["limit_up"] = bool(signal["sealed_limit"])
            item["touched_limit"] = bool(signal["touched_limit"])
            item["limit_break"] = bool(signal["limit_break"])
            item["consecutive_boards"] = signal["consecutive_boards"]

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

    # SRS 9.6 资金接力断裂指标
    prev_pcts = load_prev_day_pcts(conn, symbols, trade_date)
    relay_metrics = compute_relay_break(metrics, prev_pcts, median_pct)

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

    # 炸板率：触板股中未封板的比例（SRS 9.2）
    touched_count = sum(1 for item in metrics if item.get("touched_limit"))
    break_count = sum(1 for item in metrics if item.get("limit_break"))
    break_rate = break_count / touched_count if touched_count > 0 else 0

    # 最高连板高度
    max_consecutive = max((item.get("consecutive_boards", 0) for item in metrics), default=0)

    risks: dict[str, float] = {}
    if avg_pct5 > 0.18 and amount_ratio > 1.8:
        risks["板块连续高潮"] = min(4.0, 1.5 + avg_pct5 * 10)
    # SRS 8.4 炸板率过高：触板股>=2 且炸板率>40% 时扣分
    if touched_count >= 2 and break_rate > 0.4:
        risks["炸板率过高"] = min(4.0, 1.0 + (break_rate - 0.4) * 8 + min(touched_count, 5) * 0.3)
    if close_pos < 0.35 and amount_ratio > 1.3:
        risks["高位放量滞涨"] = min(4.0, 1.0 + (1.4 - close_pos) * 2)
    if core_avg < tail_avg - 0.015:
        risks["核心股走弱"] = min(5.0, 2.0 + (tail_avg - core_avg) * 70)
    # SRS 9.6 资金接力断裂：综合领涨延续率、涨停重合率、核心股偏离度
    relay = relay_metrics
    relay_penalty = 0.0
    if relay["lead_continue_rate"] is not None and relay["lead_continue_rate"] < 0.4:
        relay_penalty += 1.0 + (0.4 - relay["lead_continue_rate"]) * 5
    if relay["limit_overlap_rate"] is not None and relay["limit_overlap_rate"] < 0.15 and limit_count >= 2:
        relay_penalty += 1.0 + (0.15 - relay["limit_overlap_rate"]) * 7
    if relay["core_deviation"] is not None and relay["core_deviation"] > 0.02:
        relay_penalty += 2.0 + relay["core_deviation"] * 50
    if relay_penalty > 0:
        risks["资金接力断裂"] = min(5.0, relay_penalty)
    if up_ratio < 0.35 and avg_pct > 0:
        risks["后排不跟/广度不足"] = min(3.0, 1.0 + (0.35 - up_ratio) * 5)
    if amount_ratio > 2.2 and avg_pct < 0.01:
        risks["舆情/成交过热"] = min(3.0, 1.0 + (amount_ratio - 2.2))
    # SRS 8.4 监管/异动风险：板块内出现极端波动信号
    extreme_count = sum(
        1 for item in metrics
        if abs(item["pct1"]) > 0.08
        and item.get("limit_up") or item.get("limit_break")
    )
    if extreme_count >= 3 or (extreme_count >= 2 and max_consecutive >= 5):
        risks["监管/异动风险"] = min(3.0, 0.5 + extreme_count * 0.5 + min(max_consecutive, 8) * 0.15)

    # 无真实舆情数据时排除占位因子，将权重按比例分配给其他因子
    heat_w = effective_weights(HEAT_WEIGHTS, _SENTIMENT_FACTORS)
    cont_w = effective_weights(CONTINUATION_WEIGHTS, _SENTIMENT_FACTORS)

    # SRS 10.1: 应用动态因子权重（如果有）
    config = get_active_config()
    dyn = config.get("dynamic_factor_weights", {})
    if dyn:
        heat_w = _apply_dynamic(heat_w, dyn)
        cont_w = _apply_dynamic(cont_w, dyn)

    heat = weighted_score(heat_factors, heat_w)
    continuation = weighted_score(continuation_factors, cont_w)
    risk = min(float(config["risk_cap"]), sum(risks.values()))
    composite = round(config["heat_weight"] * heat + config["continuation_weight"] * continuation - risk, 2)
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
                "touched_limit": item.get("touched_limit", False),
                "consecutive_boards": item.get("consecutive_boards", 0),
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
            "touched_count": touched_count,
            "break_count": break_count,
            "break_rate": round(break_rate, 4),
            "max_consecutive_boards": max_consecutive,
            "close_position": round(close_pos, 3),
            "relay_break": {
                "lead_continue_rate": round(relay_metrics["lead_continue_rate"], 4) if relay_metrics["lead_continue_rate"] is not None else None,
                "limit_overlap_rate": round(relay_metrics["limit_overlap_rate"], 4) if relay_metrics["limit_overlap_rate"] is not None else None,
                "core_deviation": round(relay_metrics["core_deviation"] * 100, 2) if relay_metrics["core_deviation"] is not None else None,
            },
        },
    }
    return SectorScore(raw, heat, continuation, round(risk, 2), composite)


def compute_relay_break(
    metrics: list[dict[str, Any]],
    prev_pcts: dict[str, float],
    today_median_pct: float,
) -> dict[str, float | None]:
    """计算 SRS 9.6 资金接力断裂三项指标。

    - 领涨延续率: 昨日涨幅前 N 股中今日继续跑赢板块中位数的比例
    - 涨停重合率: 今日涨停股中昨日涨幅也强势的比例
    - 核心股偏离度: 板块中位数涨幅 - 核心股平均涨幅（正值=核心弱于后排）
    """
    # 领涨延续率
    lead_continue_rate: float | None = None
    if prev_pcts:
        sorted_prev = sorted(prev_pcts.items(), key=lambda pair: pair[1], reverse=True)
        leaders = sorted_prev[: max(3, len(sorted_prev) // 3)]
        if leaders:
            continued = sum(
                1 for symbol, _ in leaders
                if any(m["symbol"] == symbol and m["pct1"] > today_median_pct for m in metrics)
            )
            lead_continue_rate = continued / len(leaders)

    # 涨停重合率
    limit_overlap_rate: float | None = None
    today_limit_symbols = {m["symbol"] for m in metrics if m.get("limit_up")}
    if today_limit_symbols and prev_pcts:
        strong_threshold = 0.05
        overlap = sum(
            1 for s in today_limit_symbols
            if prev_pcts.get(s, 0) >= strong_threshold
        )
        limit_overlap_rate = overlap / len(today_limit_symbols)

    # 核心股偏离度: 中位数涨幅 - 核心股平均涨幅
    core_deviation: float | None = None
    if len(metrics) >= 4:
        sorted_by_amount = sorted(metrics, key=lambda m: m["amount"], reverse=True)
        core_symbols = {m["symbol"] for m in sorted_by_amount[:3]}
        core_avg = safe_mean([m["pct1"] for m in metrics if m["symbol"] in core_symbols], today_median_pct)
        core_deviation = today_median_pct - core_avg

    return {
        "lead_continue_rate": lead_continue_rate,
        "limit_overlap_rate": limit_overlap_rate,
        "core_deviation": core_deviation,
    }


def prev_trade_date(conn: sqlite3.Connection, trade_date: int) -> int | None:
    row = conn.execute(
        "select max(trade_date) from em_daily_quote where trade_date < ?",
        (trade_date,),
    ).fetchone()
    return int(row[0]) if row and row[0] else None


def load_prev_day_pcts(conn: sqlite3.Connection, symbols: list[str], trade_date: int) -> dict[str, float]:
    """加载前一交易日个股涨跌幅，用于资金接力断裂计算。"""
    prev_td = prev_trade_date(conn, trade_date)
    if not prev_td or not symbols:
        return {}
    prev_prev_td = prev_trade_date(conn, prev_td)
    if not prev_prev_td:
        return {}
    placeholders = ",".join("?" for _ in symbols)
    rows = conn.execute(
        f"""
        select q.symbol, (q.close - p.close) / p.close
        from em_daily_quote q
        join em_daily_quote p on p.symbol = q.symbol
        where q.trade_date = ? and p.trade_date = ?
          and q.close > 0 and p.close > 0
          and q.symbol in ({placeholders})
        """,
        [prev_td, prev_prev_td, *symbols],
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def load_limit_signals(conn: sqlite3.Connection, symbols: list[str], trade_date: str) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    placeholders = ",".join("?" for _ in symbols)
    try:
        rows = conn.execute(
            f"""
            select symbol, touched_limit, sealed_limit, limit_break, consecutive_boards
            from local_limit_signal_daily
            where trade_date = ? and symbol in ({placeholders})
            """,
            [trade_date, *symbols],
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {
        row[0]: {
            "touched_limit": bool(row[1]),
            "sealed_limit": bool(row[2]),
            "limit_break": bool(row[3]),
            "consecutive_boards": row[4],
        }
        for row in rows
    }


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
    # 使用有效权重（已排除舆情占位因子）
    heat_w = effective_weights(HEAT_WEIGHTS, _SENTIMENT_FACTORS)
    cont_w = effective_weights(CONTINUATION_WEIGHTS, _SENTIMENT_FACTORS)
    for item in cluster:
        for key in heat_w:
            heat[key] += item.raw["factors"].get(key, 50)
        for key in cont_w:
            continuation[key] += item.raw["factors"].get(key, 50)
        for key, value in item.raw.get("risks", {}).items():
            risk[key] += value
    return {
        "heat": [{"name": key, "score": round(value / count, 2), "weight": heat_w[key]} for key, value in heat.items()],
        "continuation": [{"name": key, "score": round(value / count, 2), "weight": cont_w[key]} for key, value in continuation.items()],
        "risk": [{"name": key, "penalty": round(value, 2)} for key, value in sorted(risk.items(), key=lambda pair: pair[1], reverse=True)],
    }


def load_real_sectors(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """从 SQLite 加载东方财富真实板块成分，格式与 THEME_SECTORS 兼容。

    优先使用 local_theme + local_theme_sector_mapping 定义的主线-板块映射；
    若无映射，则直接使用 em_sector 中成分>=5 的板块。
    """
    # 检查是否有主线映射
    theme_rows = conn.execute(
        "select theme_id, theme_name, category from local_theme where status = 'active'"
    ).fetchall()

    if theme_rows:
        sectors: list[dict[str, Any]] = []
        for theme_id, theme_name, category in theme_rows:
            mappings = conn.execute(
                """
                select m.sector_id, m.branch,
                       coalesce(s.sector_name, m.sector_id)
                from local_theme_sector_mapping m
                left join em_sector s on s.sector_code = m.sector_id
                where m.theme_id = ?
                order by m.sort_order
                """,
                (theme_id,),
            ).fetchall()
            for sector_code, branch, sector_name in mappings:
                stocks = conn.execute(
                    """
                    select c.symbol, coalesce(s.name, c.symbol)
                    from em_sector_constituent_history c
                    left join em_stock s on s.symbol = c.symbol
                    where c.sector_code = ?
                    group by c.symbol
                    order by c.symbol
                    """,
                    (sector_code,),
                ).fetchall()
                if stocks:
                    sectors.append({
                        "sector_id": sector_code,
                        "sector_name": sector_name,
                        "branch": branch or sector_name,
                        "category": category,
                        "keywords": [theme_name, sector_name],
                        "stocks": [(r[0], r[1]) for r in stocks],
                        "catalysts": [],
                    })
        return sectors

    # 无主线映射时，使用 em_sector 中成分>=5 的板块按来源分组
    rows = conn.execute(
        """
        select s.sector_code, s.sector_name, s.source
        from em_sector s
        where (select count(*) from em_sector_constituent_history c where c.sector_code = s.sector_code) >= 5
        order by s.source, s.sector_name
        """
    ).fetchall()
    sectors = []
    for sector_code, sector_name, source in rows:
        stocks = conn.execute(
            """
            select c.symbol, coalesce(s.name, c.symbol)
            from em_sector_constituent_history c
            left join em_stock s on s.symbol = c.symbol
            where c.sector_code = ?
            group by c.symbol
            order by c.symbol
            """,
            (sector_code,),
        ).fetchall()
        if stocks:
            sectors.append({
                "sector_id": sector_code,
                "sector_name": sector_name,
                "branch": sector_name,
                "category": source,
                "keywords": [sector_name],
                "stocks": [(r[0], r[1]) for r in stocks],
                "catalysts": [],
            })
    return sectors


def build_themes_for_date(date: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        trade_date = resolve_trade_date(conn, date)
        market = build_market_snapshot(conn, trade_date)
        # 优先使用真实板块数据，回退到人工主题配置
        sector_list = load_real_sectors(conn)
        if not sector_list:
            sector_list = THEME_SECTORS
        scored = [score_sector_from_db(conn, sector, trade_date, market["market_amount"]) for sector in sector_list]
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
        config = get_active_config()
        risk = round(min(float(config["risk_cap"]), avg("risk_penalty")), 2)
        theme_score = round(config["heat_weight"] * heat + config["continuation_weight"] * continuation - risk, 2)
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
    return {"date": market["date"], "requested_date": date, "period": period, "market": market, "model_config": get_active_config(), **conf, "items": themes}


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


def confidence_history_payload(date: str, days: int = 20) -> dict[str, Any]:
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
    items = []
    for day in dates:
        themes, market = build_themes_for_date(day)
        conf = confidence(themes, market)
        items.append({
            "date": day,
            "confidence": conf["confidence"],
            "confidence_score": conf["confidence_score"],
            "components": conf["components"],
            "reason": conf["reason"],
            "top_theme": themes[0]["theme_name"] if themes else None,
            "top_theme_score": themes[0]["theme_score"] if themes else None,
        })
    return {
        "date": dates[-1] if dates else date,
        "days": len(dates),
        "items": items,
    }


def risk_history_payload(theme_id: str, date: str, days: int = 20) -> dict[str, Any]:
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
    items = []
    theme_name = None
    for day in dates:
        theme = find_theme(theme_id, day)
        if not theme:
            continue
        theme_name = theme_name or theme["theme_name"]
        items.append({
            "date": day,
            "theme_id": theme_id,
            "theme_name": theme["theme_name"],
            "theme_score": theme["theme_score"],
            "risk_penalty": theme["risk_penalty"],
            "status": theme["status"],
            "risks": theme["risks"],
        })
    return {
        "date": dates[-1] if dates else date,
        "theme_id": theme_id,
        "theme_name": theme_name,
        "days": len(items),
        "items": items,
    }


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


def rank_values(values: list[float]) -> list[float]:
    ordered = sorted((value, idx) for idx, value in enumerate(values))
    ranks = [0.0] * len(values)
    pos = 0
    while pos < len(ordered):
        end = pos + 1
        while end < len(ordered) and ordered[end][0] == ordered[pos][0]:
            end += 1
        rank = (pos + 1 + end) / 2
        for _value, idx in ordered[pos:end]:
            ranks[idx] = rank
        pos = end
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    return pearson(rank_values(xs), rank_values(ys))


def factor_effectiveness_payload(date: str, holding_period: int = 3) -> dict[str, Any]:
    holding_period = max(1, min(10, int(holding_period)))
    with sqlite3.connect(DB_PATH) as conn:
        target_date = resolve_trade_date(conn, date)
        dates = [
            row[0]
            for row in conn.execute(
                """
                select distinct trade_date
                from em_daily_quote
                where trade_date <= ?
                order by trade_date
                """,
                (target_date,),
            ).fetchall()
        ]
        target_idx = dates.index(target_date)
        entry_dates = [
            trade_date
            for idx, trade_date in enumerate(dates)
            if idx + holding_period <= target_idx
        ][-20:]
        if not entry_dates:
            return {
                "date": date_text(target_date),
                "holding_period": holding_period,
                "status": "insufficient_data",
                "items": [],
                "summary": "本地数据不足，暂不能计算因子有效性。",
            }

        factor_points: dict[str, list[dict[str, float]]] = defaultdict(list)
        date_to_index = {trade_date: idx for idx, trade_date in enumerate(dates)}
        for entry_date in entry_dates:
            exit_date = dates[date_to_index[entry_date] + holding_period]
            themes, _market = build_themes_for_date(date_text(entry_date))
            for theme in themes:
                symbols = sorted({stock["symbol"] for stock in theme.get("stock_metrics", [])})
                future_return = future_theme_return(conn, symbols, entry_date, exit_date)
                if future_return is None:
                    continue
                factor_points["主线分"].append({"score": float(theme["theme_score"]), "return": future_return})
                factor_points["热度分"].append({"score": float(theme["heat_score"]), "return": future_return})
                factor_points["延续性分"].append({"score": float(theme["continuation_score"]), "return": future_return})
                for row in theme.get("factor_contribution", {}).get("heat", []):
                    factor_points[row["name"]].append({"score": float(row["score"]), "return": future_return})
                for row in theme.get("factor_contribution", {}).get("continuation", []):
                    factor_points[row["name"]].append({"score": float(row["score"]), "return": future_return})

    def window_stats(points: list[dict[str, float]], window: int) -> dict[str, Any]:
        sliced = points[-window * max(1, len(THEME_SECTORS)):]
        scores = [point["score"] for point in sliced]
        returns = [point["return"] for point in sliced]
        return {
            "ic": round(pearson(scores, returns), 4) if len(scores) >= 3 else None,
            "rank_ic": round(spearman(scores, returns), 4) if len(scores) >= 3 else None,
            "sample_count": len(scores),
        }

    def state(ic: float | None, sample_count: int) -> str:
        if ic is None or sample_count < 12 or abs(ic) < 0.03:
            return "不显著"
        return "上升" if ic > 0 else "下降"

    def action(short_state: str, long_state: str) -> str:
        if short_state == "上升" and long_state == "上升":
            return "小幅上调"
        if short_state == "下降" and long_state == "下降":
            return "小幅下调"
        return "不调整"

    all_base_weights = {"主线分": None, "热度分": None, "延续性分": None, **HEAT_WEIGHTS, **CONTINUATION_WEIGHTS}
    rows = []
    for name in ["主线分", "热度分", "延续性分", *HEAT_WEIGHTS.keys(), *CONTINUATION_WEIGHTS.keys()]:
        points = factor_points.get(name, [])
        stats_5 = window_stats(points, 5)
        stats_20 = window_stats(points, 20)
        state_5 = state(stats_5["ic"], stats_5["sample_count"])
        state_20 = state(stats_20["ic"], stats_20["sample_count"])
        adjust = action(state_5, state_20)
        base_weight = all_base_weights.get(name)
        dynamic_weight = None
        final_weight = None
        if isinstance(base_weight, (int, float)):
            multiplier = 1.08 if adjust == "小幅上调" else 0.92 if adjust == "小幅下调" else 1.0
            dynamic_weight = round(max(base_weight * 0.75, min(base_weight * 1.25, base_weight * multiplier)), 2)
            final_weight = round(0.85 * base_weight + 0.15 * dynamic_weight, 2)
        rows.append({
            "factor": name,
            "base_weight": base_weight,
            "dynamic_weight": dynamic_weight,
            "final_weight": final_weight,
            "ic_5d": stats_5["ic"],
            "rank_ic_5d": stats_5["rank_ic"],
            "sample_count_5d": stats_5["sample_count"],
            "state_5d": state_5,
            "ic_20d": stats_20["ic"],
            "rank_ic_20d": stats_20["rank_ic"],
            "sample_count_20d": stats_20["sample_count"],
            "state_20d": state_20,
            "action": adjust,
        })

    rows.sort(key=lambda row: (row["action"] == "不调整", -(abs(row["ic_20d"] or 0))))

    # SRS 10.1: 将双窗口确认的动态权重写入模型配置
    dynamic_weights: dict[str, float] = {}
    for row in rows:
        if row["final_weight"] is not None and row["action"] != "不调整":
            dynamic_weights[row["factor"]] = row["final_weight"]
    if dynamic_weights:
        config = get_active_config()
        config["dynamic_factor_weights"] = dynamic_weights
        save_config(config)

    summary = (
        f"基于本地 SQLite 截至{date_text(target_date)}的可用交易日，按未来{holding_period}日主线成分平均收益计算因子 IC；"
        f"已将{len(dynamic_weights)}项动态权重建议写入模型配置。"
    )
    return {
        "date": date_text(target_date),
        "holding_period": holding_period,
        "status": "completed",
        "entry_dates": [date_text(item) for item in entry_dates],
        "summary": summary,
        "items": rows,
    }
