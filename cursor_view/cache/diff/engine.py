"""Top-level orchestrator: walk every source, hash, classify."""

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

    Subagent dirty-set propagation is intentionally NOT performed here.
    The ``task-<toolCallId>`` descendant walk that used to fold every
    subagent of a dirty parent into ``modified_cids`` now lives in
    :mod:`cursor_view.cache.delta.propagation` and is gated on real
    project-resolution shifts (or parent deletion / ``tool_call_parent``
    edge churn). Cursor bumps ``lastUpdatedAt`` and rewrites bubble JSON
    on navigation-only events, so "any source row of the parent
    changed" is a far broader trigger than Pass 6's inheritance
    invariant actually requires; gating at apply time -- once we know
    the post-extraction project tuple -- keeps the walk surgical.
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

    # TODO(bug): A transient/locked/corrupt read of a source state.vscdb during
    # an incremental refresh silently deletes that DB's chats from the cache --
    # the user sees them disappear from the UI until a later successful refresh
    # re-extracts them. Suspected cause: _diff_global_db / _diff_workspace_db
    # return early on sqlite3.DatabaseError without recording any
    # source_row_snapshot rows for that DB (the file still passed the db.exists()
    # check above, so this is the "exists but unreadable" case, common because
    # Cursor is an active writer), and _process_deletions then cannot tell
    # "source unreadable this pass" from "composer genuinely deleted" -- it
    # routes every cached cid with no snapshot row into dirty.deleted_cids, which
    # apply_delta deletes and commits.
    _process_deletions(cached_rows, dirty)

    # Drop tool_call_parent rows whose parent is being deleted. Upserts
    # from the changed-bubble branch already won; the setdefault() call
    # here only runs for parents that are pure-delete with no matching
    # upsert.
    for tcid, parent in cached_tcp.items():
        if parent in dirty.deleted_cids:
            dirty.tool_call_parent_updates.setdefault(tcid, None)

    _trim_comp2ws_observability(dirty)

    return dirty
