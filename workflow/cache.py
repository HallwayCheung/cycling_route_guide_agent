from __future__ import annotations

import json
import os
import sqlite3
import time
from threading import Lock
from typing import Any


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cycling_cache.db")
_LOCK = Lock()


def _init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.commit()


_init_db()


def get_cached_json(cache_key: str, *, allow_stale: bool = False) -> Any | None:
    now = int(time.time())
    with _LOCK, sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT payload, expires_at FROM api_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()

    if not row:
        return None

    payload, expires_at = row
    if not allow_stale and expires_at < now:
        return None

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def set_cached_json(cache_key: str, payload: Any, ttl_seconds: int) -> None:
    now = int(time.time())
    expires_at = now + max(60, ttl_seconds)
    encoded = json.dumps(payload, ensure_ascii=False)
    with _LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO api_cache (cache_key, payload, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload = excluded.payload,
                expires_at = excluded.expires_at,
                created_at = excluded.created_at
            """,
            (cache_key, encoded, expires_at, now),
        )
        conn.commit()
