"""Orchestrate project inference from a workspace's ``state.vscdb``.

All of the heuristics live in sibling modules under
:mod:`cursor_view.projects`; this module owns only the
:func:`workspace_info` recipe that combines them in the right order and
the public/private re-exports callers outside this package rely on.
"""

from __future__ import annotations

import logging
import pathlib
import sqlite3

from cursor_view.projects.composer_uris import (
    _extract_composerdata_context_uris,
    _project_from_folder_uri_list,
    _project_from_global_composer_files,
    _project_from_uri_list,
)
from cursor_view.projects.name import (
    _normalize_root_path_field,
    _project_from_root,
    extract_project_name_from_path,
)
from cursor_view.projects.pane_view import composer_ids_from_pane_view_state
from cursor_view.projects.uris import (
    _file_uri_to_path,
    _trim_file_and_vscode_suffix,
)
from cursor_view.projects.workspace_identifier import (
    _project_from_workspace_identifier,
)
from cursor_view.projects.workspace_json import _project_root_from_workspace_json
from cursor_view.projects.workspace_sources import (
    _project_root_from_history,
    _project_root_from_tree_view_state,
)
from cursor_view.sources.sqlite_data import j

logger = logging.getLogger(__name__)

# Underscore-prefixed back-compat aliases for a handful of helpers that
# older callers still import from this module. Kept so the split is
# import-compatible even before every call site is updated; the canonical
# public forms (without the leading underscore) are re-exported from
# :mod:`cursor_view.projects`.
__all__ = [
    "_extract_composerdata_context_uris",
    "_file_uri_to_path",
    "_normalize_root_path_field",
    "_project_from_folder_uri_list",
    "_project_from_global_composer_files",
    "_project_from_root",
    "_project_from_uri_list",
    "_project_from_workspace_identifier",
    "_trim_file_and_vscode_suffix",
    "extract_project_name_from_path",
    "workspace_info",
]


def workspace_info(db: pathlib.Path):
    """Read a workspace ``state.vscdb`` and return ``(project dict, composer/tab metadata dict)``."""
    # Initialize con to None up-front so the finally block can close it
    # regardless of where in the try the failure happens. Avoids the
    # fragile ``if "con" in locals()`` check this function used to have.
    con = None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = con.cursor()

        proj = {"name": "(unknown)", "rootPath": "(unknown)"}

        # 1) Authoritative: workspaceStorage/<id>/workspace.json
        project_root = _project_root_from_workspace_json(db.parent)

        # 2) workbench.explorer.treeViewState: actual resolved workspace roots
        if not project_root:
            project_root = _project_root_from_tree_view_state(cur)

        # 3) history.entries, filtered and grouped by drive/host
        if not project_root:
            ents = j(cur, "ItemTable", "history.entries") or []
            paths = []
            for e in ents:
                resource = e.get("editor", {}).get("resource", "")
                p = _file_uri_to_path(resource)
                if p:
                    paths.append(p)
            if paths:
                logger.debug("Found %s paths in history entries", len(paths))
            project_root = _project_root_from_history(paths)

        # 4) debug.selectedroot fallback (now works with raw-string-safe j())
        if not project_root:
            selected_root = j(cur, "ItemTable", "debug.selectedroot")
            if isinstance(selected_root, str):
                sr_path = _file_uri_to_path(selected_root)
                if sr_path:
                    trimmed = _trim_file_and_vscode_suffix(sr_path)
                    if trimmed and not (len(trimmed) <= 2 and trimmed.endswith(":")):
                        logger.debug(
                            "Project root from debug.selectedroot: %s",
                            trimmed,
                        )
                        project_root = trimmed

        if project_root:
            project_name = extract_project_name_from_path(project_root, debug=True)
            if project_name:
                proj = {
                    "name": project_name,
                    "rootPath": _normalize_root_path_field(project_root),
                }

        comp_meta = {}
        cd = j(cur, "ItemTable", "composer.composerData") or {}
        for c in cd.get("allComposers", []):
            comp_meta[c["composerId"]] = {
                "title": c.get("name", "(untitled)"),
                "createdAt": c.get("createdAt"),
                "lastUpdatedAt": c.get("lastUpdatedAt"),
            }

        chat_data = j(cur, "ItemTable", "workbench.panel.aichat.view.aichat.chatdata") or {}
        for tab in chat_data.get("tabs", []):
            tab_id = tab.get("tabId")
            if tab_id and tab_id not in comp_meta:
                comp_meta[tab_id] = {
                    "title": f"Chat {tab_id[:8]}",
                    "createdAt": None,
                    "lastUpdatedAt": None,
                }

        # Chats that did no file/folder work (pure web-research, ask_question,
        # create_plan, etc.) have no workspaceIdentifier and no attached URIs,
        # so none of the global-DB heuristics can find their workspace. The
        # workspace's own ItemTable still holds a per-chat UI pane key
        # ``workbench.panel.aichat.view.<composerId>`` which gives us a
        # direct cid -> workspace mapping. Seed comp_meta from those keys so
        # the caller's loop wires comp2ws for these otherwise-orphaned chats.
        for cid in composer_ids_from_pane_view_state(cur):
            if cid not in comp_meta:
                comp_meta[cid] = {
                    "title": f"Chat {cid[:8]}",
                    "createdAt": None,
                    "lastUpdatedAt": None,
                }
    except sqlite3.DatabaseError as e:
        logger.debug("Error getting workspace info from %s: %s", db, e)
        proj = {"name": "(unknown)", "rootPath": "(unknown)"}
        comp_meta = {}
    finally:
        if con is not None:
            con.close()

    return proj, comp_meta
