"""Seed scoped extraction with cache-side ancestor and tool-call-parent state."""

from __future__ import annotations

import sqlite3
from typing import Any

from cursor_view.cache.delta.composer_rows import _GLOBAL_WS
from cursor_view.cache.diff import DirtySet
from cursor_view.extraction import CachedExtractionState


def _load_cached_tool_call_parent(
    cur: sqlite3.Cursor, updates: dict[str, str | None]
) -> dict[str, str]:
    """Return the persisted ``tool_call_parent`` map with staged updates applied.

    Pass 5 of scoped extraction prefers the in-memory map built by
    scoped Pass 2 for toolCallIds both halves cover, so we only need
    the cached view to cover toolCallIds whose parent bubble was NOT
    in the dirty set. Applying the staged upserts/deletes here lets
    ``_link_task_subagents_to_parents`` resolve parents correctly even
    when a fresh bubble's cid isn't itself in ``modified_cids`` (e.g.
    a pane-key-only promotion).
    """
    cur.execute("SELECT tool_call_id, parent_composer_id FROM tool_call_parent")
    tcp: dict[str, str] = {row[0]: row[1] for row in cur.fetchall()}
    for tcid, parent in updates.items():
        if parent is None:
            tcp.pop(tcid, None)
        else:
            tcp[tcid] = parent
    return tcp


def _load_ancestor_state(
    cur: sqlite3.Cursor, dirty: DirtySet
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Snapshot ``comp2ws`` / ``_inferred_project`` for every non-dirty composer.

    Pass 6 walks up ``subagent_parent`` looking for a resolved
    ancestor. In scoped mode the ancestor may be outside the dirty set
    and thus absent from the current run's ``comp2ws`` /
    ``sessions[ancestor]``; seeding both from the cache lets the walk
    reach a resolution without Pass 6 having to re-scan workspaces.
    The ``(global)`` filter on ``ancestor_inferred_project`` matches
    the extraction-time invariant that non-``(global)`` rows in
    ``chat_summary`` carry the workspace's own project, not an
    inferred one.
    """
    skip = dirty.modified_cids | dirty.deleted_cids
    cur.execute("SELECT session_id, workspace_id FROM composer_state")
    ancestor_comp2ws: dict[str, str] = {
        row[0]: row[1] for row in cur.fetchall() if row[0] not in skip
    }
    cur.execute(
        "SELECT session_id, workspace_id, project_name, project_root_path FROM chat_summary"
    )
    ancestor_inferred: dict[str, dict[str, Any]] = {}
    for session_id, workspace_id, project_name, project_root in cur.fetchall():
        if session_id in skip:
            continue
        if workspace_id != _GLOBAL_WS:
            continue
        if not project_name or project_name == "(unknown)":
            continue
        ancestor_inferred[session_id] = {
            "name": project_name,
            "rootPath": project_root or "(unknown)",
        }
    return ancestor_comp2ws, ancestor_inferred


def _compose_cached_state(
    cur: sqlite3.Cursor, dirty: DirtySet
) -> CachedExtractionState:
    """Assemble the :class:`CachedExtractionState` for scoped extraction."""
    tcp = _load_cached_tool_call_parent(cur, dirty.tool_call_parent_updates)
    ancestor_comp2ws, ancestor_inferred = _load_ancestor_state(cur, dirty)
    return CachedExtractionState(
        tool_call_parent=tcp,
        ancestor_comp2ws=ancestor_comp2ws,
        ancestor_inferred_project=ancestor_inferred,
    )
