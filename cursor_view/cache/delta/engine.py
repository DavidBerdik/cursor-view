"""Apply-delta orchestrator: one ``BEGIN IMMEDIATE`` tx over every sub-pass."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Callable

from cursor_view.cache.delta.cached_state import _compose_cached_state
from cursor_view.cache.delta.composer_rows import (
    _GLOBAL_WS,
    _delete_cid_rows,
    _extract_modified_chats,
    _upsert_composer_state,
)
from cursor_view.cache.delta.metadata import (
    _apply_tool_call_parent_updates,
    _sync_source_row,
    _update_meta,
)
from cursor_view.cache.delta.project_only import (
    _project_only_refresh,
    _workspace_db_lookup,
)
from cursor_view.cache.diff import DirtySet

logger = logging.getLogger(__name__)

# Re-exported so callers that used to reach for
# ``cursor_view.cache.apply_delta._GLOBAL_WS`` find the sentinel in the
# expected location after the split. Canonical definition lives in
# :mod:`cursor_view.cache.delta.composer_rows`.
__all__ = ["_GLOBAL_WS", "apply_delta"]


def apply_delta(
    con: sqlite3.Connection,
    dirty: DirtySet,
    source_fingerprint: str,
    sources: list[dict[str, Any]],
    insert_chat: Callable[
        [sqlite3.Cursor, dict[str, Any], bool],
        tuple[dict[str, Any], list[dict[str, Any]]],
    ],
    database_has_fts: Callable[[sqlite3.Connection], bool],
) -> None:
    """Apply ``dirty`` to the live cache in a single ``BEGIN IMMEDIATE`` tx.

    ``insert_chat`` is injected so the apply step reuses the caller's
    existing row-insertion logic (normally
    ``ChatIndex._insert_chat``) without :mod:`cursor_view.cache`
    having to import :mod:`cursor_view.chat_index` and create a
    cycle. It must return the ``(formatted_chat, coalesced_messages)``
    pair produced while writing the content rows; the apply loop hands
    that pair straight to ``_upsert_composer_state`` so the formatting
    work is paid exactly once per refreshed composer. The caller owns
    the connection lifecycle, concurrency serialization
    (``_rebuild_build_lock``), and the choice between this path and
    the full-rebuild fallback.
    """
    cur = con.cursor()
    fts_enabled = database_has_fts(con)
    workspace_dbs = _workspace_db_lookup()

    prior_isolation = con.isolation_level
    # Python's sqlite3 module auto-begins a transaction for DML under
    # the default isolation level; switching to None lets us issue the
    # BEGIN IMMEDIATE / COMMIT / ROLLBACK explicitly so the cache
    # write is framed by a single predictable transaction.
    con.isolation_level = None
    try:
        cur.execute("BEGIN IMMEDIATE")
        try:
            cached_state = _compose_cached_state(cur, dirty)
            new_chats = _extract_modified_chats(dirty, cached_state)

            for cid in dirty.deleted_cids:
                _delete_cid_rows(cur, cid, fts_enabled)

            inserted = 0
            for cid in dirty.modified_cids:
                _delete_cid_rows(cur, cid, fts_enabled)
                chat = new_chats.get(cid)
                if chat is None:
                    continue
                formatted, messages = insert_chat(cur, chat, fts_enabled)
                _upsert_composer_state(cur, chat, formatted, messages)
                inserted += 1

            project_only_workspaces = 0
            project_only_composers = 0
            for ws_id in dirty.workspace_project_dirty:
                updated = _project_only_refresh(cur, ws_id, workspace_dbs.get(ws_id))
                if updated > 0:
                    project_only_workspaces += 1
                    project_only_composers += updated

            _apply_tool_call_parent_updates(cur, dirty.tool_call_parent_updates)
            _sync_source_row(cur, dirty.source_row_snapshot)
            _update_meta(cur, source_fingerprint, sources)
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
    finally:
        con.isolation_level = prior_isolation

    # Counter layout matches the observability line described in
    # todo 8 of the incremental-refresh plan: message-level dirtiness
    # (``modified`` / ``inserted``), link-driven dirtiness
    # (``subagent-propagated``), removals (``deleted``), cheap
    # workspace-scoped UPDATEs (``project-only``), and persisted-map
    # churn (``tool_call_parent updates``) are each tracked
    # separately so a spike in any single axis is diagnosable from
    # the log alone.
    logger.info(
        "Incremental chat-index refresh: "
        "%s modified (inserted %s, %s subagent-propagated), "
        "%s deleted, "
        "%s project-only composers across %s workspaces, "
        "%s tool_call_parent updates",
        len(dirty.modified_cids),
        inserted,
        len(dirty.subagent_propagated_cids),
        len(dirty.deleted_cids),
        project_only_composers,
        project_only_workspaces,
        len(dirty.tool_call_parent_updates),
    )
