"""舆情数据存储与行情代理评分（SRS 9.7）。

数据策略：
1. 优先从本地缓存读取真实舆情快照（如后续接入 Eastmoney 股吧 API）
2. 无真实数据时使用行情代理指标生成舆情评分：
   - 舆情绝对热度 ≈ 成交额分位数 + 涨停数 + 涨幅排名
   - 舆情边际变化率 ≈ 当日成交额 / 近 5 日均值 - 1
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"


def init_sentiment_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists local_sentiment_daily (
          trade_date text not null,
          sector_code text not null,
          source text not null default 'proxy',
          absolute_heat real not null,
          marginal_change real not null,
          volume_proxy real not null,
          limit_proxy real not null,
          pct_proxy real not null,
          raw_data text,
          saved_at text not null,
          primary key (trade_date, sector_code, source)
        );
        """
    )


def proxy_sentiment_scores(
    sector_code: str,
    amount: float,
    amount_ratio: float,
    limit_rate: float,
    avg_pct: float,
    market_amounts_5d: list[float] | None = None,
) -> dict[str, float]:
    """用行情代理指标生成舆情评分（0-100）。

    - absolute_heat: 综合成交额排名 + 涨停率 + 涨幅
    - marginal_change: 成交额相对均值的边际变化
    """
    # 绝对热度：基于成交额放大倍数 + 涨停率 + 涨幅
    volume_score = min(100, 30 + amount_ratio * 30) if amount_ratio > 0 else 30
    limit_score = min(100, limit_rate * 500)
    pct_score = min(100, max(0, 50 + avg_pct * 600))
    absolute_heat = 0.50 * volume_score + 0.30 * limit_score + 0.20 * pct_score

    # 边际变化率：成交额相对均值的变化
    marginal_change = (amount_ratio - 1) * 100  # 百分比

    return {
        "absolute_heat": round(min(100, max(0, absolute_heat)), 2),
        "marginal_change": round(marginal_change, 2),
        "volume_proxy": round(volume_score, 2),
        "limit_proxy": round(limit_score, 2),
        "pct_proxy": round(pct_score, 2),
    }


def load_sector_sentiment(conn: sqlite3.Connection, sector_code: str, trade_date: str) -> dict[str, Any] | None:
    """从 SQLite 读取舆情数据，优先真实数据，回退到代理数据。"""
    init_sentiment_schema(conn)
    row = conn.execute(
        """
        select source, absolute_heat, marginal_change, volume_proxy, limit_proxy, pct_proxy
        from local_sentiment_daily
        where sector_code = ? and trade_date = ?
        order by case when source = 'real' then 0 else 1 end
        limit 1
        """,
        (sector_code, trade_date),
    ).fetchone()
    if row:
        return {
            "source": row[0],
            "absolute_heat": row[1],
            "marginal_change": row[2],
            "volume_proxy": row[3],
            "limit_proxy": row[4],
            "pct_proxy": row[5],
        }
    return None


