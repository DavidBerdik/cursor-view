"""End-to-end extraction of chat sessions from Cursor local storage.

The top-level :func:`extract_chats` is a sequence of well-defined passes
over the workspace and global SQLite databases; each pass lives in its
own module under :mod:`cursor_view.extraction.passes` so the
orchestrator reads as a recipe rather than one 300-line function.

Pass order matters:

1. ``_collect_workspace_messages`` populates the workspace-level project
   and composer metadata and scrapes messages from each workspace's
   ``ItemTable``. Via ``workspace_info`` it also seeds synthetic
   ``comp_meta`` entries from ``workbench.panel.aichat.view.<cid>`` UI
   pane-view keys, which is often the only workspace link for chats
   that never touched files (pure web research, ``ask_question``,
   ``create_plan``, etc.).
2. ``_collect_global_bubbles`` streams per-bubble messages and URIs out
   of the global ``cursorDiskKV``, and records every bubble's
   ``toolFormerData.toolCallId -> parent composerId`` so Pass 5 can
   reconstruct subagent parent links without a second bubble scan.
3. ``_collect_global_composers`` walks ``composerData:*`` entries, filling
   in metadata, recording subagent -> parent relationships, resolving
   workspace associations, and appending conversation messages.
4. ``_apply_uri_fallbacks`` infers a project for still-global composers
   from the URIs seen in their bubbles.
5. ``_link_task_subagents_to_parents`` reconstructs the parent of
   ``task-<toolCallId>`` subagent composers from the parent bubble's
   ``toolFormerData``. Needed because ``task_v2``-spawned composers
   ship with ``subagentInfo: null``, so Pass 3 never records their
   parent and Pass 6 would otherwise have no chain to walk. Must run
   before Pass 6.
6. ``_apply_subagent_inheritance`` walks the subagent parent chain so
   unresolved subagent composers inherit an ancestor's project.
7. ``_collect_global_item_table_chats`` scrapes an older chat storage
   format (``workbench.panel.aichat.view.aichat.chatdata``) in the global
   ``ItemTable``.
8. ``_finalize_sessions`` drops empty sessions, resolves each session's
   project, and returns the recency-sorted list.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict

from cursor_view.paths import cursor_root, global_storage_path
from cursor_view.sources.composer_data import build_bubble_order_map

logger = logging.getLogger(__name__)


@dataclass
class CachedExtractionState:
    """Prior-run state threaded into scoped re-extraction.

    Populated by the chat-index apply step from the cache's
    ``tool_call_parent`` table and the ``composer_state`` /
    ``chat_summary`` rows of non-dirty composers. Every field is
    additive: missing entries make a pass behave as if the global scan
    had not seen that cid, so the caller can safely pass the full
    cached map without pre-filtering to the dirty set.
    """

    # Persisted toolCallId -> parent_composer_id map. Pass 5 merges
    # this with the in-memory map populated by scoped Pass 2, preferring
    # in-memory entries (first-seen semantics) for toolCallIds that
    # both halves cover.
    tool_call_parent: Dict[str, str] = field(default_factory=dict)
    # Pre-resolved comp2ws entries for composers that may appear as
    # ancestors when Pass 6 walks the subagent parent chain. Only
    # consulted when the current run's ``comp2ws`` has no entry for
    # the ancestor.
    ancestor_comp2ws: Dict[str, str] = field(default_factory=dict)
    # Pre-resolved ``_inferred_project`` dicts for the same ancestor
    # set. Only consulted when the current run's ``sessions[ancestor]``
    # has no ``_inferred_project`` of its own.
    ancestor_inferred_project: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def _merge_global_composer_into_meta(meta: dict, cid: str, data: dict) -> None:
    """Fill missing title/timestamps from global composerData; preserve workspace meta when set."""
    if not isinstance(data, dict):
        return
    name = data.get("name")
    if isinstance(name, str) and name.strip():
        cur = (meta.get("title") or "").strip()
        if (
            cur.startswith("Chat ")
            or cur.startswith("Global Chat ")
            or cur in ("(untitled)", "")
        ):
            meta["title"] = name.strip()
    created_at = data.get("createdAt")
    last_updated = data.get("lastUpdatedAt")
    if last_updated is None:
        last_updated = created_at
    if meta.get("createdAt") is None and created_at is not None:
        meta["createdAt"] = created_at
    if meta.get("lastUpdatedAt") is None and last_updated is not None:
        meta["lastUpdatedAt"] = last_updated


# Per-pass helpers live under :mod:`cursor_view.extraction.passes`. The
# import is placed AFTER ``_merge_global_composer_into_meta`` is defined
# because :mod:`cursor_view.extraction.passes.global_composers` pulls
# that helper back through this module's namespace, and resolving the
# name during Python's partially-initialized-module phase would fail
# if the ``def`` had not already executed.
from cursor_view.extraction.diagnostics import (
    diagnostics_enabled,
    dump_workspace_diagnostics,
)
from cursor_view.extraction.passes import (
    _apply_subagent_inheritance,
    _apply_uri_fallbacks,
    _collect_global_bubbles,
    _collect_global_composers,
    _collect_global_item_table_chats,
    _collect_workspace_messages,
    _finalize_sessions,
    _link_task_subagents_to_parents,
)


def extract_chats(
    cids: set[str] | None = None,
    cached_state: CachedExtractionState | None = None,
) -> list[Dict[str, Any]]:
    """Scan workspace and global Cursor databases and return chat sessions.

    Default call (``cids=None``) performs the full scan and returns
    every non-empty chat found -- unchanged from the original behavior,
    which the chat-index full-rebuild path depends on.

    When ``cids`` is provided, each pass restricts its SQL queries and
    message recording to that composer set, and ``cached_state`` supplies
    the slice of prior-run state (persisted ``tool_call_parent`` plus
    ancestor ``comp2ws`` / ``_inferred_project``) that Passes 5 and 6
    need for composers outside the dirty set. The returned list then
    contains only chats whose composerId is in ``cids``; the apply step
    in :mod:`cursor_view.chat_index` overwrites just those rows in the
    cache and leaves everyone else untouched.
    """
    root = cursor_root()
    logger.debug("Using Cursor root: %s", root)

    if diagnostics_enabled():
        dump_workspace_diagnostics(root)

    ws_proj: Dict[str, Dict[str, Any]] = {}
    comp_meta: Dict[str, Dict[str, Any]] = {}
    comp2ws: Dict[str, str] = {}
    sessions: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"messages": []})
    # URIs accumulated from global bubbles, used as a tertiary fallback for
    # composers that have no workspaceIdentifier and no composerData file refs.
    # Kept split so folder URIs (workspaceUris/attachedFolders) are not
    # mistakenly treated as files (whose last segment gets stripped).
    bubble_file_uris_by_cid: Dict[str, list[str]] = defaultdict(list)
    bubble_folder_uris_by_cid: Dict[str, list[str]] = defaultdict(list)
    # Maps subagent composerId -> parent composerId. Populated from each
    # composer's ``subagentInfo.parentComposerId`` so we can later inherit the
    # parent's workspace/project for subagents that have no workspace signal
    # of their own.
    subagent_parent: Dict[str, str] = {}
    # Maps bubble ``toolFormerData.toolCallId`` -> the composerId whose
    # bubble fired that tool. Used to reconstruct subagent parent links for
    # ``task-<toolCallId>`` composers that ship with ``subagentInfo: null``.
    tool_call_parent: Dict[str, str] = {}

    _collect_workspace_messages(root, ws_proj, comp_meta, comp2ws, sessions, cids=cids)

    global_db = global_storage_path(root)
    if global_db:
        logger.debug("Processing global storage: %s", global_db)
        # Read the canonical bubble order from each composer's
        # ``fullConversationHeadersOnly`` array BEFORE Pass 2 runs, so
        # Pass 2 can tag each bubble with its ordinal as it streams rows
        # out of the PK-ordered cursorDiskKV and produce messages in
        # Cursor's own turn order rather than alphabetical-bubbleId order.
        bubble_order_by_cid = build_bubble_order_map(global_db, cids=cids)
        _collect_global_bubbles(
            global_db,
            sessions,
            comp_meta,
            comp2ws,
            bubble_file_uris_by_cid,
            bubble_folder_uris_by_cid,
            tool_call_parent,
            bubble_order_by_cid,
            cids=cids,
        )
        _collect_global_composers(
            global_db,
            sessions,
            ws_proj,
            comp_meta,
            comp2ws,
            subagent_parent,
            cids=cids,
        )
        _apply_uri_fallbacks(
            sessions,
            comp2ws,
            bubble_file_uris_by_cid,
            bubble_folder_uris_by_cid,
        )
        # ``task_v2`` subagent composers ship with ``subagentInfo: null`` so
        # they have no explicit parent link. Reconstruct it from the parent
        # bubble's ``toolFormerData.toolCallId`` before running the generic
        # inheritance pass.
        _link_task_subagents_to_parents(
            sessions,
            subagent_parent,
            tool_call_parent,
            cached_tool_call_parent=(cached_state.tool_call_parent if cached_state else None),
        )
        _apply_subagent_inheritance(
            sessions,
            comp2ws,
            subagent_parent,
            ancestor_comp2ws=(cached_state.ancestor_comp2ws if cached_state else None),
            ancestor_inferred_project=(
                cached_state.ancestor_inferred_project if cached_state else None
            ),
        )
        _collect_global_item_table_chats(global_db, sessions, comp_meta, comp2ws, cids=cids)

    return _finalize_sessions(sessions, ws_proj, comp2ws, comp_meta, cids=cids)
