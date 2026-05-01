"""自动聚合结果版本化存储（SRS FR-005, G-005）。

记录每日板块聚类结果，包含聚类名称、包含底层板块、核心股、生成原因和生效日期。
同日重复执行时自增版本号。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists local_auto_theme_cluster (
          id integer primary key autoincrement,
          cluster_date text not null,
          cluster_version integer not null default 1,
          cluster_name text not null,
          sector_codes text not null,
          sector_names text,
          core_stocks text,
          generation_reason text,
          status text not null default 'active',
          created_at text not null
        )
        """
    )
    conn.execute(
        """
        create unique index if not exists udx_cluster_date_ver_name
        on local_auto_theme_cluster(cluster_date, cluster_version, cluster_name)
        """
    )


def save_clusters(
    conn: sqlite3.Connection,
    cluster_date: str,
    clusters: list[dict[str, Any]],
) -> int:
    """保存当日聚合结果。同日重复执行时自增版本号。

    clusters 列表每项包含：
      - cluster_name: str
      - sector_codes: list[str]
      - sector_names: list[str]（可选）
      - core_stocks: list[str]（可选）
      - generation_reason: str（可选）

    返回保存的版本号。
    """
    init_schema(conn)

    # 查询当日最大版本号
    row = conn.execute(
        "select max(cluster_version) from local_auto_theme_cluster where cluster_date = ?",
        (cluster_date,),
    ).fetchone()
    version = (row[0] or 0) + 1

    now = datetime.now().isoformat(timespec="seconds")
    for c in clusters:
        conn.execute(
            """
            insert into local_auto_theme_cluster
              (cluster_date, cluster_version, cluster_name, sector_codes, sector_names,
               core_stocks, generation_reason, status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                cluster_date,
                version,
                c["cluster_name"],
                json.dumps(c["sector_codes"], ensure_ascii=False),
                json.dumps(c.get("sector_names", []), ensure_ascii=False),
                json.dumps(c.get("core_stocks", []), ensure_ascii=False),
                c.get("generation_reason", ""),
                now,
            ),
        )
    conn.commit()
    return version


def load_clusters(
    conn: sqlite3.Connection,
    cluster_date: str,
    version: int | None = None,
) -> list[dict[str, Any]]:
    """加载指定日期的聚合结果。version 为 None 时取最新版本。"""
    init_schema(conn)

    if version is None:
        row = conn.execute(
            "select max(cluster_version) from local_auto_theme_cluster where cluster_date = ?",
            (cluster_date,),
        ).fetchone()
        if not row or row[0] is None:
            return []
        version = row[0]

    rows = conn.execute(
        """
        select id, cluster_date, cluster_version, cluster_name, sector_codes,
               sector_names, core_stocks, generation_reason, status, created_at
        from local_auto_theme_cluster
        where cluster_date = ? and cluster_version = ? and status = 'active'
        order by id
        """,
        (cluster_date, version),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_cluster_dates(conn: sqlite3.Connection, limit: int = 30) -> list[dict[str, Any]]:
    """列出有聚合记录的日期及其版本号。"""
    init_schema(conn)
    rows = conn.execute(
        """
        select cluster_date, max(cluster_version) as max_ver, count(*) as cluster_count
        from local_auto_theme_cluster
        where status = 'active'
        group by cluster_date
        order by cluster_date desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [
        {"cluster_date": r[0], "max_version": r[1], "cluster_count": r[2]}
        for r in rows
    ]


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "cluster_date": row[1],
        "cluster_version": row[2],
        "cluster_name": row[3],
        "sector_codes": json.loads(row[4]) if row[4] else [],
        "sector_names": json.loads(row[5]) if row[5] else [],
        "core_stocks": json.loads(row[6]) if row[6] else [],
        "generation_reason": row[7],
        "status": row[8],
        "created_at": row[9],
    }
