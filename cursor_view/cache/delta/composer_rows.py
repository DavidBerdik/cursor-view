"""Per-composer row shaping: delete, re-extract, hash, and upsert watermarks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from cursor_view.extraction import CachedExtractionState, extract_chats
from cursor_view.timestamps import session_sort_key_ms

# Sentinel matching the string written to ``comp2ws`` for composers
# without a workspace in ``_collect_global_bubbles`` /
# ``_collect_global_composers``. Used here (and by
# :mod:`cursor_view.cache.delta.cached_state`) to gate the
# ancestor-inferred-project cache seed: only ``(global)``-tagged rows
# carry inferred_project values in the cache (workspace-tagged rows
# use their workspace's project directly).
_GLOBAL_WS = "(global)"


def _delete_cid_rows(cur: sqlite3.Cursor, cid: str, fts_enabled: bool) -> None:
    """Drop every cache row tied to one composer id.

    Includes ``composer_state`` so a subsequently-deleted cid does not
    linger as a ghost ancestor for Pass 6 on the next refresh.
    """
    cur.execute("DELETE FROM chat_summary WHERE session_id=?", (cid,))
    cur.execute("DELETE FROM chat_message WHERE session_id=?", (cid,))
    cur.execute("DELETE FROM chat_search_text WHERE session_id=?", (cid,))
    if fts_enabled:
        cur.execute("DELETE FROM chat_search_fts WHERE session_id=?", (cid,))
    cur.execute("DELETE FROM composer_state WHERE session_id=?", (cid,))


def _composer_hash(
    chat_formatted: dict[str, Any], messages: list[dict[str, Any]]
) -> str:
    """Return a stable content hash for one composer's frontend-shaped payload.

    Mirrors the role of ``source_row.row_hash`` one granularity up; a
    caller that only reads ``composer_state`` can compare this column
    against a freshly derived payload to detect drift without joining
    back to ``chat_message``.
    """
    payload = {
        "project_name": chat_formatted.get("project", {}).get("name", ""),
        "project_root": chat_formatted.get("project", {}).get("rootPath", ""),
        "workspace_id": chat_formatted.get("workspace_id", ""),
        "db_path": chat_formatted.get("db_path", ""),
        "date": chat_formatted.get("date"),
        "messages": [
            {"role": m.get("role"), "content": m.get("content")} for m in messages
        ],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _upsert_composer_state(
    cur: sqlite3.Cursor,
    chat: dict[str, Any],
    chat_formatted: dict[str, Any],
    messages: list[dict[str, Any]],
) -> None:
    """Write the per-composer watermark row for one (re-)extracted chat."""
    session_obj = chat.get("session") or {}
    session_id = chat_formatted["session_id"]
    workspace_id = chat_formatted.get("workspace_id") or _GLOBAL_WS
    db_path = chat_formatted.get("db_path") or "Unknown database path"
    last_updated_ms = session_sort_key_ms(session_obj)
    composer_hash = _composer_hash(chat_formatted, messages)
    cur.execute(
        """
        INSERT INTO composer_state(
            session_id, workspace_id, db_path,
            last_updated_ms, composer_hash, bubble_count
        ) VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            workspace_id=excluded.workspace_id,
            db_path=excluded.db_path,
            last_updated_ms=excluded.last_updated_ms,
            composer_hash=excluded.composer_hash,
            bubble_count=excluded.bubble_count
        """,
        (
            session_id,
            workspace_id,
            db_path,
            last_updated_ms,
            composer_hash,
            len(messages),
        ),
    )


def _extract_modified_chats(
    dirty, cached_state: CachedExtractionState
) -> dict[str, dict[str, Any]]:
    """Run scoped extraction for ``dirty.modified_cids`` and key by composerId.

    Composers whose fresh extraction yields no messages are filtered
    out by ``_finalize_sessions`` and never appear in the returned
    dict; the caller treats that as "delete the cached rows and move
    on" so a composer that lost all its bubbles cleanly disappears
    from the cache without a dedicated deletion code path.
    """
    if not dirty.modified_cids:
        return {}
    extracted = extract_chats(
        cids=set(dirty.modified_cids), cached_state=cached_state
    )
    out: dict[str, dict[str, Any]] = {}
    for chat in extracted:
        cid = (chat.get("session") or {}).get("composerId")
        if cid:
            out[cid] = chat
    return out
