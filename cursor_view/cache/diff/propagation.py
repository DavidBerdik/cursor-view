"""Post-hash passes: deletion classification, subagent propagation, observability trim."""

from __future__ import annotations

from cursor_view.cache.diff.types import DirtySet, SourceKey

# Mirrors _MAX_PARENT_DEPTH in cursor_view/extraction/passes/subagent_inheritance.py
# so dirty-set propagation stops where ``_apply_subagent_inheritance`` would.
_MAX_PARENT_DEPTH = 8


def _process_deletions(
    cached: dict[SourceKey, tuple[str, str]],
    dirty: DirtySet,
) -> None:
    """Split cached rows that vanished from the new snapshot into modified vs deleted.

    A composer whose cached source rows are all missing from the new
    snapshot lands in ``deleted_cids``; one with some rows still present
    lands in ``modified_cids`` so scoped re-extraction runs and
    ``_finalize_sessions`` decides whether to drop it.
    """
    cids_with_new_rows: set[str] = {
        rec.composer_id
        for rec in dirty.source_row_snapshot.values()
        if rec.composer_id
    }
    cids_missing: set[str] = set()
    for sk, (_hash, composer_id) in cached.items():
        if sk.db_path in dirty.unreadable_db_paths:
            # Source unreadable this pass -> we have no snapshot to compare,
            # so preserve its cached chats rather than treating the empty
            # snapshot as "everything deleted".
            continue
        if sk in dirty.source_row_snapshot:
            continue
        if composer_id:
            cids_missing.add(composer_id)
    for cid in cids_missing:
        if cid in cids_with_new_rows:
            dirty.modified_cids.add(cid)
        else:
            dirty.deleted_cids.add(cid)


def _propagate_subagent_dirtiness(
    dirty: DirtySet,
    merged_tcp: dict[str, str],
    walk_starts: set[str],
    direct_cids: set[str] | None = None,
) -> set[str]:
    """Fold ``task-<toolCallId>`` descendants of trigger cids into ``modified_cids``.

    Runs at apply-time (from
    :mod:`cursor_view.cache.delta.propagation`) rather than during
    the diff. The trigger set splits across two parameters because
    the two trigger sources have opposite semantics for the frontier
    cids themselves:

    - ``walk_starts`` -- cids whose **descendants** must re-extract
      but who do **not** themselves need to land in the secondary
      set. Project-shifted parents and deleted parents go here:
      project-shifted parents are already in the primary
      ``_apply_chat_writes`` loop (re-extracting them in the
      secondary pass would do the same work twice), and deleted
      parents have no row left to write.
    - ``direct_cids`` -- cids that **themselves** must re-extract
      (and whose descendants must follow). Edge-churn ``task-<tcid>``
      children go here: a new or rewired ``tool_call_parent`` entry
      means the named subagent's inheritance chain just shifted, so
      the subagent itself has to ride the secondary scoped
      extraction. The walk also expands from each direct cid in
      case it has its own descendants.

    The narrow trigger set is the whole point of the apply-time
    gating: the previous "every dirty parent's descendants" form of
    this walk folded tens of thousands of unchanged subagents into
    ``modified_cids`` on every refresh because Cursor bumps
    ``lastUpdatedAt`` and rewrites bubble JSON for navigation-only
    events that leave Pass 6's inheritance answer untouched.

    ``merged_tcp`` is the post-update view of ``tool_call_parent``
    (cache map merged with ``dirty.tool_call_parent_updates``) so a
    first-time tool-call bubble's child is reachable on the same
    refresh that recorded the edge.

    Walks outward via a reverse index keyed by parent, bounded by
    :data:`_MAX_PARENT_DEPTH` so the propagation budget matches
    ``_apply_subagent_inheritance``. A ``visited`` set guards against
    cycles that malformed data could introduce. Cids added to the
    secondary set (``direct_cids`` plus walked descendants) are also
    folded into ``dirty.modified_cids`` and
    ``dirty.subagent_propagated_cids`` so the refresh log's
    link-driven-dirtiness counter and the apply step's downstream
    iteration both see the updated set.
    """
    secondary_cids: set[str] = set()
    direct = direct_cids or set()
    if not walk_starts and not direct:
        return secondary_cids
    # ``direct_cids`` need to ride the secondary scoped extraction
    # regardless of whether ``merged_tcp`` has any entries left -- a
    # parent deletion drops every ``tool_call_parent`` row pointing
    # at it (compute_source_diff stages the deletes inline), so by
    # the time we get here ``merged_tcp`` may have already been
    # emptied of the very edges that triggered this propagation. The
    # direct-cid pass below adds them up front; the descendant walk
    # only runs when we still have a non-empty tcp map to traverse.
    for cid in direct:
        if not cid:
            continue
        secondary_cids.add(cid)
        dirty.modified_cids.add(cid)
        dirty.subagent_propagated_cids.add(cid)
    if not merged_tcp:
        return secondary_cids
    by_parent: dict[str, list[str]] = {}
    for tcid, parent in merged_tcp.items():
        by_parent.setdefault(parent, []).append(f"task-{tcid}")
    frontier = [cid for cid in set(walk_starts) | set(direct) if cid]
    visited: set[str] = set(frontier)
    depth = 0
    while frontier and depth < _MAX_PARENT_DEPTH:
        next_frontier: list[str] = []
        for parent in frontier:
            for child in by_parent.get(parent, ()):
                if child in visited:
                    continue
                visited.add(child)
                dirty.modified_cids.add(child)
                dirty.subagent_propagated_cids.add(child)
                secondary_cids.add(child)
                next_frontier.append(child)
        frontier = next_frontier
        depth += 1
    return secondary_cids


def _trim_comp2ws_observability(dirty: DirtySet) -> None:
    """Drop cids from ``workspace_comp2ws_dirty`` that didn't ultimately land in the dirty set."""
    for ws_id in list(dirty.workspace_comp2ws_dirty.keys()):
        dirty.workspace_comp2ws_dirty[ws_id] = {
            cid
            for cid in dirty.workspace_comp2ws_dirty[ws_id]
            if cid in dirty.modified_cids
        }
        if not dirty.workspace_comp2ws_dirty[ws_id]:
            del dirty.workspace_comp2ws_dirty[ws_id]
