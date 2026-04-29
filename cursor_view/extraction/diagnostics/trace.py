"""Per-cid replay of the project-resolution decision points.

:func:`trace_project_resolution` is the public entry point; it returns
a structured ``trace`` dict that the CLI renderer in :mod:`.__main__`
formats for human consumption and that unit tests can assert against
without scraping log text. The four documented root causes (orphan
filter, scoped-mode walk gap, dead chain, deleted parent) and the
"already resolved -- stale UI" case are produced by
:func:`_classify_cause` against fields populated by helpers in
:mod:`.probes` and :mod:`.walker`.

All SQLite reads use the read-only URI form per
``.cursor/rules/sqlite-cursor-db.mdc`` and run inside
``contextlib.closing`` blocks. The probe NEVER raises on a missing
source DB or missing cache row; those cases are valid signals that
get folded into the returned trace.
"""

from __future__ import annotations

import logging
from typing import Any

from cursor_view.extraction.diagnostics.probes import (
    count_bubbles_for_cid,
    find_bubble_with_tool_call_id,
    lookup_chat_summary,
    lookup_tool_call_parent,
    probe_composer_row,
)
from cursor_view.extraction.diagnostics.walker import walk_chain_via_cache
from cursor_view.paths import (
    cursor_root,
    cursor_view_cache_dir,
    global_storage_path,
)

logger = logging.getLogger(__name__)


_TASK_CID_PREFIX = "task-"
_GLOBAL_WS = "(global)"


def trace_project_resolution(cid: str) -> dict[str, Any]:
    """Replay the project-resolution decision points for one composer id.

    Returns a dict with these top-level keys:

    - ``cid`` / ``is_task_subagent`` / ``tool_call_id``: input echoes.
    - ``global_db`` / ``cache_db``: paths actually probed (or ``None``
      when the file was missing).
    - ``probes``: per-source findings (``composer``, ``bubble_count``,
      ``tool_call_parent_in_cache``, ``orphan_bubble_with_tcid``).
    - ``cache_summary``: the leaf cid's own ``chat_summary`` /
      ``composer_state`` rows, used by the classifier to distinguish
      "resolved in cache, UI stale" from "still broken in cache".
    - ``chain``: the per-hop ancestor walk via the persisted
      ``tool_call_parent`` table.
    - ``chain_terminus``: which terminating condition the walk hit.
    - ``cause``: a one-line classification mapping to the plan's
      root-cause taxonomy.
    """
    trace: dict[str, Any] = {
        "cid": cid,
        "is_task_subagent": cid.startswith(_TASK_CID_PREFIX),
        "tool_call_id": (
            cid[len(_TASK_CID_PREFIX):]
            if cid.startswith(_TASK_CID_PREFIX)
            else None
        ),
        "global_db": None,
        "cache_db": None,
        "probes": {},
        "chain": [],
        "chain_terminus": None,
        "cache_summary": None,
        "cause": "Unknown",
    }

    root = cursor_root()
    global_db = global_storage_path(root)
    cache_db = cursor_view_cache_dir() / "chat-index.sqlite3"
    trace["global_db"] = str(global_db) if global_db else None
    trace["cache_db"] = str(cache_db) if cache_db.exists() else None

    if global_db is not None and global_db.exists():
        trace["probes"]["composer"] = probe_composer_row(global_db, cid)
        trace["probes"]["bubble_count"] = count_bubbles_for_cid(global_db, cid)
        if trace["is_task_subagent"]:
            trace["probes"]["orphan_bubble_with_tcid"] = (
                find_bubble_with_tool_call_id(global_db, trace["tool_call_id"])
            )

    if cache_db.exists():
        trace["cache_summary"] = lookup_chat_summary(cache_db, cid)
        if trace["is_task_subagent"]:
            trace["probes"]["tool_call_parent_in_cache"] = (
                lookup_tool_call_parent(cache_db, trace["tool_call_id"])
            )
        chain, terminus = walk_chain_via_cache(cache_db, cid)
        trace["chain"] = chain
        trace["chain_terminus"] = terminus

    trace["cause"] = _classify_cause(trace)
    return trace


def _classify_cause(trace: dict[str, Any]) -> str:
    """Map a populated trace dict to one of the four documented causes.

    Ordering matters: Cause 1 vs Cause 4 are distinguished by whether
    a bubble carrying the missing tool-call id still lives on disk;
    Cause 2 vs Cause 3 are distinguished by whether the cached chain
    resolves to a real workspace (Pass 6 *should* have followed it)
    or terminates in a genuinely workspace-less ancestor.
    """
    if not trace.get("is_task_subagent"):
        return "Not a task-* subagent (resolution failure is upstream of Pass 5/6)."

    tcp = trace["probes"].get("tool_call_parent_in_cache")
    orphan = trace["probes"].get("orphan_bubble_with_tcid")
    terminus = trace.get("chain_terminus")
    cache_summary = trace.get("cache_summary") or {}
    leaf_ws = cache_summary.get("workspace_id")

    if tcp is None:
        if orphan is not None and orphan.get("in_parent_headers") is False:
            return (
                "Cause 1: orphan-filter dropped the parent's tool-call bubble. "
                "Bubble exists in cursorDiskKV but is absent from the parent's "
                "fullConversationHeadersOnly array, so Pass 2 skipped the "
                "tool_call_parent upsert."
            )
        if orphan is None:
            return (
                "Cause 4: no bubble on disk carries this toolCallId and no "
                "tool_call_parent row in cache. Parent likely deleted; the "
                "task-* row is an orphan."
            )
        return (
            "Cause 1 (likely): bubble for this toolCallId exists on disk but "
            "tool_call_parent has no cache row for it. Re-check headers-array "
            "membership."
        )

    if terminus in ("resolved-workspace", "resolved-inferred"):
        if leaf_ws and leaf_ws != _GLOBAL_WS:
            return (
                "Resolved: cache reports a real workspace for this chat. If "
                "the UI still shows (global), the running process is serving "
                "a stale snapshot -- force a refresh."
            )
        return (
            "Cause 2: persisted chain resolves to a real ancestor but the "
            "leaf chat_summary still carries (global). Pass 6 walk could not "
            "follow the chain through a non-dirty task-* ancestor in the "
            "last scoped extraction."
        )

    if terminus == "dead-global":
        return (
            "Cause 3: chain walks up to a top-level chat that itself is "
            "(global) with no inferred project. The chat was spawned from a "
            "workspace-less Cursor session; nothing to inherit."
        )

    if terminus == "missing-edge":
        return (
            "Cause 1 or 4: chain hit a task-* ancestor with no cached "
            "tool_call_parent edge. Re-run the diagnostic on that ancestor "
            "for a precise classification."
        )

    if terminus == "depth-cap":
        return (
            "Indeterminate: walk hit the 8-hop cap without resolving. Either "
            "the chain is genuinely deeper than Pass 6 follows or a cycle "
            "through siblings is consuming hops."
        )

    if terminus == "cycle":
        return "Indeterminate: cycle detected in the parent chain."

    return "Indeterminate: unable to classify; see chain and probes for context."
