"""Infer project name and root from Cursor workspace storage and composer URIs."""

import json
import logging
import os
import pathlib
import re
import sqlite3
from typing import Dict, Iterable
from urllib.parse import unquote

from cursor_view.sqlite_data import j

logger = logging.getLogger(__name__)


def _is_windows_drive_segment(part):
    """True if part is a Windows drive letter segment like 'c:' or 'C:'."""
    return len(part) == 2 and part[1] == ":" and part[0].isalpha()


def extract_project_name_from_path(root_path, debug=False):
    """
    Extract a project name from a path, skipping user directories.
    """
    if not root_path or root_path == "/":
        return "Root"

    path_parts = [p for p in root_path.split("/") if p]

    # Windows file URIs yield paths like c:/Users/name/repos/project
    if path_parts and _is_windows_drive_segment(path_parts[0]):
        if len(path_parts) == 1:
            return "Unknown Project"
        path_parts = path_parts[1:]

    # Skip common user directory patterns
    project_name = None
    home_dir_patterns = ["Users", "home"]

    # Get current username for comparison
    current_username = os.path.basename(os.path.expanduser("~"))

    # Find user directory in path
    username_index = -1
    for i, part in enumerate(path_parts):
        if part in home_dir_patterns:
            username_index = i + 1
            break

    # If this is just /Users/username with no deeper path, don't use username as project
    if username_index >= 0 and username_index < len(path_parts) and path_parts[username_index] == current_username:
        if len(path_parts) <= username_index + 1:
            return "Home Directory"

    if username_index >= 0 and username_index + 1 < len(path_parts):
        # First try specific project directories we know about by name
        known_projects = ["genaisf", "cursor-view", "cursor", "cursor-apps", "universal-github", "inquiry"]

        # Look at the most specific/deepest part of the path first
        for i in range(len(path_parts) - 1, username_index, -1):
            if path_parts[i] in known_projects:
                project_name = path_parts[i]
                if debug:
                    logger.debug(f"Found known project name from specific list: {project_name}")
                break

        # If no known project found, use the last part of the path as it's likely the project directory
        if not project_name and len(path_parts) > username_index + 1:
            # Check if we have a structure like /Users/username/Documents/codebase/project_name
            if "Documents" in path_parts and "codebase" in path_parts:
                doc_index = path_parts.index("Documents")
                codebase_index = path_parts.index("codebase")

                # If there's a path component after 'codebase', use that as the project name
                if codebase_index + 1 < len(path_parts):
                    project_name = path_parts[codebase_index + 1]
                    if debug:
                        logger.debug(f"Found project name in Documents/codebase structure: {project_name}")

            # If no specific structure found, use the last component of the path
            if not project_name:
                project_name = path_parts[-1]
                if debug:
                    logger.debug(f"Using last path component as project name: {project_name}")

        # Skip username as project name
        if project_name == current_username:
            project_name = "Home Directory"
            if debug:
                logger.debug("Avoided using username as project name")

        # Skip common project container directories
        project_containers = ["Documents", "Projects", "Code", "workspace", "repos", "git", "src", "codebase"]
        if project_name in project_containers:
            # Don't use container directories as project names
            # Try to use the next component if available
            container_index = path_parts.index(project_name)
            if container_index + 1 < len(path_parts):
                project_name = path_parts[container_index + 1]
                if debug:
                    logger.debug(f"Skipped container dir, using next component as project name: {project_name}")

        # If we still don't have a project name, use the first non-system directory after username
        if not project_name and username_index + 1 < len(path_parts):
            system_dirs = ["Library", "Applications", "System", "var", "opt", "tmp"]
            for i in range(username_index + 1, len(path_parts)):
                if path_parts[i] not in system_dirs and path_parts[i] not in project_containers:
                    project_name = path_parts[i]
                    if debug:
                        logger.debug(f"Using non-system dir as project name: {project_name}")
                    break
    else:
        # If not in a user directory, use the basename
        project_name = path_parts[-1] if path_parts else "Root"
        if debug:
            logger.debug(f"Using basename as project name: {project_name}")

    # Final check: don't return username as project name
    if project_name == current_username:
        project_name = "Home Directory"
        if debug:
            logger.debug("Final check: replaced username with 'Home Directory'")

    return project_name if project_name else "Unknown Project"


