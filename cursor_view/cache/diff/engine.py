"""Top-level orchestrator: walk every source, hash, classify, propagate."""

from __future__ import annotations

import pathlib
import sqlite3
from typing import Any

from cursor_view.cache.diff.cache_state import (
    _known_cids_by_workspace,
    _load_cached_source_rows,
    _load_cached_tool_call_parent,
)
from cursor_view.cache.diff.global_db import _diff_global_db
from cursor_view.cache.diff.propagation import (
    _process_deletions,
    _propagate_subagent_dirtiness,
    _trim_comp2ws_observability,
)
from cursor_view.cache.diff.types import DirtySet
from cursor_view.cache.diff.workspace_db import (
    _diff_workspace_db,
    _diff_workspace_json,
)

_GLOBAL_SOURCE_ID = "(global)"


def compute_source_diff(
    sources: list[dict[str, Any]],
    cache_con: sqlite3.Connection,
) -> DirtySet:
    """Produce a :class:`DirtySet` describing what's changed since the last cache build.

    ``sources`` is the list produced by
    :meth:`cursor_view.chat_index.ChatIndex._current_source_fingerprint`;
    each entry carries ``workspace_id`` and ``path`` plus stat metadata.
    The diff intentionally ignores the stat fields and rehashes values,
    so an mtime flip without a content change produces an empty dirty
    set and no apply work is scheduled.

    ``cache_con`` must be a connection to the current chat-index cache
    (read-only is sufficient). The ``source_row``, ``tool_call_parent``,
    and ``composer_state`` tables are expected to exist; on a freshly
    created v2 cache they are empty, and the diff reports every current
    source row as modified so the apply step performs an initial
    populate.
    """
    cur = cache_con.cursor()
    cached_rows = _load_cached_source_rows(cur)
    cached_tcp = _load_cached_tool_call_parent(cur)
    known_cids_by_ws = _known_cids_by_workspace(cur)

    dirty = DirtySet()
    for entry in sources:
        ws_id = entry.get("workspace_id") or ""
        path_str = entry.get("path")
        if not path_str:
            continue
        db = pathlib.Path(path_str)
        if not db.exists():
            continue
        if ws_id == _GLOBAL_SOURCE_ID:
            _diff_global_db(db, cached_rows, dirty)
        else:
            known_cids = known_cids_by_ws.get(ws_id, set())
            _diff_workspace_db(ws_id, db, cached_rows, known_cids, dirty)
            _diff_workspace_json(db.parent, ws_id, cached_rows, dirty)

    _process_deletions(cached_rows, dirty)

    # Drop tool_call_parent rows whose parent is being deleted. Upserts
    # from the changed-bubble branch already won; the setdefault() call
    # here only runs for parents that are pure-delete with no matching
    # upsert.
    for tcid, parent in cached_tcp.items():
        if parent in dirty.deleted_cids:
            dirty.tool_call_parent_updates.setdefault(tcid, None)

    # Subagent propagation uses the POST-change view of
    # ``tool_call_parent`` so links that appeared in this refresh (a
    # newly-fired tool-call bubble linking its ``task-<toolCallId>``
    # child) immediately fold the child into ``modified_cids``.
    # Without the merge the walk would only see links from previous
    # refreshes and miss first-time subagent spawns.
    merged_tcp = dict(cached_tcp)
    for tcid, parent in dirty.tool_call_parent_updates.items():
        if parent is None:
            merged_tcp.pop(tcid, None)
        else:
            merged_tcp[tcid] = parent

    _propagate_subagent_dirtiness(dirty, merged_tcp)
    _trim_comp2ws_observability(dirty)

    return dirty
