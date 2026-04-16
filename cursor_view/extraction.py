"""End-to-end extraction of chat sessions from Cursor local storage."""

import logging
import os
import sqlite3
from collections import defaultdict
from typing import Any, Dict

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


def extract_chats() -> list[Dict[str, Any]]:
    """Scan workspace and global Cursor databases and return all non-empty chat sessions."""
    root = cursor_root()
    logger.debug(f"Using Cursor root: {root}")

    # Diagnostic: Check for AI-related keys in the first workspace
    if os.environ.get("CURSOR_CHAT_DIAGNOSTICS"):
        try:
            first_ws = next(workspaces(root))
            if first_ws:
                ws_id, db = first_ws
                logger.debug(f"\n--- DIAGNOSTICS for workspace {ws_id} ---")
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                cur = con.cursor()

                # List all tables
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cur.fetchall()]
                logger.debug(f"Tables in workspace DB: {tables}")

                # Search for AI-related keys
                if "ItemTable" in tables:
                    for pattern in ["%ai%", "%chat%", "%composer%", "%prompt%", "%generation%"]:
                        cur.execute("SELECT key FROM ItemTable WHERE key LIKE ?", (pattern,))
                        keys = [row[0] for row in cur.fetchall()]
                        if keys:
                            logger.debug(f"Keys matching '{pattern}': {keys}")

                con.close()

            # Check global storage
            global_db = global_storage_path(root)
            if global_db:
                logger.debug("\n--- DIAGNOSTICS for global storage ---")
                con = sqlite3.connect(f"file:{global_db}?mode=ro", uri=True)
                cur = con.cursor()

                # List all tables
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cur.fetchall()]
                logger.debug(f"Tables in global DB: {tables}")

                # Search for AI-related keys in ItemTable
                if "ItemTable" in tables:
                    for pattern in ["%ai%", "%chat%", "%composer%", "%prompt%", "%generation%"]:
                        cur.execute("SELECT key FROM ItemTable WHERE key LIKE ?", (pattern,))
                        keys = [row[0] for row in cur.fetchall()]
                        if keys:
                            logger.debug(f"Keys matching '{pattern}': {keys}")

                # Check for keys in cursorDiskKV
                if "cursorDiskKV" in tables:
                    cur.execute("SELECT DISTINCT substr(key, 1, instr(key, ':') - 1) FROM cursorDiskKV")
                    prefixes = [row[0] for row in cur.fetchall()]
                    logger.debug(f"Key prefixes in cursorDiskKV: {prefixes}")

                con.close()

            logger.debug("\n--- END DIAGNOSTICS ---\n")
        except Exception as e:
            logger.debug(f"Error in diagnostics: {e}")

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

    # 1. Process workspace DBs first
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

    # 2. Process global storage
    global_db = global_storage_path(root)
    if global_db:
        logger.debug(f"Processing global storage: {global_db}")
        # Extract bubbles from cursorDiskKV
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

        # Extract composer data
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

        # Tertiary fallback: for composers still tagged (global) without a
        # project, infer from URIs seen in their bubbles. Folder URIs are
        # preferred since they are candidate project roots as-is; file URIs
        # require common-prefix + filename-trim logic and are noisier.
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

        # Quaternary fallback: subagent composers (e.g. "explore") are spawned
        # with no workspaceIdentifier, no attached-file URIs, and no URIs in
        # their bubbles. They do know their parent composerId via
        # ``subagentInfo.parentComposerId``, so walk that chain until we find
        # an ancestor with a resolved workspace or an inferred project and
        # inherit it. Runs after all the earlier passes so ancestor state is
        # final.
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

        if comp_count > 0:
            logger.debug(f"  - Extracted data from {comp_count} composers in global cursorDiskKV")

        # Also try ItemTable in global DB
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

    # 3. Build final list
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