def _file_uri_to_path(uri: str) -> str | None:
    """Convert a file:// or vscode-remote:// URI to an OS-ish path string.

    - ``file:///c%3A/Users/x`` -> ``c:/Users/x``
    - ``file://wsl.localhost/Ubuntu/home/x`` -> ``//wsl.localhost/Ubuntu/home/x``
    - ``vscode-remote://wsl%2Bubuntu/home/x`` -> ``//wsl+ubuntu/home/x``
    Returns ``None`` for anything that is not a recognized workspace URI.
    """
    if not isinstance(uri, str):
        return None
    if uri.startswith("file:///"):
        return unquote(uri[len("file:///") :])
    if uri.startswith("file://"):
        return "//" + unquote(uri[len("file://") :])
    # Cursor uses vscode-remote://<host>/<path> for WSL and SSH workspaces.
    # Normalize to a UNC-style //host/path so grouping and display stay consistent.
    if uri.startswith("vscode-remote://"):
        return "//" + unquote(uri[len("vscode-remote://") :])
    return None


def _path_group_key(path: str) -> str:
    """Group paths by drive letter or UNC host so ``commonprefix`` is meaningful."""
    if not path:
        return ""
    if path.startswith("//"):
        host = path[2:].split("/", 1)[0]
        return "//" + host.lower()
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        return path[:2].lower()
    return "/"


def _project_root_from_workspace_json(ws_folder: pathlib.Path) -> str | None:
    """Read ``workspaceStorage/<id>/workspace.json`` for a definitive project root.

    Handles both single-folder workspaces (``{"folder": "file:///..."}``) and
    multi-root workspaces (``{"workspace": "file:///....code-workspace"}``)
    when the referenced ``.code-workspace`` file still exists.
    """
    ws_json = ws_folder / "workspace.json"
    if not ws_json.exists():
        return None
    try:
        data = json.loads(ws_json.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug(f"Failed to read {ws_json}: {e}")
        return None
    if not isinstance(data, dict):
        return None

    folder_uri = data.get("folder")
    if isinstance(folder_uri, str) and folder_uri:
        p = _file_uri_to_path(folder_uri)
        if p:
            logger.debug(f"Project root from workspace.json folder: {p}")
            return p

    workspace_uri = data.get("workspace")
    if isinstance(workspace_uri, str) and workspace_uri:
        cw_path_str = _file_uri_to_path(workspace_uri)
        if cw_path_str:
            try:
                cw_path = pathlib.Path(cw_path_str)
                if cw_path.exists():
                    cw_data = json.loads(cw_path.read_text(encoding="utf-8"))
                    folders = cw_data.get("folders") if isinstance(cw_data, dict) else None
                    if folders:
                        first = folders[0].get("path") if isinstance(folders[0], dict) else None
                        if isinstance(first, str) and first:
                            first_norm = first.replace("\\", "/")
                            is_abs = os.path.isabs(first_norm) or bool(
                                re.match(r"^[a-zA-Z]:", first_norm)
                            )
                            if is_abs:
                                logger.debug(
                                    f"Project root from .code-workspace first folder: {first_norm}"
                                )
                                return first_norm
                            resolved = (cw_path.parent / first_norm).resolve()
                            resolved_str = str(resolved).replace("\\", "/")
                            logger.debug(
                                f"Project root from .code-workspace resolved folder: {resolved_str}"
                            )
                            return resolved_str
            except Exception as e:
                logger.debug(f"Failed to parse .code-workspace {cw_path_str}: {e}")
    return None


def _project_root_from_tree_view_state(cur: sqlite3.Cursor) -> str | None:
    """Pick the most-referenced workspace root from the explorer tree view state.

    Entries are formatted as ``<rootURI>::<fileURI>`` across ``expanded``,
    ``focus`` and ``selection``. The most common left-hand side is returned.
    """
    state = j(cur, "ItemTable", "workbench.explorer.treeViewState")
    if not isinstance(state, dict):
        return None
    counts: Dict[str, int] = {}
    for field in ("expanded", "focus", "selection"):
        entries = state.get(field) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, str) or "::" not in entry:
                continue
            root_uri = entry.split("::", 1)[0]
            counts[root_uri] = counts.get(root_uri, 0) + 1
    if not counts:
        return None
    best_uri = max(counts.items(), key=lambda kv: kv[1])[0]
    resolved = _file_uri_to_path(best_uri)
    if resolved:
        logger.debug(f"Project root from explorer.treeViewState: {resolved}")
    return resolved


