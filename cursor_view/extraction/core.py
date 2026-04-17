"""End-to-end extraction of chat sessions from Cursor local storage.

The top-level :func:`extract_chats` is a sequence of well-defined passes
over the workspace and global SQLite databases; each pass lives in its
own private helper so the orchestrator reads as a recipe rather than one
300-line function.

Pass order matters:

1. ``_collect_workspace_messages`` populates the workspace-level project
   and composer metadata and scrapes messages from each workspace's
   ``ItemTable``.
2. ``_collect_global_bubbles`` streams per-bubble messages and URIs out
   of the global ``cursorDiskKV``.
3. ``_collect_global_composers`` walks ``composerData:*`` entries, filling
   in metadata, recording subagent -> parent relationships, resolving
   workspace associations, and appending conversation messages.
4. ``_apply_uri_fallbacks`` infers a project for still-global composers
   from the URIs seen in their bubbles.
5. ``_apply_subagent_inheritance`` walks the subagent parent chain so
   unresolved subagent composers inherit an ancestor's project.
6. ``_collect_global_item_table_chats`` scrapes an older chat storage
   format (``workbench.panel.aichat.view.aichat.chatdata``) in the global
   ``ItemTable``.
7. ``_finalize_sessions`` drops empty sessions, resolves each session's
   project, and returns the recency-sorted list.
"""

import logging
import pathlib
import sqlite3
from collections import defaultdict
from typing import Any, Dict

from cursor_view.extraction.diagnostics import (
    diagnostics_enabled,
    dump_workspace_diagnostics,
)
from cursor_view.paths import cursor_root, global_storage_path, workspaces
from cursor_view.project_inference import (
    _project_from_folder_uri_list,
    _project_from_global_composer_files,
    _project_from_uri_list,
    _project_from_workspace_identifier,
    workspace_info,
)
from cursor_view.sqlite_data import (
    iter_bubbles_from_disk_kv,
    iter_chat_from_item_table,
    iter_composer_data,
    j,
)
from cursor_view.timestamps import session_sort_key_ms

logger = logging.getLogger(__name__)


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


def _collect_workspace_messages(
    root: pathlib.Path,
    ws_proj: Dict[str, Dict[str, Any]],
    comp_meta: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    sessions: Dict[str, Dict[str, Any]],
) -> None:
    """Pass 1: scan workspace DBs for project metadata and ItemTable messages.

    Populates ``ws_proj`` / ``comp_meta`` / ``comp2ws`` / ``sessions`` in
    place. Composers seen only in the workspace ItemTable (no prior
    metadata entry) get a synthetic ``Chat <id-prefix>`` title so they
    still surface in the UI.
    """
    logger.debug("Processing workspace databases...")
    ws_count = 0
    for ws_id, db in workspaces(root):
        ws_count += 1
        logger.debug(f"Processing workspace {ws_id} - {db}")
        proj, meta = workspace_info(db)
        ws_proj[ws_id] = proj
        for cid, m in meta.items():
            comp_meta[cid] = m
            comp2ws[cid] = ws_id

        # Extract chat data from workspace's state.vscdb
        msg_count = 0
        for cid, role, text, db_path in iter_chat_from_item_table(db):
            # Add the message
            sessions[cid]["messages"].append({"role": role, "content": text})
            # Make sure to record the database path
            if "db_path" not in sessions[cid]:
                sessions[cid]["db_path"] = db_path
            msg_count += 1
            if cid not in comp_meta:
                comp_meta[cid] = {"title": f"Chat {cid[:8]}", "createdAt": None, "lastUpdatedAt": None}
                comp2ws[cid] = ws_id
        logger.debug(f"  - Extracted {msg_count} messages from workspace {ws_id}")

    logger.debug(f"Processed {ws_count} workspaces")


def _collect_global_bubbles(
    global_db: pathlib.Path,
    sessions: Dict[str, Dict[str, Any]],
    comp_meta: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    bubble_file_uris_by_cid: Dict[str, list[str]],
    bubble_folder_uris_by_cid: Dict[str, list[str]],
) -> None:
    """Pass 2: extract per-bubble messages + URIs from the global cursorDiskKV.

    Always records ``db_path``, composer meta, and URIs for every bubble
    we see, even for text-less ones, so later project inference can still
    work from ``workspaceUris`` attached to empty assistant bubbles.
    """
    msg_count = 0
    for cid, role, text, db_path, file_uris, folder_uris in iter_bubbles_from_disk_kv(global_db):
        # Always record db_path, comp_meta, and URIs, even for text-less
        # bubbles, so project inference can see workspaceUris attached to
        # empty assistant bubbles.
        if "db_path" not in sessions[cid]:
            sessions[cid]["db_path"] = db_path
        if file_uris:
            bubble_file_uris_by_cid[cid].extend(file_uris)
        if folder_uris:
            bubble_folder_uris_by_cid[cid].extend(folder_uris)
        if cid not in comp_meta:
            comp_meta[cid] = {"title": f"Chat {cid[:8]}", "createdAt": None, "lastUpdatedAt": None}
            comp2ws[cid] = "(global)"
        if not text:
            continue
        sessions[cid]["messages"].append({"role": role, "content": text})
        msg_count += 1
    logger.debug(f"  - Extracted {msg_count} messages from global cursorDiskKV bubbles")


