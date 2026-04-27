"""Apply-delta orchestrator: one ``BEGIN IMMEDIATE`` tx over every sub-pass."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable

from cursor_view.cache.delta.cached_state import _compose_cached_state
from cursor_view.cache.delta.composer_rows import (
    _GLOBAL_WS,
    _apply_chat_writes,
    _delete_cid_rows,
    _extract_modified_chats,
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
from cursor_view.cache.delta.propagation import (
    _apply_secondary_pass,
    _snapshot_cached_project,
)
from cursor_view.cache.diff import DirtySet

logger = logging.getLogger(__name__)

# Re-exported so callers that used to reach for
# ``cursor_view.cache.apply_delta._GLOBAL_WS`` find the sentinel in the
# expected location after the split. Canonical definition lives in
# :mod:`cursor_view.cache.delta.composer_rows`.
__all__ = ["_GLOBAL_WS", "apply_delta"]


def _apply_workspace_only_refresh(
    cur: sqlite3.Cursor,
    workspace_project_dirty: set[str],
    workspace_dbs: dict[str, Path],
) -> tuple[int, int]:
    """Run the per-workspace project-only UPDATE for each dirty workspace.

    Returns ``(updated_workspace_count, updated_composer_count)``.
    Workspaces whose :func:`_project_only_refresh` returned 0 do not
    contribute to either counter, mirroring the log-line semantics
    that "project-only" reflects actual writes (a churn-only
    ``treeViewState`` flip with no real project change stays silent).
    """
    workspaces = 0
    composers = 0
    for ws_id in workspace_project_dirty:
        updated = _project_only_refresh(cur, ws_id, workspace_dbs.get(ws_id))
        if updated > 0:
            workspaces += 1
            composers += updated
    return workspaces, composers


def _log_refresh_summary(
    dirty: DirtySet,
    inserted: int,
    project_shifted: set[str],
    secondary_inserted: int,
    project_only_workspaces: int,
    project_only_composers: int,
) -> None:
    """Emit the structured refresh line every successful apply produces.

    Counter layout mirrors the observability discipline the
    incremental-refresh plan codified, extended for the apply-time
    propagation gate: message-level dirtiness (``modified`` /
    ``inserted``), the per-refresh project-shift count that gates
    descendant propagation, link-driven dirtiness
    (``subagent-propagated``) plus the count of those subagents that
    produced new chat rows (``secondary inserts``), removals
    (``deleted``), cheap workspace-scoped UPDATEs (``project-only``),
    and persisted-map churn (``tool_call_parent updates``) are each
    tracked separately so a spike in any single axis is diagnosable
    from the log alone. Lazy ``%``-style formatting per
    :file:`.cursor/rules/python-standards.mdc` keeps the cost of a
    disabled log level zero.
    """
    logger.info(
        "Incremental chat-index refresh: "
        "%s modified (inserted %s, %s project-shifted, "
        "%s subagent-propagated, %s secondary inserts), "
        "%s deleted, "
        "%s project-only composers across %s workspaces, "
        "%s tool_call_parent updates",
        len(dirty.modified_cids),
        inserted,
        len(project_shifted),
        len(dirty.subagent_propagated_cids),
        secondary_inserted,
        len(dirty.deleted_cids),
        project_only_composers,
        project_only_workspaces,
        len(dirty.tool_call_parent_updates),
    )


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

    Subagent dirtiness propagates from this layer rather than the
    diff: the apply-time gate in
    :mod:`cursor_view.cache.delta.propagation` runs after the
    directly-modified parents have been re-extracted and written, and
    decides whether each parent's ``task-<toolCallId>`` descendants
    actually need to ride a secondary scoped extraction. A parent
    whose bubble JSON changed without shifting its project no longer
    drags its descendants into the apply loop -- that was the
    dominant source of the "23242 modified (inserted 505, 22737
    subagent-propagated)"-style refresh logs the gate exists to fix.
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
            cached_proj = _snapshot_cached_project(cur, dirty.modified_cids)
            new_chats = _extract_modified_chats(dirty, cached_state)

            for cid in dirty.deleted_cids:
                _delete_cid_rows(cur, cid, fts_enabled)

            inserted, primary_formatted = _apply_chat_writes(
                cur, dirty.modified_cids, new_chats, insert_chat, fts_enabled,
            )

            _, secondary_inserted, project_shifted = _apply_secondary_pass(
                cur, dirty, cached_state, primary_formatted, cached_proj,
                insert_chat, fts_enabled,
            )

            project_only_workspaces, project_only_composers = (
                _apply_workspace_only_refresh(
                    cur, dirty.workspace_project_dirty, workspace_dbs,
                )
            )

            _apply_tool_call_parent_updates(cur, dirty.tool_call_parent_updates)
            _sync_source_row(cur, dirty.source_row_snapshot)
            _update_meta(cur, source_fingerprint, sources)
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
    finally:
        con.isolation_level = prior_isolation

    _log_refresh_summary(
        dirty,
        inserted,
        project_shifted,
        secondary_inserted,
        project_only_workspaces,
        project_only_composers,
    )
