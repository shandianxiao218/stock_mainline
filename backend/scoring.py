from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from sample_data import MARKET_SNAPSHOT, PORTFOLIO, SECTORS, WATCHLIST


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

CATEGORY_LABELS = {
    "ai_compute": "AI硬件/算力基础设施",
    "resource_price": "资源涨价",
    "defensive_yield": "防御红利",
    "low_altitude": "低空经济",
}


@dataclass
class SectorScore:
    raw: dict[str, Any]
    heat_score: float
    continuation_score: float
    risk_penalty: float
    composite_score: float


def weighted_score(factors: dict[str, float], weights: dict[str, int]) -> float:
    total = sum(weights.values())
    score = sum(float(factors.get(name, 50)) * weight for name, weight in weights.items()) / total
    return round(score, 2)


def score_sector(sector: dict[str, Any]) -> SectorScore:
    heat = weighted_score(sector["factors"], HEAT_WEIGHTS)
    continuation = weighted_score(sector["factors"], CONTINUATION_WEIGHTS)
    risk = min(20.0, sum(float(v) for v in sector.get("risks", {}).values()))
    composite = 0.4 * heat + 0.6 * continuation - risk
    return SectorScore(sector, round(heat, 2), round(continuation, 2), round(risk, 2), round(composite, 2))


def similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_keywords = set(left["keywords"])
    right_keywords = set(right["keywords"])
    left_core = set(left["core_stocks"])
    right_core = set(right["core_stocks"])
    keyword_union = left_keywords | right_keywords
    core_union = left_core | right_core

    keyword_score = len(left_keywords & right_keywords) / len(keyword_union) if keyword_union else 0
    core_score = len(left_core & right_core) / len(core_union) if core_union else 0
    category_score = 1.0 if left["category"] == right["category"] else 0.0
    return 0.50 * category_score + 0.30 * keyword_score + 0.20 * core_score


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
            "reason": f"{'、'.join(reasons[risk_type])}触发{risk_type}信号"
        })
    return rows


def theme_status(score: float, heat: float, continuation: float, risk: float) -> str:
    if risk >= 10 and heat >= 82:
        return "高位分歧主线"
    if heat >= 80 and continuation >= 74 and risk < 8:
        return "新晋观察主线"
    if continuation >= 74 and heat < 75:
        return "防御延续主线"
    if risk >= 9:
        return "退潮风险主线"
    if score >= 65:
        return "活跃轮动主线"
    return "观察支线"


def build_themes() -> list[dict[str, Any]]:
    scored = [score_sector(sector) for sector in SECTORS]
    clusters = aggregate_sectors(scored)
    themes: list[dict[str, Any]] = []

    for idx, cluster in enumerate(clusters, start=1):
        cluster = sorted(cluster, key=lambda item: item.composite_score, reverse=True)
        categories = [item.raw["category"] for item in cluster]
        category = max(set(categories), key=categories.count)
        theme_name = CATEGORY_LABELS.get(category, cluster[0].raw["sector_name"])
        total_weight = sum(max(item.composite_score, 1) for item in cluster)

        def avg(attr: str) -> float:
            return sum(getattr(item, attr) * max(item.composite_score, 1) for item in cluster) / total_weight

        heat = round(avg("heat_score"), 2)
        continuation = round(avg("continuation_score"), 2)
        risk = round(min(20.0, avg("risk_penalty")), 2)
        theme_score = round(0.4 * heat + 0.6 * continuation - risk, 2)
        branch_names = [item.raw["branch"] for item in cluster]
        core_stocks = []
        for item in cluster:
            for stock in item.raw["core_stocks"]:
                if stock not in core_stocks:
                    core_stocks.append(stock)

        themes.append({
            "theme_id": f"theme_{category}_{idx}",
            "theme_name": theme_name,
            "theme_score": theme_score,
            "heat_score": heat,
            "continuation_score": continuation,
            "risk_penalty": risk,
            "status": theme_status(theme_score, heat, continuation, risk),
            "branches": branch_names,
            "core_stocks": core_stocks[:8],
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
                }
                for item in cluster
            ],
            "risks": risk_items(cluster),
            "catalysts": sorted({c for item in cluster for c in item.raw.get("catalysts", [])}),
            "next_checks": sorted({c for item in cluster for c in item.raw.get("next_checks", [])}),
            "factor_contribution": factor_contribution(cluster),
            "confidence": "medium_high" if theme_score >= 70 and risk < 12 else "medium" if theme_score >= 60 else "low",
        })

    themes.sort(key=lambda item: item["theme_score"], reverse=True)
    for rank, theme in enumerate(themes, start=1):
        theme["rank"] = rank
    return themes


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


