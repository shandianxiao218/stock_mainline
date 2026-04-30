"""主线定义持久化、版本管理和底层板块映射（SRS FR-003 / SRS 7.4）。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_theme_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists local_theme (
          theme_id text primary key,
          theme_name text not null,
          category text not null,
          status text not null default 'active',
          created_at text not null,
          updated_at text not null
        );

        create table if not exists local_theme_sector_mapping (
          theme_id text not null,
          sector_id text not null,
          branch text not null default '',
          sort_order int not null default 0,
          primary key (theme_id, sector_id)
        );

        create table if not exists local_theme_version (
          id integer primary key autoincrement,
          theme_id text not null,
          action text not null,
          detail text,
          operator text not null default 'system',
          created_at text not null
        );

        create table if not exists local_custom_sector (
          sector_id text primary key,
          sector_name text not null,
          category text not null default '',
          keywords text not null default '',
          created_at text not null,
          updated_at text not null
        );

        create table if not exists local_custom_sector_stock (
          sector_id text not null,
          symbol text not null,
          sort_order int not null default 0,
          primary key (sector_id, symbol)
        );
        """
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def list_themes(status: str | None = None) -> list[dict[str, Any]]:
    with _conn() as conn:
        init_theme_schema(conn)
        sql = """
            select t.theme_id, t.theme_name, t.category, t.status, t.created_at, t.updated_at,
                   count(m.sector_id) as sector_count
            from local_theme t
            left join local_theme_sector_mapping m on m.theme_id = t.theme_id
            where (? is null or t.status = ?)
            group by t.theme_id
            order by t.updated_at desc
        """
        rows = conn.execute(sql, (status, status)).fetchall()
    return [
        {
            "theme_id": r[0], "theme_name": r[1], "category": r[2],
            "status": r[3], "created_at": r[4], "updated_at": r[5],
            "sector_count": r[6],
        }
        for r in rows
    ]


def get_theme(theme_id: str) -> dict[str, Any] | None:
    with _conn() as conn:
        init_theme_schema(conn)
        row = conn.execute(
            "select theme_id, theme_name, category, status, created_at, updated_at from local_theme where theme_id = ?",
            (theme_id,),
        ).fetchone()
        if not row:
            return None
        mappings = conn.execute(
            "select sector_id, branch, sort_order from local_theme_sector_mapping where theme_id = ? order by sort_order",
            (theme_id,),
        ).fetchall()
    return {
        "theme_id": row[0], "theme_name": row[1], "category": row[2],
        "status": row[3], "created_at": row[4], "updated_at": row[5],
        "sectors": [
            {"sector_id": m[0], "branch": m[1], "sort_order": m[2]}
            for m in mappings
        ],
    }


def save_theme(theme_id: str, theme_name: str, category: str, sector_mappings: list[dict[str, Any]] | None = None, operator: str = "user") -> dict[str, Any]:
    now = _now()
    with _conn() as conn:
        init_theme_schema(conn)
        existing = conn.execute("select theme_id from local_theme where theme_id = ?", (theme_id,)).fetchone()
        if existing:
            conn.execute(
                "update local_theme set theme_name = ?, category = ?, updated_at = ? where theme_id = ?",
                (theme_name, category, now, theme_id),
            )
            action = "update"
        else:
            conn.execute(
                "insert into local_theme(theme_id, theme_name, category, status, created_at, updated_at) values (?, ?, ?, 'active', ?, ?)",
                (theme_id, theme_name, category, now, now),
            )
            action = "create"
        if sector_mappings is not None:
            conn.execute("delete from local_theme_sector_mapping where theme_id = ?", (theme_id,))
            for idx, m in enumerate(sector_mappings):
                conn.execute(
                    "insert into local_theme_sector_mapping(theme_id, sector_id, branch, sort_order) values (?, ?, ?, ?)",
                    (theme_id, m["sector_id"], m.get("branch", ""), idx),
                )
        conn.execute(
            "insert into local_theme_version(theme_id, action, detail, operator, created_at) values (?, ?, ?, ?, ?)",
            (theme_id, action, theme_name, operator, now),
        )
        conn.commit()
    return get_theme(theme_id) or {}


def archive_theme(theme_id: str, operator: str = "user") -> bool:
    now = _now()
    with _conn() as conn:
        init_theme_schema(conn)
        row = conn.execute("select status from local_theme where theme_id = ?", (theme_id,)).fetchone()
        if not row:
            return False
        new_status = "archived" if row[0] == "active" else "active"
        conn.execute("update local_theme set status = ?, updated_at = ? where theme_id = ?", (new_status, now, theme_id))
        conn.execute(
            "insert into local_theme_version(theme_id, action, detail, operator, created_at) values (?, ?, ?, ?, ?)",
            (theme_id, "archive" if new_status == "archived" else "reactivate", new_status, operator, now),
        )
        conn.commit()
    return True