def save_sector_sentiment(
    conn: sqlite3.Connection,
    trade_date: str,
    sector_code: str,
    source: str,
    scores: dict[str, float],
) -> None:
    """保存舆情快照到 SQLite。"""
    from datetime import datetime
    init_sentiment_schema(conn)
    conn.execute(
        """
        insert into local_sentiment_daily(
          trade_date, sector_code, source, absolute_heat, marginal_change,
          volume_proxy, limit_proxy, pct_proxy, saved_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(trade_date, sector_code, source) do update set
          absolute_heat = excluded.absolute_heat,
          marginal_change = excluded.marginal_change,
          volume_proxy = excluded.volume_proxy,
          limit_proxy = excluded.limit_proxy,
          pct_proxy = excluded.pct_proxy,
          saved_at = excluded.saved_at
        """,
        (
            trade_date,
            sector_code,
            source,
            scores["absolute_heat"],
            scores["marginal_change"],
            scores["volume_proxy"],
            scores["limit_proxy"],
            scores["pct_proxy"],
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def is_overheated(absolute_heat: float, marginal_change: float, avg_pct: float, amount_ratio: float) -> bool:
    """SRS 9.7.3 舆情过热检测。

    触发条件（任一）：
    1. 绝对热度 > 85 且边际变化开始下降（过热后回落）
    2. 成交额放大但涨幅收窄（量价背离）
    """
    if absolute_heat > 85 and marginal_change < -5:
        return True
    if amount_ratio > 2.0 and abs(avg_pct) < 0.005:
        return True
    return False


def price_sentiment_divergence(
    absolute_heat: float,
    avg_pct: float,
    amount_ratio: float,
) -> bool:
    """舆情与价格/成交背离检测。

    触发条件：热度高但价格不涨（热度 > 70 且 涨幅 < 0.3%）。
    """
    return absolute_heat > 70 and abs(avg_pct) < 0.003 and amount_ratio > 1.5


def load_hot_rank_for_symbols(conn: sqlite3.Connection, symbols: list[str], trade_date: str) -> dict[str, int]:
    """从 ak_hot_rank_daily 查询成分股热度排名。返回 {symbol: hot_rank}。"""
    try:
        placeholders = ",".join("?" for _ in symbols)
        rows = conn.execute(
            f"""
            select symbol, hot_rank from ak_hot_rank_daily
            where trade_date = ? and symbol in ({placeholders})
            """,
            [trade_date, *symbols],
        ).fetchall()
        return {row[0]: row[1] for row in rows}
    except Exception:
        return {}


def compute_hot_rank_sentiment(symbols: list[str], hot_ranks: dict[str, int]) -> float:
    """根据成分股热度排名计算板块级热度分（0-100）。

    排名越靠前（数字越小）分数越高。前 10 名得 100 分，前 50 得 80 分，前 100 得 60 分。
    取板块内有排名成分股的平均分。
    """
    if not hot_ranks:
        return 0.0
    scores = []
    for rank in hot_ranks.values():
        if rank <= 10:
            scores.append(100)
        elif rank <= 30:
            scores.append(90)
        elif rank <= 50:
            scores.append(80)
        elif rank <= 100:
            scores.append(60)
        else:
            scores.append(40)
    return sum(scores) / len(scores)


def enhanced_sentiment_scores(
    sector_code: str,
    symbols: list[str],
    trade_date: str,
    amount: float,
    amount_ratio: float,
    limit_rate: float,
    avg_pct: float,
    conn: sqlite3.Connection | None = None,
) -> dict[str, float]:
    """增强版舆情评分：行情代理 + 热度排名 + 龙虎榜。"""
    base = proxy_sentiment_scores(sector_code, amount, amount_ratio, limit_rate, avg_pct)

    hot_boost = 0.0
    if conn is not None:
        hot_ranks = load_hot_rank_for_symbols(conn, symbols, trade_date)
        hot_score = compute_hot_rank_sentiment(symbols, hot_ranks)
        if hot_score > 0:
            # 热度排名加权：有数据时占 20% 权重
            hot_boost = (hot_score - base["absolute_heat"]) * 0.2

    if hot_boost != 0:
        base["absolute_heat"] = round(min(100, max(0, base["absolute_heat"] + hot_boost)), 2)
        base["hot_rank_source"] = "akshare"

    return base


def sentiment_history(
    conn: sqlite3.Connection,
    sector_codes: list[str],
    end_date: str,
    days: int = 20,
) -> list[dict[str, Any]]:
    """查询多个板块近 N 日的舆情评分序列。"""
    init_sentiment_schema(conn)
    if not sector_codes:
        return []
    placeholders = ",".join("?" for _ in sector_codes)
    rows = conn.execute(
        f"""
        select trade_date, sector_code, absolute_heat, marginal_change,
               volume_proxy, limit_proxy, pct_proxy
        from local_sentiment_daily
        where sector_code in ({placeholders})
          and trade_date <= ?
        order by trade_date desc
        limit ?
        """,
        (*sector_codes, end_date, days * len(sector_codes)),
    ).fetchall()
    return [
        {
            "date": r[0],
            "sector_code": r[1],
            "absolute_heat": r[2],
            "marginal_change": r[3],
            "volume_proxy": r[4],
            "limit_proxy": r[5],
            "pct_proxy": r[6],
        }
        for r in rows
    ]