def _project_root_from_history(paths: list[str]) -> str | None:
    """Compute a project root from ``history.entries`` paths.

    - Drops files under the user's home ``.cursor`` folder (Cursor-internal
      assets such as plan files, which live outside any project).
    - Groups by drive letter / UNC host so paths from different roots don't
      collapse ``commonprefix`` to the empty string.
    - Runs ``os.path.commonprefix`` on the largest group and trims to the last
      path separator.
    """
    if not paths:
        return None

    # Drop Cursor-internal files (plans, rules, etc.) that live under any
    # ``.cursor/`` directory, whether on the local machine or a remote host.
    filtered = [p for p in paths if "/.cursor/" not in p.lower()]
    if not filtered:
        filtered = paths

    groups: Dict[str, list[str]] = {}
    for p in filtered:
        groups.setdefault(_path_group_key(p), []).append(p)
    if not groups:
        return None
    _, best_paths = max(groups.items(), key=lambda kv: len(kv[1]))

    common_prefix = os.path.commonprefix(best_paths)
    last_sep = common_prefix.rfind("/")
    if last_sep <= 0:
        return None
    project_root = common_prefix[:last_sep]
    if len(project_root) <= 2 and project_root.endswith(":"):
        logger.debug(
            "Skipping drive-letter-only project root from common prefix: %s",
            project_root,
        )
        return None
    logger.debug(f"Project root from history common prefix: {project_root}")
    return project_root


def _trim_file_and_vscode_suffix(path: str) -> str:
    """Walk up from ``.../Project/.vscode/launch.json`` to ``.../Project``."""
    if not path:
        return path
    parts = path.rstrip("/").split("/")
    if parts and "." in parts[-1]:
        parts = parts[:-1]
    if parts and parts[-1] == ".vscode":
        parts = parts[:-1]
    return "/".join(parts)


def _normalize_root_path_field(project_root: str) -> str:
    """Normalize a project root for the ``rootPath`` field the frontend shows."""
    return "/" + project_root.lstrip("/")


def _project_from_root(project_root: str) -> dict | None:
    """Build a ``{name, rootPath}`` project dict from a resolved root, or ``None``."""
    if not project_root:
        return None
    if len(project_root) <= 2 and project_root.endswith(":"):
        return None
    name = extract_project_name_from_path(project_root, debug=False)
    if not name:
        return None
    return {"name": name, "rootPath": _normalize_root_path_field(project_root)}


def _path_from_workspace_uri_object(uri_obj) -> str | None:
    """Decode a Cursor URI object (``{$mid, external, path, fsPath, scheme}``).

    Falls back to ``fsPath`` (backslashes normalized) when no URI string form
    is present.
    """
    if not isinstance(uri_obj, dict):
        return None
    for key in ("external", "path"):
        val = uri_obj.get(key)
        if isinstance(val, str) and val:
            p = _file_uri_to_path(val) if val.startswith(("file://", "vscode-remote://")) else None
            if p:
                return p
            if val.startswith("/"):
                return val
    fs = uri_obj.get("fsPath")
    if isinstance(fs, str) and fs:
        return fs.replace("\\", "/")
    return None


