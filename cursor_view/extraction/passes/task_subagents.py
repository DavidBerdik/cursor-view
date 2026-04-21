"""Pass 5: reconstruct ``task-<toolCallId>`` subagent -> parent links."""

from __future__ import annotations

from typing import Any, Dict

# Cursor names every ``task_v2``-spawned subagent composer ``task-<toolCallId>``
# where ``<toolCallId>`` is the parent bubble's ``toolFormerData.toolCallId``.
# This convention was observed empirically across a real Cursor install; it is
# the only durable link back to the parent when Cursor persists the subagent
# with ``subagentInfo: null`` (which is the current behavior). Pass 5 strips
# this prefix to look up the parent in ``tool_call_parent``.
_TASK_CID_PREFIX = "task-"


def _link_task_subagents_to_parents(
    sessions: Dict[str, Dict[str, Any]],
    subagent_parent: Dict[str, str],
    tool_call_parent: Dict[str, str],
    cached_tool_call_parent: Dict[str, str] | None = None,
) -> None:
    """Pass 5: map ``task-<toolCallId>`` composers to the parent that fired the tool.

    Some subagent composers are persisted with ``subagentInfo: null`` (seen
    on ``task_v2``-spawned composers), so ``_apply_subagent_inheritance``
    finds no link. Their composerId is always ``"task-" + toolCallId``,
    and the parent's bubble carries the same ``toolCallId`` in
    ``toolFormerData``. Combine the two to recover the parent link so the
    subsequent inheritance pass can attach the parent's workspace.

    This pass is a dedicated seam rather than part of Pass 3 or Pass 6
    because of where the two halves of its input live: Pass 3 walks
    ``composerData`` and never sees bubble ``toolFormerData``, so it
    cannot populate ``tool_call_parent`` itself, while Pass 6 expects
    ``subagent_parent`` to be final before it walks. Pass 2 already
    builds ``tool_call_parent`` cheaply as a side-effect of its bubble
    iteration, so this pass only has to do an O(sessions) dict join,
    not a second O(bubbles) scan.

    In scoped mode, the in-memory ``tool_call_parent`` only covers
    dirty composers' bubbles. ``cached_tool_call_parent`` -- the
    persisted map from the chat-index cache -- fills in the rest, with
    the in-memory map winning on conflict so fresh entries from a
    rescanned parent override stale cached ones.
    """
    merged_map = tool_call_parent
    if cached_tool_call_parent:
        merged_map = dict(cached_tool_call_parent)
        merged_map.update(tool_call_parent)
    # Guard against ``subagent_parent[cid]`` being preset (e.g. genuine
    # ``subagentInfo.parentComposerId`` from Pass 3) so authentic links win
    # over reconstructed ones in the rare case both are present for the
    # same composer.
    for cid in sessions.keys():
        if not cid.startswith(_TASK_CID_PREFIX):
            continue
        if cid in subagent_parent:
            continue
        tcid = cid[len(_TASK_CID_PREFIX):]
        parent = merged_map.get(tcid)
        if parent and parent != cid:
            subagent_parent[cid] = parent