def _collect_global_composers(
    global_db: pathlib.Path,
    sessions: Dict[str, Dict[str, Any]],
    ws_proj: Dict[str, Dict[str, Any]],
    comp_meta: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    subagent_parent: Dict[str, str],
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
    """
    comp_count = 0
    for cid, data, db_path in iter_composer_data(global_db):
        # Record subagent -> parent relationship so an unresolved subagent
        # can later inherit its parent composer's project. Subagents
        # (e.g. type "explore") are spawned without their own
        # workspaceIdentifier or attached-file URIs, so none of the
        # standard resolution paths find a project for them.
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

        # Record the database path
        if "db_path" not in sessions[cid]:
            sessions[cid]["db_path"] = db_path

        # Try to associate this global composer with a real workspace.
        # 1) Explicit workspaceIdentifier (most reliable)
        # 2) File URIs in composerData (originalFileStates, attached URIs)
        # Only override the workspace mapping if it's currently (global) or
        # absent, so workspace-scoped mappings from step 1 are preserved.
        current_ws = comp2ws.get(cid)
        if current_ws in (None, "(global)"):
            wsid_resolved = _project_from_workspace_identifier(
                data.get("workspaceIdentifier") if isinstance(data, dict) else None
            )
            if wsid_resolved is not None:
                ws_id, resolved_project = wsid_resolved
                comp2ws[cid] = ws_id
                if ws_id not in ws_proj or (ws_proj[ws_id].get("name") in (None, "(unknown)")):
                    ws_proj[ws_id] = resolved_project
            else:
                inferred = _project_from_global_composer_files(data)
                if inferred and "_inferred_project" not in sessions[cid]:
                    sessions[cid]["_inferred_project"] = inferred

        # Extract conversation from composer data
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
                logger.debug(f"  - Added {msg_count} messages from composer {cid[:8]}")

    if comp_count > 0:
        logger.debug(f"  - Extracted data from {comp_count} composers in global cursorDiskKV")


def _apply_uri_fallbacks(
    sessions: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    bubble_file_uris_by_cid: Dict[str, list[str]],
    bubble_folder_uris_by_cid: Dict[str, list[str]],
) -> None:
    """Pass 4: infer a project from bubble URIs for composers still tagged ``(global)``.

    Folder URIs are preferred since they are candidate project roots
    as-is; file URIs require common-prefix + filename-trim logic and are
    noisier.
    """
    fallback_cids = set(bubble_folder_uris_by_cid) | set(bubble_file_uris_by_cid)
    for cid in fallback_cids:
        if comp2ws.get(cid) != "(global)":
            continue
        if "_inferred_project" in sessions[cid]:
            continue
        inferred = _project_from_folder_uri_list(
            bubble_folder_uris_by_cid.get(cid, [])
        ) or _project_from_uri_list(
            bubble_file_uris_by_cid.get(cid, [])
        )
        if inferred:
            sessions[cid]["_inferred_project"] = inferred


def _apply_subagent_inheritance(
    sessions: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    subagent_parent: Dict[str, str],
) -> None:
    """Pass 5: make subagent composers inherit a resolved ancestor's project.

    Subagent composers (e.g. ``explore`` tasks) are spawned with no
    ``workspaceIdentifier``, no attached-file URIs, and no URIs in their
    bubbles. They do know their parent composer id via
    ``subagentInfo.parentComposerId``, so walk that chain up to
    ``_MAX_PARENT_DEPTH`` hops and inherit the first resolved ancestor's
    workspace or inferred project. Must run after all the earlier passes
    so ancestor state is final.
    """
    _MAX_PARENT_DEPTH = 8
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
            if ancestor_ws and ancestor_ws != "(global)":
                comp2ws[child_cid] = ancestor_ws
                break
            ancestor_project = sessions.get(ancestor, {}).get("_inferred_project")
            if ancestor_project:
                sessions[child_cid]["_inferred_project"] = ancestor_project
                break
            ancestor = subagent_parent.get(ancestor)
            depth += 1


def _collect_global_item_table_chats(
    global_db: pathlib.Path,
    sessions: Dict[str, Dict[str, Any]],
    comp_meta: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
) -> None:
    """Pass 6: scrape legacy ``workbench.panel.aichat.view.aichat.chatdata`` tabs.

    This is an older chat storage format that predates the
    ``cursorDiskKV``/``composerData`` split; wrapped in a broad
    ``try/except`` so a schema mismatch in this legacy path never takes
    down the rest of the extraction.
    """
    try:
        con = sqlite3.connect(f"file:{global_db}?mode=ro", uri=True)
        chat_data = j(con.cursor(), "ItemTable", "workbench.panel.aichat.view.aichat.chatdata")
        if chat_data:
            msg_count = 0
            for tab in chat_data.get("tabs", []):
                tab_id = tab.get("tabId")
                if tab_id and tab_id not in comp_meta:
                    comp_meta[tab_id] = {
                        "title": f"Global Chat {tab_id[:8]}",
                        "createdAt": None,
                        "lastUpdatedAt": None,
                    }
                    comp2ws[tab_id] = "(global)"

                for bubble in tab.get("bubbles", []):
                    content = ""
                    if "text" in bubble:
                        content = bubble["text"]
                    elif "content" in bubble:
                        content = bubble["content"]

                    if content and isinstance(content, str):
                        role = "user" if bubble.get("type") == "user" else "assistant"
                        sessions[tab_id]["messages"].append({"role": role, "content": content})
                        msg_count += 1
            logger.debug(f"  - Extracted {msg_count} messages from global chat data")
        con.close()
    except Exception as e:
        logger.debug(f"Error processing global ItemTable: {e}")


def _finalize_sessions(
    sessions: Dict[str, Dict[str, Any]],
    ws_proj: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    comp_meta: Dict[str, Dict[str, Any]],
) -> list[Dict[str, Any]]:
    """Pass 7: drop empty sessions, resolve each one's project, sort by recency.

    Project resolution preference:

    1. The workspace's own project, if named.
    2. A project inferred from URIs / composer files.
    3. The workspace project as-is (which may be ``(unknown)``), or the
       sentinel ``{"name": "(unknown)", ...}`` as a last resort.
    """
    out = []
    for cid, data in sessions.items():
        if not data["messages"]:
            continue
        ws_id = comp2ws.get(cid, "(unknown)")
        ws_project = ws_proj.get(ws_id)
        inferred_project = data.get("_inferred_project")
        if ws_project and ws_project.get("name") not in (None, "(unknown)"):
            project = ws_project
        elif inferred_project:
            project = inferred_project
        else:
            project = ws_project or {"name": "(unknown)", "rootPath": "(unknown)"}
        meta = comp_meta.get(cid, {"title": "(untitled)", "createdAt": None, "lastUpdatedAt": None})

        # Create the output object with the db_path included
        chat_data = {
            "project": project,
            "session": {"composerId": cid, **meta},
            "messages": data["messages"],
            "workspace_id": ws_id,
        }

        # Add the database path if available
        if "db_path" in data:
            chat_data["db_path"] = data["db_path"]

        out.append(chat_data)

    # Sort by recency (parsed ms) so ordering matches timestamp semantics
    out.sort(key=lambda s: session_sort_key_ms(s.get("session", {})), reverse=True)
    logger.debug(f"Total chat sessions extracted: {len(out)}")
    return out


def extract_chats() -> list[Dict[str, Any]]:
    """Scan workspace and global Cursor databases and return all non-empty chat sessions."""
    root = cursor_root()
    logger.debug(f"Using Cursor root: {root}")

    # Diagnostic: Check for AI-related keys in the first workspace
    if diagnostics_enabled():
        dump_workspace_diagnostics(root)

    # map lookups
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

    _collect_workspace_messages(root, ws_proj, comp_meta, comp2ws, sessions)

    global_db = global_storage_path(root)
    if global_db:
        logger.debug(f"Processing global storage: {global_db}")
        _collect_global_bubbles(
            global_db,
            sessions,
            comp_meta,
            comp2ws,
            bubble_file_uris_by_cid,
            bubble_folder_uris_by_cid,
        )
        _collect_global_composers(
            global_db,
            sessions,
            ws_proj,
            comp_meta,
            comp2ws,
            subagent_parent,
        )
        # Tertiary fallback: for composers still tagged (global) without a
        # project, infer from URIs seen in their bubbles.
        _apply_uri_fallbacks(
            sessions,
            comp2ws,
            bubble_file_uris_by_cid,
            bubble_folder_uris_by_cid,
        )
        # Quaternary fallback: subagent composers inherit an ancestor's project.
        _apply_subagent_inheritance(sessions, comp2ws, subagent_parent)
        # Also try the legacy ItemTable chat storage in the global DB.
        _collect_global_item_table_chats(global_db, sessions, comp_meta, comp2ws)

    return _finalize_sessions(sessions, ws_proj, comp2ws, comp_meta)
