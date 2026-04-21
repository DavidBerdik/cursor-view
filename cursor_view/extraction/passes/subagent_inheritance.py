"""Pass 6: walk the subagent parent chain so children inherit a project."""

from __future__ import annotations

from typing import Any, Dict

# Cap the inheritance walk so a pathological cycle (e.g. a subagent whose
# ``subagentInfo`` points at itself through a surviving ancestor chain)
# can't spin forever. Eight is already more than any real chain we've
# observed; the walk also short-circuits on the first resolved ancestor.
_MAX_PARENT_DEPTH = 8


def _apply_subagent_inheritance(
    sessions: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    subagent_parent: Dict[str, str],
    ancestor_comp2ws: Dict[str, str] | None = None,
    ancestor_inferred_project: Dict[str, Dict[str, Any]] | None = None,
) -> None:
    """Pass 6: make subagent composers inherit a resolved ancestor's project.

    Subagent composers (e.g. ``explore`` tasks) are spawned with no
    ``workspaceIdentifier``, no attached-file URIs, and no URIs in their
    bubbles, so they need a parent's workspace to fall back on. By the
    time this pass runs, ``subagent_parent`` has been populated from two
    sources:

    - (a) Authentic ``subagentInfo.parentComposerId`` entries recorded
      by ``_collect_global_composers`` (Pass 3).
    - (b) Reconstructed ``task-<toolCallId> -> parent_cid`` entries
      recorded by ``_link_task_subagents_to_parents`` (Pass 5) for
      composers persisted with ``subagentInfo: null`` (``task_v2``
      subagents on current Cursor builds).

    Both kinds are treated identically: walk the parent chain up to
    ``_MAX_PARENT_DEPTH`` hops and inherit the first resolved ancestor's
    workspace or inferred project. Ordering invariants: must run AFTER
    every other project-resolution pass so ancestor state is final, and
    AFTER Pass 5 so its synthetic entries are visible to the walk.

    In scoped mode, ancestors that weren't part of the dirty set have
    no ``comp2ws`` / ``_inferred_project`` entries of their own because
    the earlier passes skipped them. ``ancestor_comp2ws`` and
    ``ancestor_inferred_project`` -- the cache's view of those
    composers -- are consulted only after the current run's dicts
    miss, so freshly computed ancestor state always wins over cached.
    """
    for child_cid, first_parent in subagent_parent.items():
        if comp2ws.get(child_cid) not in (None, "(global)"):
            continue
        if sessions.get(child_cid, {}).get("_inferred_project"):
            continue
        visited: set[str] = {child_cid}
        ancestor = first_parent
        depth = 0
        while ancestor and ancestor not in visited and depth < _MAX_PARENT_DEPTH:
            visited.add(ancestor)
            ancestor_ws = comp2ws.get(ancestor)
            if ancestor_ws is None and ancestor_comp2ws is not None:
                ancestor_ws = ancestor_comp2ws.get(ancestor)
            if ancestor_ws and ancestor_ws != "(global)":
                comp2ws[child_cid] = ancestor_ws
                break
            ancestor_project = sessions.get(ancestor, {}).get("_inferred_project")
            if ancestor_project is None and ancestor_inferred_project is not None:
                ancestor_project = ancestor_inferred_project.get(ancestor)
            if ancestor_project:
                sessions[child_cid]["_inferred_project"] = ancestor_project
                break
            ancestor = subagent_parent.get(ancestor)
            depth += 1
