"""Pass 3: extract composerData conversations, merge meta, resolve workspaces."""

from __future__ import annotations

import logging
import pathlib
from typing import Any, Dict

from cursor_view.projects import (
    project_from_global_composer_files,
    project_from_workspace_identifier,
)
from cursor_view.sources.composer_data import (
    iter_composer_data,
    iter_composer_data_for_cids,
)

logger = logging.getLogger(__name__)


def _collect_global_composers(
    global_db: pathlib.Path,
    sessions: Dict[str, Dict[str, Any]],
    ws_proj: Dict[str, Dict[str, Any]],
    comp_meta: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    subagent_parent: Dict[str, str],
    cids: set[str] | None = None,
) -> None:
    """Pass 3: extract composerData conversations, merge meta, resolve workspaces.

    For each composer:

    - Remember the ``subagentInfo.parentComposerId`` link so subagents
      (e.g. ``explore`` tasks) can inherit a parent's project later.
    - Adopt the composer's ``name`` / timestamps as metadata if we don't
      already have workspace-scoped metadata for this composer.
    - Attempt to associate the composer with a real workspace via
      ``workspaceIdentifier`` first, then fall back to
      ``_project_from_global_composer_files``. Only override when the
      current mapping is ``(global)``/absent, so workspace-scoped
      associations from the earlier workspace pass win.
    - Append every non-empty message from ``data.conversation`` as a
      user/assistant message in ``sessions[cid]``.

    When ``cids`` is given, composer rows are fetched via
    :func:`iter_composer_data_for_cids` (batched IN query on the
    primary key) instead of the full-table LIKE scan.
    """
    # Imported here (rather than at module top) to avoid a circular
    # import: ``core`` depends on the passes at module load, so
    # resolving ``_merge_global_composer_into_meta`` through ``core``
    # is done lazily inside this function where ``core`` is guaranteed
    # to have finished executing its body.
    from cursor_view.extraction.core import _merge_global_composer_into_meta

    if cids is not None:
        composer_iter = iter_composer_data_for_cids(global_db, cids)
    else:
        composer_iter = iter_composer_data(global_db)
    comp_count = 0
    for cid, data, db_path in composer_iter:
        # Subagents (e.g. type "explore") are spawned without their own
        # workspaceIdentifier or attached-file URIs, so none of the
        # standard resolution paths find a project for them; record the
        # parent link here so a later pass can inherit.
        si = data.get("subagentInfo") if isinstance(data, dict) else None
        if isinstance(si, dict):
            pcid = si.get("parentComposerId")
            if isinstance(pcid, str) and pcid and pcid != cid:
                subagent_parent[cid] = pcid

        created_at = data.get("createdAt")
        last_updated = data.get("lastUpdatedAt")
        if last_updated is None:
            last_updated = created_at
        name = data.get("name")
        if isinstance(name, str) and name.strip():
            use_title = name.strip()
        else:
            use_title = f"Chat {cid[:8]}"

        if cid not in comp_meta:
            comp_meta[cid] = {
                "title": use_title,
                "createdAt": created_at,
                "lastUpdatedAt": last_updated,
            }
            comp2ws[cid] = "(global)"
        else:
            _merge_global_composer_into_meta(comp_meta[cid], cid, data)

        if "db_path" not in sessions[cid]:
            sessions[cid]["db_path"] = db_path

        # Try to associate this global composer with a real workspace.
        # 1) Explicit workspaceIdentifier (most reliable)
        # 2) File URIs in composerData (originalFileStates, attached URIs)
        # Only override the workspace mapping if it's currently (global) or
        # absent, so workspace-scoped mappings from Pass 1 are preserved.
        current_ws = comp2ws.get(cid)
        if current_ws in (None, "(global)"):
            wsid_resolved = project_from_workspace_identifier(
                data.get("workspaceIdentifier") if isinstance(data, dict) else None
            )
            if wsid_resolved is not None:
                ws_id, resolved_project = wsid_resolved
                comp2ws[cid] = ws_id
                if ws_id not in ws_proj or (ws_proj[ws_id].get("name") in (None, "(unknown)")):
                    ws_proj[ws_id] = resolved_project
            else:
                inferred = project_from_global_composer_files(data)
                if inferred and "_inferred_project" not in sessions[cid]:
                    sessions[cid]["_inferred_project"] = inferred

        conversation = data.get("conversation", [])
        if conversation:
            msg_count = 0
            for msg in conversation:
                msg_type = msg.get("type")
                if msg_type is None:
                    continue

                # Type 1 = user, Type 2 = assistant
                role = "user" if msg_type == 1 else "assistant"
                content = msg.get("text", "")
                if content and isinstance(content, str):
                    sessions[cid]["messages"].append({"role": role, "content": content})
                    msg_count += 1

            if msg_count > 0:
                comp_count += 1
                logger.debug("  - Added %s messages from composer %s", msg_count, cid[:8])

    if comp_count > 0:
        logger.debug("  - Extracted data from %s composers in global cursorDiskKV", comp_count)
