"""Apply-time gate for ``task-<toolCallId>`` subagent dirty-set propagation.

Mirrors the diff side's :mod:`cursor_view.cache.diff.propagation` split:
the diff is read-only and does NOT walk the subagent-parent chain;
that walk happens here, gated on real project-resolution shifts (or
parent deletion / ``tool_call_parent`` edge churn). The over-broad
"every dirty parent's task-* descendants" form of this walk is what
produced the lopsided "23242 modified (inserted 505, 22737
subagent-propagated)" refresh logs the gate was introduced to fix.

Public-shape helpers (all underscore-prefixed because they are
package-private to :mod:`cursor_view.cache.delta`):

- :func:`_snapshot_cached_project` -- snapshot
  ``(workspace_id, project_name, project_root_path)`` from
  ``chat_summary`` for the directly-modified set, taken BEFORE the
  primary writes clear those rows.
- :func:`_apply_secondary_pass` -- compute project-shifted parents,
  build the trigger set, walk descendants, augment cached state with
  freshly-written primary projects, run scoped extraction, and write
  the secondary chats inside the same ``BEGIN IMMEDIATE`` transaction
  the caller already opened.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable

from cursor_view.cache.delta.composer_rows import (
    _GLOBAL_WS,
    _apply_chat_writes,
)
from cursor_view.cache.diff import DirtySet
from cursor_view.cache.diff.propagation import _propagate_subagent_dirtiness
from cursor_view.extraction import CachedExtractionState, extract_chats

# SQLite's default ``SQLITE_MAX_VARIABLE_NUMBER`` cap on bound parameters
# per statement. The ``chat_summary`` IN-list snapshot of cached project
# tuples chunks under this so a 23k-cid refresh never trips the cap.
_SQLITE_MAX_VARIABLE_NUMBER = 999


def _project_tuple_from_formatted(
    formatted: dict[str, Any],
) -> tuple[str, str, str]:
    """Return the ``(workspace_id, project_name, project_root_path)`` triple a chat would write to ``chat_summary``.

    Mirrors the exact ``or``-fallback chain used in
    :func:`cursor_view.chat_index.rows._insert_chat`. Computing the
    triple identically on both sides of the comparison is what lets
    the project-shift detector trust an equality check; otherwise a
    chat with ``workspace_id=""`` and a chat with ``workspace_id=None``
    would compare as different even though their cached rows are
    byte-identical.
    """
    project = formatted.get("project") or {}
    return (
        formatted.get("workspace_id") or "unknown",
        project.get("name") or "Unknown Project",
        project.get("rootPath") or "Unknown",
    )


def _snapshot_cached_project(
    cur: sqlite3.Cursor, cids: set[str]
) -> dict[str, tuple[str, str, str]]:
    """Snapshot ``(workspace_id, project_name, project_root_path)`` for ``cids`` from ``chat_summary``.

    Must run BEFORE the modified-cids loop calls
    ``_delete_cid_rows``, which clears ``chat_summary`` for those
    ids; afterwards the post-extraction comparison would have nothing
    to compare against. The IN-list is chunked under
    :data:`_SQLITE_MAX_VARIABLE_NUMBER` so a refresh whose dirty set
    exceeds SQLite's bound-parameter cap still completes in one
    helper call.
    """
    out: dict[str, tuple[str, str, str]] = {}
    if not cids:
        return out
    cid_list = list(cids)
    for start in range(0, len(cid_list), _SQLITE_MAX_VARIABLE_NUMBER):
        chunk = cid_list[start : start + _SQLITE_MAX_VARIABLE_NUMBER]
        placeholders = ",".join("?" * len(chunk))
        cur.execute(
            "SELECT session_id, workspace_id, project_name, project_root_path "
            f"FROM chat_summary WHERE session_id IN ({placeholders})",
            chunk,
        )
        for row in cur.fetchall():
            out[row[0]] = (row[1], row[2], row[3])
    return out


def _compute_propagation_triggers(
    project_shifted: set[str],
    dirty: DirtySet,
    raw_cached_tcp: dict[str, str],
) -> tuple[set[str], set[str]]:
    """Assemble the apply-time triggers for the gated subagent walk.

    Returns ``(walk_starts, direct_cids)`` matching the two
    parameters of
    :func:`cursor_view.cache.diff.propagation._propagate_subagent_dirtiness`.
    The split keeps the two trigger semantics distinct: ``walk_starts``
    cids are NOT themselves added to the secondary set (project-shifted
    parents are already extracted by the primary pass; deleted parents
    have no row to write), while ``direct_cids`` ARE (an edge-churn
    ``task-<tcid>`` child must re-extract because its inheritance
    chain shifted, even though no row of the child itself was hashed
    as dirty).

    Three trigger classes, each chosen because Pass 6's inheritance
    walk will produce a different answer for any descendant after
    this refresh:

    - **project-shifted parents** (``walk_starts``) -- a directly-
      modified parent whose post-extraction ``chat_summary`` triple
      differs from the cached row; every ``task-<toolCallId>``
      descendant inheriting from it must re-resolve.
    - **deleted parents** (``walk_starts``) -- a vanished cid means
      descendants lose their inheritance anchor and must walk further
      up the chain (or fall back to ``(global)``).
    - **edge-churn children** (``direct_cids``) -- ``task-<tcid>``
      whose cached ``tool_call_parent`` entry differs from the staged
      update (new edge, rewired parent, or removed edge). The parent
      itself is NOT added; folding the parent in would re-fire the
      over-broad "every parent's task-* descendants" walk this gate
      exists to avoid (the unchanged sibling subagent stays out).
    """
    walk_starts: set[str] = set(project_shifted) | set(dirty.deleted_cids)
    direct_cids: set[str] = set()
    for tcid, parent in dirty.tool_call_parent_updates.items():
        cached_parent = raw_cached_tcp.get(tcid)
        if cached_parent != parent:
            # TODO: When ``task-<tcid>`` is BOTH directly dirty (its
            # own bubble or composerData rows changed hash) AND has
            # an edge-churn entry here, the cid is processed twice
            # in one apply transaction -- once by the primary
            # ``_apply_chat_writes`` loop iterating
            # ``dirty.modified_cids``, then again by the secondary
            # loop after this trigger adds it to ``direct_cids`` and
            # ``_propagate_subagent_dirtiness`` folds it into
            # ``secondary_cids``. Both passes write the same content
            # rows, so the final cache state is correct; the cost is
            # one extra ``_delete_cid_rows`` + ``insert_chat`` +
            # ``_upsert_composer_state`` cycle per overlapping cid.
            # Hits frequently for first-time ``task_v2`` spawns
            # where the parent's tool-call bubble and the
            # subagent's own bubbles are both new in the same
            # refresh window. Output is correct so this is a plain
            # ``TODO:`` per ``.cursor/rules/known-bugs.mdc``, not
            # a ``TODO(bug):``; a future cleanup could skip the
            # ``add`` when ``f"task-{tcid}" in dirty.modified_cids``
            # without changing observable behavior.
            direct_cids.add(f"task-{tcid}")
    return walk_starts, direct_cids


def _augment_cached_state_for_secondary(
    base: CachedExtractionState,
    primary_formatted: dict[str, dict[str, Any]],
) -> CachedExtractionState:
    """Reseed ancestor maps with freshly-written primary projects.

    :func:`cursor_view.cache.delta.cached_state._load_ancestor_state`
    builds the ancestor maps with the original
    ``dirty.modified_cids | dirty.deleted_cids`` set explicitly
    excluded, on the principle that those rows are about to change.
    Once the primary writes have landed, however, the secondary
    extraction's Pass 6 needs to walk into those same primary
    parents to inherit their *new* project. Reseed the maps mirroring
    exactly what :func:`_upsert_composer_state` and
    :func:`cursor_view.chat_index.rows._insert_chat` just wrote, so
    Pass 6 sees the same shape it would have seen if the apply path
    were a single combined extraction (which the pre-gating code in
    fact was).
    """
    augmented_comp2ws = dict(base.ancestor_comp2ws)
    augmented_inferred = dict(base.ancestor_inferred_project)
    for cid, formatted in primary_formatted.items():
        ws_id = formatted.get("workspace_id") or _GLOBAL_WS
        augmented_comp2ws[cid] = ws_id
        if ws_id != _GLOBAL_WS:
            augmented_inferred.pop(cid, None)
            continue
        project = formatted.get("project") or {}
        project_name = project.get("name") or ""
        if not project_name or project_name == "(unknown)":
            augmented_inferred.pop(cid, None)
            continue
        augmented_inferred[cid] = {
            "name": project_name,
            "rootPath": project.get("rootPath") or "(unknown)",
        }
    return CachedExtractionState(
        tool_call_parent=base.tool_call_parent,
        ancestor_comp2ws=augmented_comp2ws,
        ancestor_inferred_project=augmented_inferred,
        raw_cached_tool_call_parent=base.raw_cached_tool_call_parent,
    )


def _extract_secondary_chats(
    secondary_cids: set[str], cached_state: CachedExtractionState
) -> dict[str, dict[str, Any]]:
    """Run scoped extraction over the propagated subagent set, keyed by composerId.

    Mirrors :func:`cursor_view.cache.delta.composer_rows._extract_modified_chats`
    but for the apply-time secondary frontier. Composers whose fresh
    extraction yields no messages are filtered out by
    ``_finalize_sessions`` and never appear in the returned dict; the
    caller treats that as "delete the cached rows and move on".
    """
    if not secondary_cids:
        return {}
    extracted = extract_chats(cids=set(secondary_cids), cached_state=cached_state)
    out: dict[str, dict[str, Any]] = {}
    for chat in extracted:
        cid = (chat.get("session") or {}).get("composerId")
        if cid:
            out[cid] = chat
    return out


def _apply_secondary_pass(
    cur: sqlite3.Cursor,
    dirty: DirtySet,
    cached_state: CachedExtractionState,
    primary_formatted: dict[str, dict[str, Any]],
    cached_proj: dict[str, tuple[str, str, str]],
    insert_chat: Callable[
        [sqlite3.Cursor, dict[str, Any], bool],
        tuple[dict[str, Any], list[dict[str, Any]]],
    ],
    fts_enabled: bool,
) -> tuple[set[str], int, set[str]]:
    """Detect project shifts, propagate, secondary-extract, and write.

    Single named pass that owns the entire apply-time gate flow.
    Comparison of ``cached_proj`` (snapshot taken before the primary
    writes) against the post-write ``primary_formatted`` produces the
    project-shifted set, which feeds
    :func:`_compute_propagation_triggers` alongside
    ``dirty.deleted_cids`` and the staged
    ``tool_call_parent_updates``. The walk in
    :func:`cursor_view.cache.diff.propagation._propagate_subagent_dirtiness`
    expands triggers up to ``_MAX_PARENT_DEPTH`` hops, augments the
    cached state with freshly-written primary projects so Pass 6 of
    the secondary extraction can walk into a primary parent and
    inherit its *new* project, and applies the
    delete-then-insert-then-upsert loop. Returns
    ``(secondary_cids, secondary_inserted, project_shifted)`` so the
    caller folds those counters into the refresh log alongside the
    primary inserted count. An empty trigger set short-circuits
    before extraction so the common case (no project shifts, no edge
    churn, no deletions) pays nothing for the gate.
    """
    # TODO(bug): A cid in ``dirty.modified_cids`` whose primary
    # extraction returns no chat (``new_chats.get(cid) is None`` --
    # e.g. every bubble in ``cursorDiskKV`` was filtered out by the
    # ``composerData.fullConversationHeadersOnly`` orphan invariant
    # in ``cursor_view/cache/diff/global_db.py`` and the composer
    # has no ``conversation`` array, so ``_finalize_sessions`` drops
    # the session for empty messages) gets its ``chat_summary`` row
    # deleted by ``_apply_chat_writes`` but never lands in
    # ``primary_formatted``. ``project_shifted`` only iterates
    # ``primary_formatted.items()``, so the cid never enters
    # ``walk_starts`` -- and because the cid is in ``modified_cids``
    # rather than ``deleted_cids`` (its source-row snapshot still
    # holds at least one row, e.g. an unchanged pane-view key in a
    # workspace ``ItemTable``), the deleted-parent trigger arm
    # misses it too. ``task-<toolCallId>`` subagent descendants of
    # this "soft-deleted" parent therefore keep the parent's
    # now-stale project in ``chat_summary`` (and in
    # ``composer_state``) until something else dirties them.
    # Suspected cause: the trigger set assembled below treats
    # "extraction yielded a chat with a different project" and
    # "extraction yielded no chat at all" as different cases, but
    # both functionally remove the parent's row from the inheritable
    # set. Folding ``set(dirty.modified_cids) - set(primary_formatted)``
    # into ``walk_starts`` would close the gap. The pre-gating code
    # covered this case incidentally because every directly-dirty
    # parent's descendants propagated regardless.
    project_shifted = {
        cid
        for cid, formatted in primary_formatted.items()
        if cached_proj.get(cid) != _project_tuple_from_formatted(formatted)
    }
    walk_starts, direct_cids = _compute_propagation_triggers(
        project_shifted, dirty, cached_state.raw_cached_tool_call_parent,
    )
    secondary_cids = _propagate_subagent_dirtiness(
        dirty, cached_state.tool_call_parent, walk_starts, direct_cids,
    )
    if not secondary_cids:
        return set(), 0, project_shifted
    secondary_state = _augment_cached_state_for_secondary(
        cached_state, primary_formatted,
    )
    secondary_chats = _extract_secondary_chats(secondary_cids, secondary_state)
    secondary_inserted, _ = _apply_chat_writes(
        cur, secondary_cids, secondary_chats, insert_chat, fts_enabled,
    )
    return secondary_cids, secondary_inserted, project_shifted
