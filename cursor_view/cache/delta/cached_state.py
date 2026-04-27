"""Seed scoped extraction with cache-side ancestor and tool-call-parent state."""

from __future__ import annotations

import sqlite3
from typing import Any

from cursor_view.cache.delta.composer_rows import _GLOBAL_WS
from cursor_view.cache.diff import DirtySet
from cursor_view.extraction import CachedExtractionState


def _load_raw_cached_tool_call_parent(cur: sqlite3.Cursor) -> dict[str, str]:
    """Snapshot the cache's ``tool_call_parent`` table verbatim.

    Returned map is the pre-merge view -- it does not yet account for
    ``dirty.tool_call_parent_updates``. Two consumers want it in this
    shape: :func:`_merge_tool_call_parent_updates` produces the
    Pass-5 friendly merged form, and the apply-time edge-churn
    detector in :mod:`cursor_view.cache.delta.propagation` compares
    this snapshot against the staged updates to decide which
    ``task-<toolCallId>`` children need to ride the secondary
    extraction pass.
    """
    cur.execute("SELECT tool_call_id, parent_composer_id FROM tool_call_parent")
    return {row[0]: row[1] for row in cur.fetchall()}


def _merge_tool_call_parent_updates(
    raw: dict[str, str], updates: dict[str, str | None]
) -> dict[str, str]:
    """Apply staged ``tool_call_parent`` upserts / deletes to the raw cache map.

    Pass 5 of scoped extraction prefers the in-memory map built by
    scoped Pass 2 for toolCallIds both halves cover, so we only need
    the cached view to cover toolCallIds whose parent bubble was NOT
    in the dirty set. Folding the staged upserts/deletes in here lets
    ``_link_task_subagents_to_parents`` resolve parents correctly even
    when a fresh bubble's cid isn't itself in ``modified_cids`` (e.g.
    a pane-key-only promotion).
    """
    merged = dict(raw)
    for tcid, parent in updates.items():
        if parent is None:
            merged.pop(tcid, None)
        else:
            merged[tcid] = parent
    return merged


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
    """Assemble the :class:`CachedExtractionState` for scoped extraction.

    Carries both the merged Pass-5-ready ``tool_call_parent`` and the
    pre-merge ``raw_cached_tool_call_parent`` snapshot so the
    apply-time subagent-propagation gate in
    :mod:`cursor_view.cache.delta.propagation` can compare new edges
    against the cache without re-running the SELECT inside the
    ``BEGIN IMMEDIATE`` transaction. Extraction itself only reads the
    merged form; the raw map is a transport payload.
    """
    raw_tcp = _load_raw_cached_tool_call_parent(cur)
    merged_tcp = _merge_tool_call_parent_updates(
        raw_tcp, dirty.tool_call_parent_updates
    )
    ancestor_comp2ws, ancestor_inferred = _load_ancestor_state(cur, dirty)
    return CachedExtractionState(
        tool_call_parent=merged_tcp,
        ancestor_comp2ws=ancestor_comp2ws,
        ancestor_inferred_project=ancestor_inferred,
        raw_cached_tool_call_parent=raw_tcp,
    )
