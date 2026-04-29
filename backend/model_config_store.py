from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"

DEFAULT_CONFIG = {
    "model_version": "v1.0-local",
    "config_version": "default",
    "heat_weight": 0.4,
    "continuation_weight": 0.6,
    "risk_cap": 20,
}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists local_model_config (
          id integer primary key autoincrement,
          model_version text not null,
          config_version text not null,
          config_json text not null,
          is_active integer not null default 0,
          created_at text not null,
          unique(model_version, config_version)
        );
        """
    )


def get_active_config() -> dict[str, Any]:
    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        row = conn.execute(
            """
            select config_json
            from local_model_config
            where is_active = 1
            order by id desc
            limit 1
            """
        ).fetchone()
        if not row:
            save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()
        return json.loads(row[0])


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    clean = DEFAULT_CONFIG.copy()
    clean.update(config)
    clean["heat_weight"] = float(clean["heat_weight"])
    clean["continuation_weight"] = float(clean["continuation_weight"])
    clean["risk_cap"] = float(clean["risk_cap"])
    total = clean["heat_weight"] + clean["continuation_weight"]
    if total <= 0:
        raise ValueError("热度权重和延续性权重之和必须大于0")
    clean["heat_weight"] = round(clean["heat_weight"] / total, 4)
    clean["continuation_weight"] = round(clean["continuation_weight"] / total, 4)
    clean["risk_cap"] = max(0, min(50, clean["risk_cap"]))
    clean["created_at"] = datetime.now().isoformat(timespec="seconds")

    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        conn.execute("update local_model_config set is_active = 0")
        conn.execute(
            """
            insert into local_model_config(model_version, config_version, config_json, is_active, created_at)
            values (?, ?, ?, 1, ?)
            on conflict(model_version, config_version) do update set
              config_json = excluded.config_json,
              is_active = 1,
              created_at = excluded.created_at
            """,
            (
                clean["model_version"],
                clean["config_version"],
                json.dumps(clean, ensure_ascii=False),
                clean["created_at"],
            ),
        )
        conn.commit()
    return clean


def list_configs() -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        init_schema(conn)
        rows = conn.execute(
            """
            select model_version, config_version, config_json, is_active, created_at
            from local_model_config
            order by id desc
            """
        ).fetchall()
    return [
        {
            "model_version": row[0],
            "config_version": row[1],
            "config": json.loads(row[2]),
            "is_active": bool(row[3]),
            "created_at": row[4],
        }
        for row in rows
    ]

