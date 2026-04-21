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
        if sk in dirty.source_row_snapshot:
            continue
        if composer_id:
            cids_missing.add(composer_id)
    for cid in cids_missing:
        if cid in cids_with_new_rows:
            dirty.modified_cids.add(cid)
        else:
            dirty.deleted_cids.add(cid)


def _propagate_subagent_dirtiness(dirty: DirtySet, cached_tcp: dict[str, str]) -> None:
    """Fold every ``task-<toolCallId>`` descendant of a dirty parent into ``modified_cids``.

    Walks outward from each dirty parent via a reverse index built from
    the cached ``tool_call_parent`` map, bounded by
    :data:`_MAX_PARENT_DEPTH` so the propagation budget matches
    ``_apply_subagent_inheritance``. A ``visited`` set guards against
    cycles that malformed data could introduce. Propagated children
    are additionally recorded in :attr:`DirtySet.subagent_propagated_cids`
    so the apply step can log link-driven dirtiness separately from the
    content-driven set.
    """
    if not cached_tcp:
        return
    by_parent: dict[str, list[str]] = {}
    for tcid, parent in cached_tcp.items():
        by_parent.setdefault(parent, []).append(f"task-{tcid}")
    frontier = list(dirty.modified_cids | dirty.deleted_cids)
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
                next_frontier.append(child)
        frontier = next_frontier
        depth += 1


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
