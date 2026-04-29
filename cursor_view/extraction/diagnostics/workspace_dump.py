"""Coarse "what does this Cursor install look like?" log dump.

Gated by the ``CURSOR_CHAT_DIAGNOSTICS`` environment variable; the
extraction pipeline calls :func:`dump_workspace_diagnostics` once at
the top of :func:`cursor_view.extraction.extract_chats` when the
variable is set. Errors are caught so a probe failure cannot block
the real extraction path, but they are logged with a traceback so the
user sees why the probe itself misbehaved.
"""

from __future__ import annotations

import logging
import os
import pathlib
import sqlite3
from contextlib import closing

from cursor_view.paths import global_storage_path, workspaces

logger = logging.getLogger(__name__)


_AI_KEY_PATTERNS = ("%ai%", "%chat%", "%composer%", "%prompt%", "%generation%")


def diagnostics_enabled() -> bool:
    """Return True when ``CURSOR_CHAT_DIAGNOSTICS`` is set to a truthy value."""
    return bool(os.environ.get("CURSOR_CHAT_DIAGNOSTICS"))


def dump_workspace_diagnostics(root: pathlib.Path) -> None:
    """Log a summary of tables/keys in the first workspace and the global DB."""
    try:
        _dump_first_workspace(root)
        _dump_global_storage(root)
        logger.info("\n--- END DIAGNOSTICS ---\n")
    except Exception:
        logger.exception("Diagnostic probe failed")


def _dump_first_workspace(root: pathlib.Path) -> None:
    first_ws = next(workspaces(root), None)
    if first_ws is None:
        return
    ws_id, db = first_ws
    logger.info("\n--- DIAGNOSTICS for workspace %s ---", ws_id)
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as con:
        cur = con.cursor()
        tables = _list_tables(cur)
        logger.info("Tables in workspace DB: %s", tables)
        if "ItemTable" in tables:
            _dump_item_table_keys(cur)


def _dump_global_storage(root: pathlib.Path) -> None:
    global_db = global_storage_path(root)
    if global_db is None:
        return
    logger.info("\n--- DIAGNOSTICS for global storage ---")
    with closing(sqlite3.connect(f"file:{global_db}?mode=ro", uri=True)) as con:
        cur = con.cursor()
        tables = _list_tables(cur)
        logger.info("Tables in global DB: %s", tables)
        if "ItemTable" in tables:
            _dump_item_table_keys(cur)
        if "cursorDiskKV" in tables:
            _dump_cursor_disk_kv_prefixes(cur)


def _list_tables(cur: sqlite3.Cursor) -> list[str]:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [row[0] for row in cur.fetchall()]


def _dump_item_table_keys(cur: sqlite3.Cursor) -> None:
    for pattern in _AI_KEY_PATTERNS:
        cur.execute("SELECT key FROM ItemTable WHERE key LIKE ?", (pattern,))
        keys = [row[0] for row in cur.fetchall()]
        if keys:
            logger.info("Keys matching '%s': %s", pattern, keys)


def _dump_cursor_disk_kv_prefixes(cur: sqlite3.Cursor) -> None:
    cur.execute("SELECT DISTINCT substr(key, 1, instr(key, ':') - 1) FROM cursorDiskKV")
    prefixes = [row[0] for row in cur.fetchall()]
    logger.info("Key prefixes in cursorDiskKV: %s", prefixes)
