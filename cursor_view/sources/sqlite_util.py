"""Low-level SQLite helpers shared by every source iterator."""

from __future__ import annotations

import json
import logging
import pathlib
import sqlite3

logger = logging.getLogger(__name__)


def j(cur: sqlite3.Cursor, table: str, key: str):
    """Load a JSON value from ``table`` by string ``key``; return raw string if JSON decode fails."""
    cur.execute(f"SELECT value FROM {table} WHERE key=?", (key,))
    row = cur.fetchone()
    if not row:
        return None
    raw = row[0]
    try:
        return json.loads(raw)
    except Exception as e:
        logger.debug("Failed to parse JSON for %s: %s", key, e)
        # Some Cursor/VSCode keys (e.g. debug.selectedroot) store a raw string
        # without JSON quoting. Preserve it so downstream fallbacks can use it.
        if isinstance(raw, str) and raw:
            return raw
        return None


def _connect_cursor_disk_kv(db: pathlib.Path) -> sqlite3.Connection | None:
    """Open ``db`` read-only and confirm the ``cursorDiskKV`` table is present.

    Returns ``None`` (and logs at debug) for any error or for DBs that
    never grew the ``cursorDiskKV`` table; callers should iterate
    nothing in that case. Every ``cursorDiskKV``-consuming iterator in
    this package funnels through here so the "open + probe" handshake
    lives in one place.
    """
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.DatabaseError as e:
        logger.debug("Database error opening %s: %s", db, e)
        return None
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'")
        if cur.fetchone() is None:
            con.close()
            return None
    except sqlite3.DatabaseError as e:
        logger.debug("Database error probing cursorDiskKV in %s: %s", db, e)
        con.close()
        return None
    return con
