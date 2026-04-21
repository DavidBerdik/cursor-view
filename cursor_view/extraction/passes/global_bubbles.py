"""Pass 2: extract per-bubble messages + URIs from the global cursorDiskKV."""

from __future__ import annotations

import logging
import pathlib
from collections import defaultdict
from typing import Any, Dict

from cursor_view.sources.bubbles import (
    iter_bubbles_for_cids,
    iter_bubbles_from_disk_kv,
)

logger = logging.getLogger(__name__)

# Sentinel ordinal for bubbles whose bubbleId is absent from the composer's
# ``fullConversationHeadersOnly`` array (legacy builds, or a bubble written
# after the composerData snapshot we read). Chosen much larger than any real
# ordinal so unmapped bubbles sort to the END of the per-cid bucket while
# still preserving encountered-order within the unmapped tail. Kept a
# plain int (not ``math.inf``) so (ordinal, seq) tuples stay comparable
# under the stdlib's ordering rules.
_UNMAPPED_BUBBLE_ORDINAL = 10**9


def _collect_global_bubbles(
    global_db: pathlib.Path,
    sessions: Dict[str, Dict[str, Any]],
    comp_meta: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    bubble_file_uris_by_cid: Dict[str, list[str]],
    bubble_folder_uris_by_cid: Dict[str, list[str]],
    tool_call_parent: Dict[str, str],
    bubble_order_by_cid: Dict[str, Dict[str, int]],
    cids: set[str] | None = None,
) -> None:
    """Pass 2: extract per-bubble messages + URIs from the global cursorDiskKV.

    Always records ``db_path``, composer meta, and URIs for every bubble
    we see, even for text-less ones, so later project inference can still
    work from ``workspaceUris`` attached to empty assistant bubbles.
    Also records ``toolCallId -> parent composerId`` for every tool-call
    bubble so ``_link_task_subagents_to_parents`` can recover subagent
    parent links that Cursor no longer stores on the subagent itself.

    ``cursorDiskKV`` returns ``bubbleId:*`` rows in primary-key (key-string)
    order, which is effectively random for the UUIDv4 bubbleIds Cursor
    uses. Appending messages in that order scrambles the chronological
    turn order and makes ``coalesce_consecutive_messages_by_role`` merge
    unrelated user prompts.     ``bubble_order_by_cid`` -- the
    ``{cid -> {bubbleId -> ordinal}}`` map produced by
    :func:`cursor_view.sources.composer_data.build_bubble_order_map`
    from each composer's ``composerData.fullConversationHeadersOnly`` --
    supplies Cursor's own canonical ordering. Messages are accumulated
    per cid tagged with their ordinal and sorted before being appended
    to ``sessions[cid]["messages"]``, so the final list matches the
    order the user actually saw the turns in. Bubbles whose bubbleId
    is missing from the map (legacy builds, or a bubble written after
    the composerData snapshot we read) fall to the end of the per-cid
    list in encountered order -- the exact fallback
    ``fullConversationHeadersOnly`` is designed to make rare.

    When ``cids`` is given, bubbles are fetched via
    :func:`iter_bubbles_for_cids` so only rows in the dirty set are
    read -- a PK-range scan per cid instead of the full-table scan.
    The in-memory ``tool_call_parent`` built here only covers dirty
    composers; Pass 5 merges in the cached map for the rest.
    """
    if cids is not None:
        bubble_iter = iter_bubbles_for_cids(global_db, cids)
    else:
        bubble_iter = iter_bubbles_from_disk_kv(global_db)
    # Per-cid ordered message buckets populated from the bubble stream.
    # Each entry is (ordinal, sequence, message_dict): ``ordinal`` comes
    # from the headers array (or ``_UNMAPPED_BUBBLE_ORDINAL`` for bubbles
    # not listed there) and ``sequence`` is the encounter order used as
    # a stable tiebreaker so bubbles with identical ordinals preserve the
    # order the iterator yielded them.
    messages_by_cid: Dict[str, list[tuple[int, int, dict]]] = defaultdict(list)
    msg_count = 0
    seq = 0
    for cid, bubble_id, role, text, db_path, file_uris, folder_uris, tool_call in bubble_iter:
        if "db_path" not in sessions[cid]:
            sessions[cid]["db_path"] = db_path
        if file_uris:
            bubble_file_uris_by_cid[cid].extend(file_uris)
        if folder_uris:
            bubble_folder_uris_by_cid[cid].extend(folder_uris)
        if tool_call is not None:
            tcid, _name = tool_call
            # Cursor stamps each tool invocation with the upstream model
            # provider's tool-call id (e.g. Anthropic's ``toolu_*``, OpenAI's
            # ``call_*``). These are unique per model invocation, so a
            # collision here would indicate a bubble replay or storage
            # anomaly; first-seen wins for determinism.
            tool_call_parent.setdefault(tcid, cid)
        if cid not in comp_meta:
            comp_meta[cid] = {"title": f"Chat {cid[:8]}", "createdAt": None, "lastUpdatedAt": None}
            comp2ws[cid] = "(global)"
        if not text:
            continue
        ordinal_map = bubble_order_by_cid.get(cid) or {}
        ordinal = ordinal_map.get(bubble_id, _UNMAPPED_BUBBLE_ORDINAL)
        messages_by_cid[cid].append((ordinal, seq, {"role": role, "content": text}))
        seq += 1
        msg_count += 1

    # Pass 1 workspace-ItemTable messages (if any) stay at the head of
    # sessions[cid]["messages"]; this matches the prior "Pass 1 before
    # Pass 2" ordering for composers that appear in both stores, while
    # reordering Pass 2's contribution into Cursor's canonical turn order.
    for cid, bucket in messages_by_cid.items():
        bucket.sort(key=lambda item: (item[0], item[1]))
        sessions[cid]["messages"].extend(msg for _ord, _s, msg in bucket)

    logger.debug("  - Extracted %s messages from global cursorDiskKV bubbles", msg_count)
