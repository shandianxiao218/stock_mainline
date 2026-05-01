from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"

LEVEL_SCORES = {"S": 9.0, "A": 7.0, "B": 4.0, "C": 1.0}

# 催化等级对应评分基础分（用于评分引擎）
GRADE_BASE_SCORES = {"S": 85, "A": 70, "B": 50, "C": 30}

# 衰减窗口（天数）
DECAY_WINDOW = 20


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists local_catalyst_event (
          id integer primary key autoincrement,
          trade_date text not null,
          theme_id text,
          theme_name text,
          title text not null,
          source text,
          level text not null,
          score real not null,
          note text,
          created_at text not null
        )
        """
    )


def list_catalysts(date: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(500, int(limit)))
    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        if date:
            rows = conn.execute(
                """
                select id, trade_date, theme_id, theme_name, title, source, level, score, note, created_at
                from local_catalyst_event
                where trade_date = ?
                order by id desc
                limit ?
                """,
                (date, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                select id, trade_date, theme_id, theme_name, title, source, level, score, note, created_at
                from local_catalyst_event
                order by id desc
                limit ?
                """,
                (limit,),
            ).fetchall()
    return [row_to_dict(row) for row in rows]


def add_catalyst(body: dict[str, Any]) -> dict[str, Any]:
    trade_date = str(body.get("trade_date") or body.get("date") or "").strip()
    title = str(body.get("title") or "").strip()
    level = str(body.get("level") or "C").upper().strip()
    if not trade_date:
        raise ValueError("交易日期不能为空")
    if not title:
        raise ValueError("催化标题不能为空")
    if level not in LEVEL_SCORES:
        raise ValueError("催化等级必须为 S/A/B/C")
    score = float(body.get("score") or LEVEL_SCORES[level])
    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        cur = conn.execute(
            """
            insert into local_catalyst_event(trade_date, theme_id, theme_name, title, source, level, score, note, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_date,
                body.get("theme_id"),
                body.get("theme_name"),
                title,
                body.get("source"),
                level,
                score,
                body.get("note"),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        row = conn.execute(
            """
            select id, trade_date, theme_id, theme_name, title, source, level, score, note, created_at
            from local_catalyst_event
            where id = ?
            """,
            (cur.lastrowid,),
        ).fetchone()
    return row_to_dict(row)


def row_to_dict(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "trade_date": row[1],
        "theme_id": row[2],
        "theme_name": row[3],
        "title": row[4],
        "source": row[5],
        "level": row[6],
        "score": row[7],
        "note": row[8],
        "created_at": row[9],
    }


def get_catalysts_for_scoring(
    conn: sqlite3.Connection,
    theme_name: str,
    trade_date: str,
    window_days: int = DECAY_WINDOW,
) -> list[dict[str, Any]]:
    """查询指定板块名称在评分窗口内的催化事件，按事件日期降序。

    theme_name 匹配 theme_name 字段或 title 字段中的关键词。
    """
    init_schema(conn)
    # 计算窗口起始日期（简单做字符串减法，仅适用于 YYYY-MM-DD）
    year, month, day = int(trade_date[:4]), int(trade_date[5:7]), int(trade_date[8:10])
    from datetime import timedelta
    start_dt = datetime(year, month, day) - timedelta(days=window_days * 2)
    start_date = start_dt.strftime("%Y-%m-%d")

    rows = conn.execute(
        """
        select id, trade_date, theme_id, theme_name, title, source, level, score, note, created_at
        from local_catalyst_event
        where trade_date <= ? and trade_date >= ?
          and (theme_name = ? or title like ?)
        order by trade_date desc
        limit 50
        """,
        (trade_date, start_date, theme_name, f"%{theme_name}%"),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def compute_catalyst_score(
    catalysts: list[dict[str, Any]],
    trade_date: str,
) -> tuple[float, float, list[dict[str, Any]]]:
    """计算催化强度分和催化持续性分。

    返回 (强度分, 持续性分, 解释列表)。
    强度分取窗口内最高有效催化分（等级基础分 × 衰减系数）。
    持续性分取近 5 日催化分的均值（无催化时为 0）。
    """
    if not catalysts:
        return 0.0, 0.0, []

    year, month, day = int(trade_date[:4]), int(trade_date[5:7]), int(trade_date[8:10])
    ref_dt = datetime(year, month, day)

    scored: list[dict[str, Any]] = []
    for c in catalysts:
        event_date = c["trade_date"]
        ey, em, ed = int(event_date[:4]), int(event_date[5:7]), int(event_date[8:10])
        event_dt = datetime(ey, em, ed)
        days_since = (ref_dt - event_dt).days
        if days_since < 0:
            continue
        base = GRADE_BASE_SCORES.get(c["level"], 30)
        decay = max(0.0, 1.0 - days_since / DECAY_WINDOW)
        effective = base * decay
        scored.append({
            "title": c["title"],
            "level": c["level"],
            "event_date": event_date,
            "days_since": days_since,
            "base_score": base,
            "decay": round(decay, 3),
            "effective_score": round(effective, 2),
        })

    if not scored:
        return 0.0, 0.0, []

    # 强度分：取最高有效分
    strength = max(s["effective_score"] for s in scored)

    # 持续性分：近 5 日内的催化分均值
    recent = [s["effective_score"] for s in scored if s["days_since"] <= 5]
    continuation = sum(recent) / len(recent) if recent else 0.0

    return round(strength, 2), round(continuation, 2), scored
