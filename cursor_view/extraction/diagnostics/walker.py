"""Cache-driven walk of the ``task-<tcid>`` parent chain.

:func:`walk_chain_via_cache` mirrors the traversal logic in
:mod:`cursor_view.extraction.passes.subagent_inheritance` but reads
the persisted chat-index cache because the diagnostic runs out of
process. Returns the per-hop state plus a ``terminus`` string the
classifier maps to one of the four documented root causes.
"""

from __future__ import annotations

import pathlib
import sqlite3
from contextlib import closing
from typing import Any

# Mirrors ``_MAX_PARENT_DEPTH`` in
# :mod:`cursor_view.extraction.passes.subagent_inheritance` so the
# diagnostic reports the same reachable-ancestor view that Pass 6
# actually walks. Diverging from Pass 6's cap would let the probe
# misclassify a deep-but-resolvable chain as ``depth-cap`` while Pass
# 6 itself succeeds (or vice versa).
_MAX_TRACE_DEPTH = 8

_TASK_CID_PREFIX = "task-"
_GLOBAL_WS = "(global)"
_UNKNOWN_PROJECT = "(unknown)"


def walk_chain_via_cache(
    cache_db: pathlib.Path, start_cid: str
) -> tuple[list[dict[str, Any]], str]:
    """Walk parent edges via cached ``tool_call_parent`` until resolution or dead end.

    Mirrors Pass 6's traversal. ``terminus`` is one of:

    - ``"resolved-workspace"``: an ancestor's ``workspace_id`` is a
      real workspace (not ``(global)``).
    - ``"resolved-inferred"``: an ancestor has a non-``(unknown)``
      project name with ``workspace_id == "(global)"`` (an
      ``_inferred_project`` saved in the cache).
    - ``"dead-global"``: walk reached a non-``task-*`` cid with no
      resolved workspace and no inferred project. Cause 3.
    - ``"missing-edge"``: walk hit a ``task-*`` cid with no
      ``tool_call_parent`` cache row. Cause 1 or Cause 4.
    - ``"depth-cap"``: 8-hop cap reached without resolution.
    - ``"cycle"``: same cid revisited.
    """
    chain: list[dict[str, Any]] = []
    visited: set[str] = set()
    current = start_cid
    terminus = "missing-edge"
    try:
        con = sqlite3.connect(f"file:{cache_db}?mode=ro", uri=True)
    except sqlite3.DatabaseError:
        return chain, terminus
    with closing(con):
        cur = con.cursor()
        for _ in range(_MAX_TRACE_DEPTH + 1):
            if current in visited:
                terminus = "cycle"
                break
            visited.add(current)
            hop = _hop_state(cur, current)
            chain.append(hop)
            ws = hop.get("workspace_id")
            if ws and ws != _GLOBAL_WS:
                terminus = "resolved-workspace"
                break
            project_name = hop.get("project_name")
            if (
                ws == _GLOBAL_WS
                and project_name
                and project_name != _UNKNOWN_PROJECT
            ):
                terminus = "resolved-inferred"
                break
            parent = _next_parent(cur, current)
            if parent is None:
                terminus = (
                    "missing-edge"
                    if current.startswith(_TASK_CID_PREFIX)
                    else "dead-global"
                )
                break
            current = parent
        else:
            terminus = "depth-cap"
    return chain, terminus


def _hop_state(cur: sqlite3.Cursor, cid: str) -> dict[str, Any]:
    """One row per ancestor in the chain trace."""
    try:
        cur.execute(
            "SELECT workspace_id, project_name, project_root_path "
            "FROM chat_summary WHERE session_id=?",
            (cid,),
        )
        row = cur.fetchone()
    except sqlite3.DatabaseError:
        row = None
    if not row:
        return {
            "cid": cid,
            "workspace_id": None,
            "project_name": None,
            "project_root_path": None,
            "in_cache": False,
        }
    return {
        "cid": cid,
        "workspace_id": row[0],
        "project_name": row[1],
        "project_root_path": row[2],
        "in_cache": True,
    }


def _next_parent(cur: sqlite3.Cursor, cid: str) -> str | None:
    """Bridge a ``task-<tcid>`` cid to its parent via persisted ``tool_call_parent``.

    Non-``task-*`` cids have no analogous out-edge in the cache (the
    pipeline records a regular composer's parent only on the *child*
    via ``subagentInfo.parentComposerId``, which is deliberately not
    persisted), so the walk terminates here for them. That matches
    Pass 6's behavior: it stops once it leaves the ``task-*`` chain.
    """
    if not cid.startswith(_TASK_CID_PREFIX):
        return None
    tcid = cid[len(_TASK_CID_PREFIX):]
    try:
        cur.execute(
            "SELECT parent_composer_id FROM tool_call_parent WHERE tool_call_id=?",
            (tcid,),
        )
        row = cur.fetchone()
    except sqlite3.DatabaseError:
        return None
    return row[0] if row else None
