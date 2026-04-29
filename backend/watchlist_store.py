from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from theme_universe import WATCHLIST


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "backend" / "data" / "radar.db"


def init_watchlist_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists local_watchlist (
          symbol text primary key,
          name text not null,
          tag text,
          created_at text not null default current_timestamp
        );

        create table if not exists local_position (
          symbol text primary key,
          name text not null,
          quantity real not null,
          cost_price real,
          tag text,
          created_at text not null default current_timestamp
        );
        """
    )


def seed_watchlist(conn: sqlite3.Connection) -> None:
    count = conn.execute("select count(*) from local_watchlist").fetchone()[0]
    if count:
        return
    for item in WATCHLIST:
        conn.execute(
            "insert or ignore into local_watchlist(symbol, name, tag) values (?, ?, ?)",
            (item["symbol"], item["name"], "默认"),
        )


def list_watchlist() -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        init_watchlist_schema(conn)
        seed_watchlist(conn)
        rows = conn.execute("select symbol, name, tag, created_at from local_watchlist order by created_at, symbol").fetchall()
    return [{"symbol": row[0], "ts_code": row[0], "name": row[1], "tag": row[2], "created_at": row[3]} for row in rows]


def add_watchlist(symbol: str, name: str | None = None, tag: str | None = None) -> dict[str, Any]:
    symbol = symbol.strip().upper().split(".")[0]
    if not symbol or len(symbol) != 6 or not symbol.isdigit():
        raise ValueError("股票代码必须是6位数字")
    with sqlite3.connect(DB_PATH) as conn:
        init_watchlist_schema(conn)
        row = conn.execute("select name from em_stock where symbol = ?", (symbol,)).fetchone()
        final_name = name or (row[0] if row and row[0] != symbol else symbol)
        conn.execute(
            """
            insert into local_watchlist(symbol, name, tag)
            values (?, ?, ?)
            on conflict(symbol) do update set name = excluded.name, tag = excluded.tag
            """,
            (symbol, final_name, tag),
        )
        conn.commit()
    return {"symbol": symbol, "ts_code": symbol, "name": final_name, "tag": tag}


def delete_watchlist(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper().split(".")[0]
    with sqlite3.connect(DB_PATH) as conn:
        init_watchlist_schema(conn)
        conn.execute("delete from local_watchlist where symbol = ?", (symbol,))
        conn.commit()
    return {"symbol": symbol, "deleted": True}


def list_positions(default_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        init_watchlist_schema(conn)
        count = conn.execute("select count(*) from local_position").fetchone()[0]
        if count == 0:
            for item in default_positions:
                conn.execute(
                    """
                    insert or ignore into local_position(symbol, name, quantity, cost_price, tag)
                    values (?, ?, ?, ?, ?)
                    """,
                    (item["symbol"], item["name"], item.get("quantity", 0), item.get("cost_price"), "默认"),
                )
            conn.commit()
        rows = conn.execute(
            "select symbol, name, quantity, cost_price, tag, created_at from local_position order by created_at, symbol"
        ).fetchall()
    return [
        {
            "symbol": row[0],
            "ts_code": row[0],
            "name": row[1],
            "quantity": row[2],
            "cost_price": row[3],
            "tag": row[4],
            "created_at": row[5],
        }
        for row in rows
    ]


def add_position(symbol: str, name: str | None, quantity: float, cost_price: float | None = None, tag: str | None = None) -> dict[str, Any]:
    symbol = symbol.strip().upper().split(".")[0]
    if not symbol or len(symbol) != 6 or not symbol.isdigit():
        raise ValueError("股票代码必须是6位数字")
    if quantity <= 0:
        raise ValueError("持仓数量必须大于0")
    with sqlite3.connect(DB_PATH) as conn:
        init_watchlist_schema(conn)
        row = conn.execute("select name from em_stock where symbol = ?", (symbol,)).fetchone()
        final_name = name or (row[0] if row and row[0] != symbol else symbol)
        conn.execute(
            """
            insert into local_position(symbol, name, quantity, cost_price, tag)
            values (?, ?, ?, ?, ?)
            on conflict(symbol) do update set
              name = excluded.name,
              quantity = excluded.quantity,
              cost_price = excluded.cost_price,
              tag = excluded.tag
            """,
            (symbol, final_name, quantity, cost_price, tag),
        )
        conn.commit()
    return {"symbol": symbol, "ts_code": symbol, "name": final_name, "quantity": quantity, "cost_price": cost_price, "tag": tag}


def delete_position(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper().split(".")[0]
    with sqlite3.connect(DB_PATH) as conn:
        init_watchlist_schema(conn)
        conn.execute("delete from local_position where symbol = ?", (symbol,))
        conn.commit()
    return {"symbol": symbol, "deleted": True}
