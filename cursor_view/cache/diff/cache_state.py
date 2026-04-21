"""Read-only snapshots of the cache state the diff compares against."""

from __future__ import annotations

import sqlite3

from cursor_view.cache.diff.types import SourceKey


def _load_cached_source_rows(cur: sqlite3.Cursor) -> dict[SourceKey, tuple[str, str]]:
    """Snapshot ``source_row`` as ``SourceKey -> (row_hash, composer_id)``."""
    cur.execute("SELECT db_path, table_name, key, row_hash, composer_id FROM source_row")
    return {
        SourceKey(r[0], r[1], r[2]): (r[3], r[4])
        for r in cur.fetchall()
    }


def _load_cached_tool_call_parent(cur: sqlite3.Cursor) -> dict[str, str]:
    """Snapshot ``tool_call_parent`` as ``tool_call_id -> parent_composer_id``."""
    cur.execute("SELECT tool_call_id, parent_composer_id FROM tool_call_parent")
    return {r[0]: r[1] for r in cur.fetchall()}


def _known_cids_by_workspace(cur: sqlite3.Cursor) -> dict[str, set[str]]:
    """Group every cached composer by its ``composer_state.workspace_id``."""
    cur.execute("SELECT workspace_id, session_id FROM composer_state")
    out: dict[str, set[str]] = {}
    for ws_id, cid in cur.fetchall():
        out.setdefault(ws_id, set()).add(cid)
    return out