def merge_themes(target_id: str, source_ids: list[str], operator: str = "user") -> dict[str, Any] | None:
    """将 source_ids 的板块映射合并到 target_id，并归档 source。"""
    now = _now()
    with _conn() as conn:
        init_theme_schema(conn)
        target = conn.execute("select theme_id from local_theme where theme_id = ?", (target_id,)).fetchone()
        if not target:
            return None
        existing = conn.execute(
            "select sector_id from local_theme_sector_mapping where theme_id = ?", (target_id,),
        ).fetchall()
        existing_ids = {r[0] for r in existing}
        max_order = conn.execute("select coalesce(max(sort_order), -1) from local_theme_sector_mapping where theme_id = ?", (target_id,)).fetchone()[0]
        for src_id in source_ids:
            rows = conn.execute(
                "select sector_id, branch from local_theme_sector_mapping where theme_id = ?", (src_id,),
            ).fetchall()
            for sector_id, branch in rows:
                if sector_id not in existing_ids:
                    max_order += 1
                    conn.execute(
                        "insert or ignore into local_theme_sector_mapping(theme_id, sector_id, branch, sort_order) values (?, ?, ?, ?)",
                        (target_id, sector_id, branch, max_order),
                    )
                    existing_ids.add(sector_id)
            conn.execute("update local_theme set status = 'archived', updated_at = ? where theme_id = ?", (now, src_id))
            conn.execute(
                "insert into local_theme_version(theme_id, action, detail, operator, created_at) values (?, 'merged_into', ?, ?, ?)",
                (src_id, target_id, operator, now),
            )
        conn.execute(
            "insert into local_theme_version(theme_id, action, detail, operator, created_at) values (?, 'merge_from', ?, ?, ?)",
            (target_id, ",".join(source_ids), operator, now),
        )
        conn.execute("update local_theme set updated_at = ? where theme_id = ?", (now, target_id))
        conn.commit()
    return get_theme(target_id)


def theme_history(theme_id: str, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(200, limit))
    with _conn() as conn:
        init_theme_schema(conn)
        rows = conn.execute(
            "select id, theme_id, action, detail, operator, created_at from local_theme_version where theme_id = ? order by id desc limit ?",
            (theme_id, limit),
        ).fetchall()
    return [
        {"id": r[0], "theme_id": r[1], "action": r[2], "detail": r[3], "operator": r[4], "created_at": r[5]}
        for r in rows
    ]


# --- 自定义板块 ---

def list_custom_sectors() -> list[dict[str, Any]]:
    with _conn() as conn:
        init_theme_schema(conn)
        rows = conn.execute(
            """
            select cs.sector_id, cs.sector_name, cs.category, cs.keywords,
                   count(css.symbol) as stock_count, cs.created_at, cs.updated_at
            from local_custom_sector cs
            left join local_custom_sector_stock css on css.sector_id = cs.sector_id
            group by cs.sector_id
            order by cs.updated_at desc
            """,
        ).fetchall()
    return [
        {"sector_id": r[0], "sector_name": r[1], "category": r[2], "keywords": r[3],
         "stock_count": r[4], "created_at": r[5], "updated_at": r[6]}
        for r in rows
    ]


def save_custom_sector(sector_id: str, sector_name: str, category: str, keywords: str, symbols: list[str]) -> dict[str, Any]:
    now = _now()
    with _conn() as conn:
        init_theme_schema(conn)
        conn.execute(
            """
            insert into local_custom_sector(sector_id, sector_name, category, keywords, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?)
            on conflict(sector_id) do update set
              sector_name = excluded.sector_name,
              category = excluded.category,
              keywords = excluded.keywords,
              updated_at = excluded.updated_at
            """,
            (sector_id, sector_name, category, keywords, now, now),
        )
        conn.execute("delete from local_custom_sector_stock where sector_id = ?", (sector_id,))
        for idx, symbol in enumerate(symbols):
            conn.execute(
                "insert into local_custom_sector_stock(sector_id, symbol, sort_order) values (?, ?, ?)",
                (sector_id, symbol, idx),
            )
        conn.commit()
    return {"sector_id": sector_id, "sector_name": sector_name, "category": category, "symbols": symbols}


def delete_custom_sector(sector_id: str) -> bool:
    with _conn() as conn:
        init_theme_schema(conn)
        conn.execute("delete from local_custom_sector_stock where sector_id = ?", (sector_id,))
        deleted = conn.execute("delete from local_custom_sector where sector_id = ?", (sector_id,)).rowcount
        conn.commit()
    return deleted > 0
