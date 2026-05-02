"""主线阶段有限状态机 — 状态存储与迁移验证。

阶段枚举：启动、加速、高潮、分歧、退潮、修复。
迁移规则按设计文档 R-P2.5 定义，不允许自由文本作为主阶段。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

# ── 固定阶段枚举 ──────────────────────────────────────────────
STAGE_STARTUP = "启动"
STAGE_ACCELERATE = "加速"
STAGE_CLIMAX = "高潮"
STAGE_DIVERGE = "分歧"
STAGE_EBB = "退潮"
STAGE_REPAIR = "修复"

ALL_STAGES = (STAGE_STARTUP, STAGE_ACCELERATE, STAGE_CLIMAX,
              STAGE_DIVERGE, STAGE_EBB, STAGE_REPAIR)

# 合法迁移表：from_stage → set(to_stage)
VALID_TRANSITIONS: dict[str, set[str]] = {
    STAGE_STARTUP:    {STAGE_ACCELERATE, STAGE_DIVERGE, STAGE_EBB},
    STAGE_ACCELERATE: {STAGE_CLIMAX, STAGE_DIVERGE, STAGE_EBB},
    STAGE_CLIMAX:     {STAGE_DIVERGE, STAGE_EBB},
    STAGE_DIVERGE:    {STAGE_REPAIR, STAGE_EBB, STAGE_ACCELERATE},
    STAGE_EBB:        {STAGE_REPAIR, STAGE_STARTUP},
    STAGE_REPAIR:     {STAGE_ACCELERATE, STAGE_DIVERGE, STAGE_EBB},
}

# 阶段排序权重（用于显示排序）
STAGE_ORDER = {
    STAGE_CLIMAX: 0,
    STAGE_ACCELERATE: 1,
    STAGE_STARTUP: 2,
    STAGE_DIVERGE: 3,
    STAGE_REPAIR: 4,
    STAGE_EBB: 5,
}


# ── DDL ──────────────────────────────────────────────────────
DDL = """
CREATE TABLE IF NOT EXISTS theme_stage_state_daily (
    trade_date   TEXT NOT NULL,
    theme_id     TEXT NOT NULL,
    stage        TEXT NOT NULL,
    previous_stage TEXT,
    stage_reason TEXT,
    transition_signals TEXT,
    stage_confidence REAL DEFAULT 0.5,
    model_version TEXT,
    created_at   TEXT,
    PRIMARY KEY (trade_date, theme_id)
);
"""


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


# ── 迁移验证 ──────────────────────────────────────────────────
def is_valid_transition(from_stage: str | None, to_stage: str) -> bool:
    """验证迁移是否合法。首次（from_stage 为空）任何阶段都合法。"""
    if from_stage is None or from_stage == "":
        return to_stage in ALL_STAGES
    if from_stage == to_stage:
        return True  # 保持当前阶段
    return to_stage in VALID_TRANSITIONS.get(from_stage, set())


def get_valid_next_stages(current_stage: str | None) -> list[str]:
    """返回当前阶段可迁移到的合法阶段列表。"""
    if current_stage is None or current_stage == "":
        return list(ALL_STAGES)
    allowed = VALID_TRANSITIONS.get(current_stage, set())
    return sorted(allowed, key=lambda s: STAGE_ORDER.get(s, 99))


# ── 读写 ──────────────────────────────────────────────────────
def load_stage(conn: sqlite3.Connection, trade_date: str, theme_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT trade_date, theme_id, stage, previous_stage, stage_reason, "
        "transition_signals, stage_confidence, model_version, created_at "
        "FROM theme_stage_state_daily WHERE trade_date = ? AND theme_id = ?",
        (trade_date, theme_id),
    ).fetchone()
    if not row:
        return None
    return {
        "trade_date": row[0],
        "theme_id": row[1],
        "stage": row[2],
        "previous_stage": row[3],
        "stage_reason": row[4],
        "transition_signals": json.loads(row[5]) if row[5] else [],
        "stage_confidence": row[6],
        "model_version": row[7],
        "created_at": row[8],
    }


def load_previous_stage(conn: sqlite3.Connection, trade_date: str, theme_id: str) -> str | None:
    """查找给定交易日之前最近一次的阶段状态。"""
    row = conn.execute(
        "SELECT stage FROM theme_stage_state_daily "
        "WHERE theme_id = ? AND trade_date < ? ORDER BY trade_date DESC LIMIT 1",
        (theme_id, trade_date),
    ).fetchone()
    return row[0] if row else None


def save_stage(conn: sqlite3.Connection, trade_date: str, theme_id: str,
               stage: str, previous_stage: str | None,
               reason: str, signals: list[str],
               confidence: float, model_version: str) -> None:
    """保存阶段状态，强制校验迁移合法性。"""
    if stage not in ALL_STAGES:
        raise ValueError(f"非法阶段枚举值: {stage}，允许值: {ALL_STAGES}")
    if not is_valid_transition(previous_stage, stage):
        raise ValueError(f"非法迁移: {previous_stage} -> {stage}")
    conn.execute(
        "INSERT OR REPLACE INTO theme_stage_state_daily "
        "(trade_date, theme_id, stage, previous_stage, stage_reason, "
        "transition_signals, stage_confidence, model_version, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (trade_date, theme_id, stage, previous_stage, reason,
         json.dumps(signals, ensure_ascii=False), confidence, model_version,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )


def load_stage_history(conn: sqlite3.Connection, theme_id: str,
                       end_date: str, days: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT trade_date, stage, previous_stage, stage_reason, "
        "transition_signals, stage_confidence "
        "FROM theme_stage_state_daily "
        "WHERE theme_id = ? AND trade_date <= ? ORDER BY trade_date DESC LIMIT ?",
        (theme_id, end_date, days),
    ).fetchall()
    return [
        {
            "date": r[0], "stage": r[1], "previous_stage": r[2],
            "reason": r[3],
            "signals": json.loads(r[4]) if r[4] else [],
            "confidence": r[5],
        }
        for r in rows
    ]