def confidence(themes: list[dict[str, Any]]) -> dict[str, Any]:
    top = themes[:3]
    spread = top[0]["theme_score"] - top[2]["theme_score"] if len(top) >= 3 else 12
    liquidity = min(100, MARKET_SNAPSHOT["turnover_ratio_20d"] * 72)
    spread_score = min(100, 45 + spread * 4)
    avg_risk = sum(item["risk_penalty"] for item in themes[:10]) / max(1, min(10, len(themes)))
    risk_stability = max(20, 100 - avg_risk * 5)
    breadth = MARKET_SNAPSHOT["up_ratio"] * 100
    consistency = min(100, 50 + sum(len(item["sectors"]) for item in top) * 8)
    score = round(0.30 * liquidity + 0.25 * spread_score + 0.20 * risk_stability + 0.15 * breadth + 0.10 * consistency, 2)
    level = "high" if score >= 75 else "medium" if score >= 55 else "low"
    reason = (
        f"全市场成交额约为20日均值的{MARKET_SNAPSHOT['turnover_ratio_20d']:.2f}倍，"
        f"前三主线分差约{spread:.1f}分；头部风险均值{avg_risk:.1f}，"
        f"上涨家数占比{MARKET_SNAPSHOT['up_ratio']:.0%}。"
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
    themes = build_themes()
    conf = confidence(themes)
    return {
        "date": date,
        "period": period,
        "market": MARKET_SNAPSHOT,
        **conf,
        "items": themes,
    }


def find_theme(theme_id: str) -> dict[str, Any] | None:
    return next((theme for theme in build_themes() if theme["theme_id"] == theme_id), None)


def detail_payload(theme_id: str, date: str) -> dict[str, Any] | None:
    theme = find_theme(theme_id)
    if not theme:
        return None
    return {
        "date": date,
        **theme,
        "model_explanation": (
            f"{theme['theme_name']}由{'、'.join(theme['branches'])}自动聚合形成。"
            f"当前热度{theme['heat_score']}，延续性{theme['continuation_score']}，"
            f"风险扣分{theme['risk_penalty']}，状态判断为{theme['status']}。"
        ),
    }


def daily_report(date: str) -> dict[str, Any]:
    payload = ranking_payload(date)
    items = payload["items"]
    top = items[0]
    high_risk = [item for item in items if item["risk_penalty"] >= 8]
    warming = [item for item in items if "新晋" in item["status"] or item["heat_score"] >= 80]
    text = (
        f"{date} 复盘：今日模型置信度为{payload['confidence']}，置信度分{payload['confidence_score']}。"
        f"{payload['confidence'] != 'low' and '市场存在可识别主线' or '市场轮动较乱'}，"
        f"排名第一为{top['theme_name']}，主线分{top['theme_score']}，状态为{top['status']}。"
        f"需要重点跟踪的高风险方向包括：{format_names(high_risk)}。"
        f"升温方向包括：{format_names(warming)}。"
        f"次日验证重点：{'; '.join(top['next_checks'][:3])}。"
        "本系统仅用于复盘研究，不构成投资建议。"
    )
    return {
        "date": date,
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
    themes = build_themes()
    stock_to_theme = {}
    for theme in themes:
        for stock in theme["core_stocks"]:
            stock_to_theme[stock] = theme

    def enrich(row: dict[str, Any]) -> dict[str, Any]:
        theme = stock_to_theme.get(row["name"])
        if not theme:
            return {**row, "theme_name": None, "risk_level": "unknown", "risk_note": "未匹配到核心主线"}
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

    enriched_watchlist = [enrich(row) for row in WATCHLIST]
    enriched_portfolio = [enrich(row) for row in PORTFOLIO]
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
    return {
        "task_id": "demo_backtest_5y_v1",
        "status": "completed_demo",
        "request": body,
        "metrics": {
            "rank_ic": 0.083,
            "win_rate": 0.574,
            "avg_excess_return": 0.018,
            "max_drawdown": -0.126,
            "risk_penalty_effect": "风险扣分过滤后，Top5组合最大回撤在样例结果中下降约3.8个百分点。",
        },
        "note": "当前为接口联调用样例结果；真实5年逐日重放依赖Tushare历史快照入库后启用。",
    }