def _project_from_workspace_identifier(wsid) -> tuple[str, dict] | None:
    """Resolve a composer's ``workspaceIdentifier`` to ``(ws_id, project)``.

    Handles both single-folder (``uri``) and multi-root (``configPath``)
    workspaces. When the referenced ``.code-workspace`` file still exists the
    first declared folder is used; otherwise the ``.code-workspace`` file stem
    is used as the project name.
    """
    if not isinstance(wsid, dict):
        return None
    ws_id = wsid.get("id")
    if not isinstance(ws_id, str) or not ws_id:
        return None

    # Single-folder workspace
    uri_obj = wsid.get("uri")
    if isinstance(uri_obj, dict):
        root = _path_from_workspace_uri_object(uri_obj)
        project = _project_from_root(root) if root else None
        if project:
            return ws_id, project

    # Multi-root workspace
    config_obj = wsid.get("configPath")
    if isinstance(config_obj, dict):
        cw_path_str = _path_from_workspace_uri_object(config_obj)
        if cw_path_str:
            try:
                cw_path = pathlib.Path(cw_path_str)
                if cw_path.exists():
                    cw_data = json.loads(cw_path.read_text(encoding="utf-8"))
                    folders = cw_data.get("folders") if isinstance(cw_data, dict) else None
                    if folders and isinstance(folders[0], dict):
                        first = folders[0].get("path")
                        if isinstance(first, str) and first:
                            first_norm = first.replace("\\", "/")
                            is_abs = os.path.isabs(first_norm) or bool(
                                re.match(r"^[a-zA-Z]:", first_norm)
                            )
                            root = first_norm if is_abs else str(
                                (cw_path.parent / first_norm).resolve()
                            ).replace("\\", "/")
                            project = _project_from_root(root)
                            if project:
                                return ws_id, project
            except Exception as e:
                logger.debug(f"Failed to parse .code-workspace {cw_path_str}: {e}")
            # Fallback: use the .code-workspace filename stem as the project name
            stem = pathlib.Path(cw_path_str).stem
            if stem:
                return ws_id, {
                    "name": stem,
                    "rootPath": _normalize_root_path_field(cw_path_str),
                }
    return None


def _normalize_uri_to_path(u: str) -> str | None:
    """Convert a URI or raw fsPath string to a forward-slash path, or None."""
    if not isinstance(u, str) or not u:
        return None
    p = _file_uri_to_path(u)
    if p:
        return p
    if os.path.isabs(u) or re.match(r"^[a-zA-Z]:", u):
        return u.replace("\\", "/")
    return None


def _project_from_folder_uri_list(uris: Iterable[str]) -> dict | None:
    """Infer a project from URIs that point at folders (not files).

    Folder URIs are candidate project roots as-is. If multiple distinct
    folders are present, fall back to their longest common ancestor without
    stripping a trailing filename (since these are already directories).
    """
    if not uris:
        return None
    paths: list[str] = []
    for u in uris:
        p = _normalize_uri_to_path(u)
        if p:
            paths.append(p.rstrip("/\\"))
    if not paths:
        return None
    # Dedupe while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    if len(unique) == 1:
        return _project_from_root(unique[0])
    # Multiple folders: group by drive/host, take common prefix of largest
    # group without trimming (they're already directories).
    groups: Dict[str, list[str]] = {}
    for p in unique:
        groups.setdefault(_path_group_key(p), []).append(p)
    _, best = max(groups.items(), key=lambda kv: len(kv[1]))
    common = os.path.commonprefix(best).rstrip("/\\")
    if not common or (len(common) <= 2 and common.endswith(":")):
        return None
    return _project_from_root(common)


def _project_from_uri_list(uris: Iterable[str]) -> dict | None:
    """Infer a project from a flat list of *file* URIs.

    The last path segment is treated as a filename and stripped before
    common-prefix logic runs. Use ``_project_from_folder_uri_list`` for
    folder URIs (``workspaceUris`` etc.).
    """
    if not uris:
        return None
    paths = []
    for u in uris:
        p = _normalize_uri_to_path(u)
        if p:
            paths.append(p)
    if not paths:
        return None
    root = _project_root_from_history(paths)
    return _project_from_root(root) if root else None


