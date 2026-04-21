"""Pass 1: scan workspace DBs for project metadata and ItemTable messages."""

from __future__ import annotations

import logging
import pathlib
from typing import Any, Dict

from cursor_view.paths import workspaces
from cursor_view.projects import workspace_info
from cursor_view.sources.item_table import iter_chat_from_item_table

logger = logging.getLogger(__name__)


def _collect_workspace_messages(
    root: pathlib.Path,
    ws_proj: Dict[str, Dict[str, Any]],
    comp_meta: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    sessions: Dict[str, Dict[str, Any]],
    cids: set[str] | None = None,
) -> None:
    """Pass 1: scan workspace DBs for project metadata and ItemTable messages.

    Populates ``ws_proj`` / ``comp_meta`` / ``comp2ws`` / ``sessions`` in
    place. Composers seen only in the workspace ItemTable (no prior
    metadata entry) get a synthetic ``Chat <id-prefix>`` title so they
    still surface in the UI.

    When ``cids`` is given, the pass still runs ``workspace_info`` on
    every workspace (so ``ws_proj`` stays complete for ancestor lookups
    in Pass 6), but message recording and synthetic meta seeding in
    ``sessions`` are restricted to cids in the dirty set. Populating
    ``comp_meta`` / ``comp2ws`` for every seen cid remains correct
    because those dicts are additive and the callers only serialize the
    dirty subset.
    """
    logger.debug("Processing workspace databases...")
    ws_count = 0
    for ws_id, db in workspaces(root):
        ws_count += 1
        logger.debug("Processing workspace %s - %s", ws_id, db)
        proj, meta = workspace_info(db)
        ws_proj[ws_id] = proj
        for cid, m in meta.items():
            comp_meta[cid] = m
            comp2ws[cid] = ws_id

        msg_count = 0
        for cid, role, text, db_path in iter_chat_from_item_table(db):
            if cids is not None and cid not in cids:
                continue
            sessions[cid]["messages"].append({"role": role, "content": text})
            if "db_path" not in sessions[cid]:
                sessions[cid]["db_path"] = db_path
            msg_count += 1
            if cid not in comp_meta:
                comp_meta[cid] = {"title": f"Chat {cid[:8]}", "createdAt": None, "lastUpdatedAt": None}
                comp2ws[cid] = ws_id
        logger.debug("  - Extracted %s messages from workspace %s", msg_count, ws_id)

    logger.debug("Processed %s workspaces", ws_count)