def _extract_composerdata_context_uris(data) -> tuple[list[str], list[str]]:
    """Return ``(file_uris, folder_uris)`` from ``composerData.context.mentions``.

    Newer Cursor versions record user-mentioned files and folders under
    ``context.mentions`` with structure:

    - ``fileSelections``: dict whose keys are file URIs.
    - ``folderSelections``: dict whose keys are folder URIs.
    - ``selections``: dict whose keys are JSON-encoded blobs of the form
      ``{"uri":"file:///...","range":{...},"text":"..."}``; the embedded
      ``uri`` is extracted. Terminal-scheme selections (``terminal:``,
      ``vscode-terminal:``) point at shells, not project files, so they're
      skipped.
    """
    file_uris: list[str] = []
    folder_uris: list[str] = []
    if not isinstance(data, dict):
        return file_uris, folder_uris
    mentions = (data.get("context") or {}).get("mentions") or {}
    if not isinstance(mentions, dict):
        return file_uris, folder_uris

    fs = mentions.get("fileSelections")
    if isinstance(fs, dict):
        file_uris.extend(k for k in fs.keys() if isinstance(k, str))
    ds = mentions.get("folderSelections")
    if isinstance(ds, dict):
        folder_uris.extend(k for k in ds.keys() if isinstance(k, str))

    sel = mentions.get("selections")
    if isinstance(sel, dict):
        for key in sel.keys():
            if not isinstance(key, str):
                continue
            try:
                meta = json.loads(key)
            except Exception:
                continue
            u = meta.get("uri") if isinstance(meta, dict) else None
            if isinstance(u, str) and u.startswith(("file://", "vscode-remote://")):
                file_uris.append(u)
    return file_uris, folder_uris


def _project_from_global_composer_files(data) -> dict | None:
    """Infer a project from composer-level file/folder signals.

    Sources mined:
    - ``originalFileStates`` keys (file URIs).
    - ``allAttachedFileCodeChunksUris`` entries (file URIs).
    - ``context.mentions.fileSelections`` / ``folderSelections`` / ``selections``
      via :func:`_extract_composerdata_context_uris`.

    Used as a secondary signal for global-only composers that have no
    ``workspaceIdentifier``. Folder URIs are preferred when present since
    they are candidate project roots as-is.
    """
    if not isinstance(data, dict):
        return None
    file_uris: list[str] = []
    folder_uris: list[str] = []

    ofs = data.get("originalFileStates")
    if isinstance(ofs, dict):
        file_uris.extend(k for k in ofs.keys() if isinstance(k, str))
    acfu = data.get("allAttachedFileCodeChunksUris")
    if isinstance(acfu, list):
        file_uris.extend(u for u in acfu if isinstance(u, str))

    mentioned_files, mentioned_folders = _extract_composerdata_context_uris(data)
    file_uris.extend(mentioned_files)
    folder_uris.extend(mentioned_folders)

    return (
        _project_from_folder_uri_list(folder_uris)
        or _project_from_uri_list(file_uris)
    )


def workspace_info(db: pathlib.Path):
    """Read a workspace ``state.vscdb`` and return ``(project dict, composer/tab metadata dict)``."""
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
                logger.debug(f"Found {len(paths)} paths in history entries")
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
                            f"Project root from debug.selectedroot: {trimmed}"
                        )
                        project_root = trimmed

        if project_root:
            project_name = extract_project_name_from_path(project_root, debug=True)
            if project_name:
                proj = {
                    "name": project_name,
                    "rootPath": _normalize_root_path_field(project_root),
                }

        # composers meta
        comp_meta = {}
        cd = j(cur, "ItemTable", "composer.composerData") or {}
        for c in cd.get("allComposers", []):
            comp_meta[c["composerId"]] = {
                "title": c.get("name", "(untitled)"),
                "createdAt": c.get("createdAt"),
                "lastUpdatedAt": c.get("lastUpdatedAt"),
            }

        # Try to get composer info from workbench.panel.aichat.view.aichat.chatdata
        chat_data = j(cur, "ItemTable", "workbench.panel.aichat.view.aichat.chatdata") or {}
        for tab in chat_data.get("tabs", []):
            tab_id = tab.get("tabId")
            if tab_id and tab_id not in comp_meta:
                comp_meta[tab_id] = {
                    "title": f"Chat {tab_id[:8]}",
                    "createdAt": None,
                    "lastUpdatedAt": None,
                }
    except sqlite3.DatabaseError as e:
        logger.debug(f"Error getting workspace info from {db}: {e}")
        proj = {"name": "(unknown)", "rootPath": "(unknown)"}
        comp_meta = {}
    finally:
        if "con" in locals():
            con.close()

    return proj, comp_meta
