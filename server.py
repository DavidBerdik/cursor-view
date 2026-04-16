#!/usr/bin/env python3
"""
Simple API server to serve Cursor chat data for the web interface.
"""

import json
import sys
import uuid
import logging
import datetime
import html
import os
import platform
import re
import sqlite3
import argparse
import pathlib
import threading
import webbrowser
from collections import defaultdict
from typing import Dict, Any, Iterable
from pathlib import Path
from pygments.lexers import find_lexer_class_for_filename
from urllib.parse import unquote
from flask import Flask, Response, jsonify, send_from_directory, request
from flask_cors import CORS
import markdown

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def _get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

_BASE_PATH = _get_base_path()
app = Flask(__name__, static_folder=os.path.join(_BASE_PATH, 'frontend', 'build'))
CORS(app)

################################################################################
# Cursor storage roots
################################################################################
def cursor_root() -> pathlib.Path:
    h = pathlib.Path.home()
    s = platform.system()
    if s == "Darwin":   return h / "Library" / "Application Support" / "Cursor"
    if s == "Windows":  return h / "AppData" / "Roaming" / "Cursor"
    if s == "Linux":    return h / ".config" / "Cursor"
    raise RuntimeError(f"Unsupported OS: {s}")

################################################################################
# Helpers
################################################################################
def j(cur: sqlite3.Cursor, table: str, key: str):
    cur.execute(f"SELECT value FROM {table} WHERE key=?", (key,))
    row = cur.fetchone()
    if not row:
        return None
    raw = row[0]
    try:
        return json.loads(raw)
    except Exception as e:
        logger.debug(f"Failed to parse JSON for {key}: {e}")
        # Some Cursor/VSCode keys (e.g. debug.selectedroot) store a raw string
        # without JSON quoting. Preserve it so downstream fallbacks can use it.
        if isinstance(raw, str) and raw:
            return raw
        return None

def _uri_from_bubble_context_entry(entry) -> str | None:
    """Extract a URI string from a ``bubble.context.fileSelections`` entry.

    These entries look like ``{"uri": {"_formatted": "file:///...",
    "_fsPath": "c:\\...", "path": "/c:/...", "scheme": "file", ...}, ...}``.
    Returns the first usable URI string, preferring URL-encoded forms so
    downstream URI parsing sees the exact same format as other sources.
    """
    if not isinstance(entry, dict):
        return None
    u = entry.get("uri")
    if isinstance(u, str):
        return u
    if isinstance(u, dict):
        for k in ("_formatted", "external", "path", "_fsPath", "fsPath"):
            v = u.get(k)
            if isinstance(v, str) and v:
                return v
    return None


def _extract_uris_from_bubble(b: dict) -> tuple[list[str], list[str]]:
    """Collect (file_uris, folder_uris) from a bubble dict for project inference.

    Folder URIs (``workspaceUris``, ``attachedFoldersNew``, ``attachedFolders``)
    point at directories that are candidate project roots as-is. File URIs
    (``relevantFiles``) must have their trailing filename stripped before
    common-prefix logic runs. The two are kept separate so callers can handle
    each correctly.

    Also mines the bubble's own ``context.fileSelections`` /
    ``context.folderSelections`` lists (newer Cursor versions), whose entries
    carry structured URI objects rather than the legacy flat strings.
    """
    file_uris: list[str] = []
    folder_uris: list[str] = []

    def _collect(field: str, bucket: list[str], dict_keys: tuple[str, ...]):
        v = b.get(field)
        if not isinstance(v, list):
            return
        for item in v:
            if isinstance(item, str):
                bucket.append(item)
            elif isinstance(item, dict):
                for k in dict_keys:
                    val = item.get(k)
                    if isinstance(val, str):
                        bucket.append(val)
                        break

    _collect("relevantFiles", file_uris, ("uri", "external", "path", "fsPath"))
    _collect("workspaceUris", folder_uris, ("uri", "external", "path", "fsPath"))
    _collect("attachedFoldersNew", folder_uris, ("folderPath", "uri", "external", "path", "fsPath"))
    _collect("attachedFolders", folder_uris, ("folderPath", "uri", "external", "path", "fsPath"))

    ctx = b.get("context")
    if isinstance(ctx, dict):
        for entry in ctx.get("fileSelections") or []:
            u = _uri_from_bubble_context_entry(entry)
            if u:
                file_uris.append(u)
        for entry in ctx.get("folderSelections") or []:
            u = _uri_from_bubble_context_entry(entry)
            if u:
                folder_uris.append(u)

    return file_uris, folder_uris


def iter_bubbles_from_disk_kv(
    db: pathlib.Path,
) -> Iterable[tuple[str, str, str, str, list[str], list[str]]]:
    """Yield (composerId, role, text, db_path, file_uris, folder_uris).

    ``file_uris`` and ``folder_uris`` are kept separate so project inference
    can trim filenames from files while treating folders as candidate roots.
    """
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = con.cursor()
        # Check if table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'")
        if not cur.fetchone():
            con.close()
            return
        
        cur.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'")
    except sqlite3.DatabaseError as e:
        logger.debug(f"Database error with {db}: {e}")
        return
    
    db_path_str = str(db)
    
    for k, v in cur.fetchall():
        try:
            if v is None:
                continue
                
            b = json.loads(v)
        except Exception as e:
            logger.debug(f"Failed to parse bubble JSON for key {k}: {e}")
            continue
        
        if isinstance(b, dict):
            file_uris, folder_uris = _extract_uris_from_bubble(b)
        else:
            file_uris, folder_uris = [], []
        txt = (b.get("text") or b.get("richText") or "").strip()
        # Preserve bubbles that carry workspaceUris/relevantFiles etc. even if
        # they have no text, so project inference can see the URIs.
        if not txt and not file_uris and not folder_uris:
            continue
        role = "user" if b.get("type") == 1 else "assistant"
        composerId = k.split(":")[1]  # Format is bubbleId:composerId:bubbleId
        yield composerId, role, txt, db_path_str, file_uris, folder_uris
    
    con.close()

def iter_chat_from_item_table(db: pathlib.Path) -> Iterable[tuple[str,str,str,str]]:
    """Yield (composerId, role, text, db_path) from ItemTable."""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = con.cursor()
        
        # Try to get chat data from workbench.panel.aichat.view.aichat.chatdata
        chat_data = j(cur, "ItemTable", "workbench.panel.aichat.view.aichat.chatdata")
        if chat_data and "tabs" in chat_data:
            for tab in chat_data.get("tabs", []):
                tab_id = tab.get("tabId", "unknown")
                for bubble in tab.get("bubbles", []):
                    bubble_type = bubble.get("type")
                    if not bubble_type:
                        continue
                    
                    # Extract text from various possible fields
                    text = ""
                    if "text" in bubble:
                        text = bubble["text"]
                    elif "content" in bubble:
                        text = bubble["content"]
                    
                    if text and isinstance(text, str):
                        role = "user" if bubble_type == "user" else "assistant"
                        yield tab_id, role, text, str(db)
        
        # Check for composer data
        composer_data = j(cur, "ItemTable", "composer.composerData")
        if composer_data:
            for comp in composer_data.get("allComposers", []):
                comp_id = comp.get("composerId", "unknown")
                messages = comp.get("messages", [])
                for msg in messages:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    if content:
                        yield comp_id, role, content, str(db)
        
        # Also check for aiService entries
        for key_prefix in ["aiService.prompts", "aiService.generations"]:
            try:
                cur.execute("SELECT key, value FROM ItemTable WHERE key LIKE ?", (f"{key_prefix}%",))
                for k, v in cur.fetchall():
                    try:
                        data = json.loads(v)
                        if isinstance(data, list):
                            for item in data:
                                if "id" in item and "text" in item:
                                    role = "user" if "prompts" in key_prefix else "assistant"
                                    yield item.get("id", "unknown"), role, item.get("text", ""), str(db)
                    except json.JSONDecodeError:
                        continue
            except sqlite3.Error:
                continue
    
    except sqlite3.DatabaseError as e:
        logger.debug(f"Database error in ItemTable with {db}: {e}")
        return
    finally:
        if 'con' in locals():
            con.close()

def iter_composer_data(db: pathlib.Path) -> Iterable[tuple[str,dict,str]]:
    """Yield (composerId, composerData, db_path) from cursorDiskKV table."""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = con.cursor()
        # Check if table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'")
        if not cur.fetchone():
            con.close()
            return
        
        cur.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")
    except sqlite3.DatabaseError as e:
        logger.debug(f"Database error with {db}: {e}")
        return
    
    db_path_str = str(db)
    
    for k, v in cur.fetchall():
        try:
            if v is None:
                continue
                
            composer_data = json.loads(v)
            composer_id = k.split(":")[1]
            yield composer_id, composer_data, db_path_str
            
        except Exception as e:
            logger.debug(f"Failed to parse composer data for key {k}: {e}")
            continue
    
    con.close()

################################################################################
# Workspace discovery
################################################################################
def workspaces(base: pathlib.Path):
    ws_root = base / "User" / "workspaceStorage"
    if not ws_root.exists():
        return
    for folder in ws_root.iterdir():
        db = folder / "state.vscdb"
        if db.exists():
            yield folder.name, db

def _is_windows_drive_segment(part):
    """True if part is a Windows drive letter segment like 'c:' or 'C:'."""
    return len(part) == 2 and part[1] == ":" and part[0].isalpha()


def extract_project_name_from_path(root_path, debug=False):
    """
    Extract a project name from a path, skipping user directories.
    """
    if not root_path or root_path == '/':
        return "Root"
        
    path_parts = [p for p in root_path.split('/') if p]

    # Windows file URIs yield paths like c:/Users/name/repos/project
    if path_parts and _is_windows_drive_segment(path_parts[0]):
        if len(path_parts) == 1:
            return "Unknown Project"
        path_parts = path_parts[1:]

    # Skip common user directory patterns
    project_name = None
    home_dir_patterns = ['Users', 'home']
    
    # Get current username for comparison
    current_username = os.path.basename(os.path.expanduser('~'))
    
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
        known_projects = ['genaisf', 'cursor-view', 'cursor', 'cursor-apps', 'universal-github', 'inquiry']
        
        # Look at the most specific/deepest part of the path first
        for i in range(len(path_parts)-1, username_index, -1):
            if path_parts[i] in known_projects:
                project_name = path_parts[i]
                if debug:
                    logger.debug(f"Found known project name from specific list: {project_name}")
                break
        
        # If no known project found, use the last part of the path as it's likely the project directory
        if not project_name and len(path_parts) > username_index + 1:
            # Check if we have a structure like /Users/username/Documents/codebase/project_name
            if 'Documents' in path_parts and 'codebase' in path_parts:
                doc_index = path_parts.index('Documents')
                codebase_index = path_parts.index('codebase')
                
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
            project_name = 'Home Directory'
            if debug:
                logger.debug(f"Avoided using username as project name")
        
        # Skip common project container directories
        project_containers = ['Documents', 'Projects', 'Code', 'workspace', 'repos', 'git', 'src', 'codebase']
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
            system_dirs = ['Library', 'Applications', 'System', 'var', 'opt', 'tmp']
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
            logger.debug(f"Final check: replaced username with 'Home Directory'")
    
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
        return unquote(uri[len("file:///"):])
    if uri.startswith("file://"):
        return "//" + unquote(uri[len("file://"):])
    # Cursor uses vscode-remote://<host>/<path> for WSL and SSH workspaces.
    # Normalize to a UNC-style //host/path so grouping and display stay consistent.
    if uri.startswith("vscode-remote://"):
        return "//" + unquote(uri[len("vscode-remote://"):])
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
                    if trimmed and not (
                        len(trimmed) <= 2 and trimmed.endswith(":")
                    ):
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
        comp_meta={}
        cd = j(cur,"ItemTable","composer.composerData") or {}
        for c in cd.get("allComposers",[]):
            comp_meta[c["composerId"]] = {
                "title": c.get("name","(untitled)"),
                "createdAt": c.get("createdAt"),
                "lastUpdatedAt": c.get("lastUpdatedAt")
            }
        
        # Try to get composer info from workbench.panel.aichat.view.aichat.chatdata
        chat_data = j(cur, "ItemTable", "workbench.panel.aichat.view.aichat.chatdata") or {}
        for tab in chat_data.get("tabs", []):
            tab_id = tab.get("tabId")
            if tab_id and tab_id not in comp_meta:
                comp_meta[tab_id] = {
                    "title": f"Chat {tab_id[:8]}",
                    "createdAt": None,
                    "lastUpdatedAt": None
                }
    except sqlite3.DatabaseError as e:
        logger.debug(f"Error getting workspace info from {db}: {e}")
        proj = {"name": "(unknown)", "rootPath": "(unknown)"}
        comp_meta = {}
    finally:
        if 'con' in locals():
            con.close()
            
    return proj, comp_meta

################################################################################
# GlobalStorage
################################################################################
def global_storage_path(base: pathlib.Path) -> pathlib.Path:
    """Return path to the global storage state.vscdb."""
    global_db = base / "User" / "globalStorage" / "state.vscdb"
    if global_db.exists():
        return global_db
    
    # Legacy paths
    g_dirs = [base/"User"/"globalStorage"/"cursor.cursor",
              base/"User"/"globalStorage"/"cursor"]
    for d in g_dirs:
        if d.exists():
            for file in d.glob("*.sqlite"):
                return file
    
    return None

################################################################################
# Extraction pipeline
################################################################################
def extract_chats() -> list[Dict[str,Any]]:
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
                    for pattern in ['%ai%', '%chat%', '%composer%', '%prompt%', '%generation%']:
                        cur.execute("SELECT key FROM ItemTable WHERE key LIKE ?", (pattern,))
                        keys = [row[0] for row in cur.fetchall()]
                        if keys:
                            logger.debug(f"Keys matching '{pattern}': {keys}")
                
                con.close()
                
            # Check global storage
            global_db = global_storage_path(root)
            if global_db:
                logger.debug(f"\n--- DIAGNOSTICS for global storage ---")
                con = sqlite3.connect(f"file:{global_db}?mode=ro", uri=True)
                cur = con.cursor()
                
                # List all tables
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cur.fetchall()]
                logger.debug(f"Tables in global DB: {tables}")
                
                # Search for AI-related keys in ItemTable
                if "ItemTable" in tables:
                    for pattern in ['%ai%', '%chat%', '%composer%', '%prompt%', '%generation%']:
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
    ws_proj  : Dict[str,Dict[str,Any]] = {}
    comp_meta: Dict[str,Dict[str,Any]] = {}
    comp2ws  : Dict[str,str]           = {}
    sessions : Dict[str,Dict[str,Any]] = defaultdict(lambda: {"messages":[]})
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

            if cid not in comp_meta:
                created_at = data.get("createdAt")
                comp_meta[cid] = {
                    "title": f"Chat {cid[:8]}",
                    "createdAt": created_at,
                    "lastUpdatedAt": created_at
                }
                comp2ws[cid] = "(global)"
            
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
                    if ws_id not in ws_proj or (
                        ws_proj[ws_id].get("name") in (None, "(unknown)")
                    ):
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
                            "lastUpdatedAt": None
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
    
    # Sort by last updated time if available
    out.sort(key=lambda s: s["session"].get("lastUpdatedAt") or 0, reverse=True)
    logger.debug(f"Total chat sessions extracted: {len(out)}")
    return out

def extract_project_from_git_repos(workspace_id, debug=False):
    """
    Extract project name from the git repositories in a workspace.
    Returns None if no repositories found or unable to access the DB.
    """
    if not workspace_id or workspace_id == "unknown" or workspace_id == "(unknown)" or workspace_id == "(global)":
        if debug:
            logger.debug(f"Invalid workspace ID: {workspace_id}")
        return None
        
    # Find the workspace DB
    cursor_base = cursor_root()
    workspace_db_path = cursor_base / "User" / "workspaceStorage" / workspace_id / "state.vscdb"
    
    if not workspace_db_path.exists():
        if debug:
            logger.debug(f"Workspace DB not found for ID: {workspace_id}")
        return None
        
    try:
        # Connect to the workspace DB
        if debug:
            logger.debug(f"Connecting to workspace DB: {workspace_db_path}")
        con = sqlite3.connect(f"file:{workspace_db_path}?mode=ro", uri=True)
        cur = con.cursor()
        
        # Look for git repositories
        git_data = j(cur, "ItemTable", "scm:view:visibleRepositories")
        if not git_data or not isinstance(git_data, dict) or 'all' not in git_data:
            if debug:
                logger.debug(f"No git repositories found in workspace {workspace_id}, git_data: {git_data}")
            con.close()
            return None
            
        # Extract repo paths from the 'all' key
        repos = git_data.get('all', [])
        if not repos or not isinstance(repos, list):
            if debug:
                logger.debug(f"No repositories in 'all' key for workspace {workspace_id}, repos: {repos}")
            con.close()
            return None
            
        if debug:
            logger.debug(f"Found {len(repos)} git repositories in workspace {workspace_id}: {repos}")
            
        # Process each repo path
        for repo in repos:
            if not isinstance(repo, str):
                continue
                
            # Look for git:Git:file:/// pattern
            if "git:Git:file:///" in repo:
                # Extract the path part
                path = unquote(repo.split("file:///")[-1])
                path_parts = [p for p in path.split('/') if p]
                
                if path_parts:
                    # Use the last part as the project name
                    project_name = path_parts[-1]
                    if debug:
                        logger.debug(f"Found project name '{project_name}' from git repo in workspace {workspace_id}")
                    con.close()
                    return project_name
            else:
                if debug:
                    logger.debug(f"No 'git:Git:file:///' pattern in repo: {repo}")
                    
        if debug:
            logger.debug(f"No suitable git repos found in workspace {workspace_id}")
        con.close()
    except Exception as e:
        if debug:
            logger.debug(f"Error extracting git repos from workspace {workspace_id}: {e}")
        return None
        
    return None

def coalesce_consecutive_messages_by_role(messages):
    """Merge consecutive messages from the same speaker (user vs assistant)."""
    if not isinstance(messages, list) or not messages:
        return []

    def segment_content(msg):
        c = msg.get("content", "") if isinstance(msg, dict) else ""
        if isinstance(c, str) and c.strip():
            return c.rstrip()
        return "Content unavailable"

    out = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = "user" if msg.get("role") == "user" else "assistant"
        segment = segment_content(msg)
        if out and out[-1]["role"] == role:
            prev = out[-1]["content"]
            if prev == "Content unavailable":
                out[-1]["content"] = segment
            elif segment == "Content unavailable":
                pass
            else:
                out[-1]["content"] = prev + "\n\n" + segment
        else:
            out.append({"role": role, "content": segment})
    return out

def messages_for_json_export(messages):
    """Return a copy of messages with assistant role renamed to cursor for JSON export."""
    if not isinstance(messages, list):
        return []
    out = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        m = dict(msg)
        if m.get("role") == "assistant":
            m["role"] = "cursor"
        out.append(m)
    return out

def format_chat_for_frontend(chat):
    """Format the chat data to match what the frontend expects."""
    try:
        # Generate a unique ID for this chat if it doesn't have one
        session_id = str(uuid.uuid4())
        if 'session' in chat and chat['session'] and isinstance(chat['session'], dict):
            session_id = chat['session'].get('composerId', session_id)
        
        # Format date from createdAt timestamp or use current date
        date = int(datetime.datetime.now().timestamp())
        if 'session' in chat and chat['session'] and isinstance(chat['session'], dict):
            created_at = chat['session'].get('createdAt')
            if created_at and isinstance(created_at, (int, float)):
                # Convert from milliseconds to seconds
                date = created_at / 1000
        
        # Ensure project has expected fields
        project = chat.get('project', {})
        if not isinstance(project, dict):
            project = {}
            
        # Get workspace_id from chat
        workspace_id = chat.get('workspace_id', 'unknown')
        
        # Get the database path information
        db_path = chat.get('db_path', 'Unknown database path')
        
        # If project name is a username or unknown, try to extract a better name from rootPath
        if project.get('rootPath'):
            current_name = project.get('name', '')
            username = os.path.basename(os.path.expanduser('~'))
            
            # Check if project name is username or unknown or very generic
            if (current_name == username or 
                current_name == '(unknown)' or 
                current_name == 'Root' or
                # Check if rootPath is directly under /Users/username with no additional path components
                (project.get('rootPath').startswith(f'/Users/{username}') and 
                 project.get('rootPath').count('/') <= 3)):
                
                # Try to extract a better name from the path
                project_name = extract_project_name_from_path(project.get('rootPath'), debug=False)
                
                # Only use the new name if it's meaningful
                if (project_name and 
                    project_name != 'Unknown Project' and 
                    project_name != username and
                    project_name not in ['Documents', 'Downloads', 'Desktop']):
                    
                    logger.debug(f"Improved project name from '{current_name}' to '{project_name}'")
                    project['name'] = project_name
                elif project.get('rootPath').startswith(f'/Users/{username}/Documents/codebase/'):
                    # Special case for /Users/saharmor/Documents/codebase/X
                    parts = project.get('rootPath').split('/')
                    if len(parts) > 5:  # /Users/username/Documents/codebase/X
                        project['name'] = parts[5]
                        logger.debug(f"Set project name to specific codebase subdirectory: {parts[5]}")
                    else:
                        project['name'] = "cursor-view"  # Current project as default
        
        # If the project doesn't have a rootPath or it's very generic, enhance it with workspace_id
        if not project.get('rootPath') or project.get('rootPath') == '/' or project.get('rootPath') == '/Users':
            if workspace_id != 'unknown':
                # Use workspace_id to create a more specific path
                if not project.get('rootPath'):
                    project['rootPath'] = f"/workspace/{workspace_id}"
                elif project.get('rootPath') == '/' or project.get('rootPath') == '/Users':
                    project['rootPath'] = f"{project['rootPath']}/workspace/{workspace_id}"
        
        # FALLBACK: If project name is still generic, try git repositories
        pname = project.get('name') or ''
        if pname in ['Home Directory', '(unknown)', 'Root'] or (
            len(pname) <= 2 and pname.endswith(':')
        ):
            git_project_name = extract_project_from_git_repos(workspace_id, debug=True)
            if git_project_name:
                logger.debug(f"Improved project name from '{project.get('name')}' to '{git_project_name}' using git repo")
                project['name'] = git_project_name
        
        # Add workspace_id to the project data explicitly
        project['workspace_id'] = workspace_id
            
        # Ensure messages exist and are properly formatted
        messages = chat.get('messages', [])
        if not isinstance(messages, list):
            messages = []
        
        # Create properly formatted chat object
        return {
            'project': project,
            'messages': messages,
            'date': date,
            'session_id': session_id,
            'workspace_id': workspace_id,
            'db_path': db_path  # Include the database path in the output
        }
    except Exception as e:
        logger.error(f"Error formatting chat: {e}")
        # Return a minimal valid object if there's an error
        return {
            'project': {'name': 'Error', 'rootPath': '/'},
            'messages': [],
            'date': int(datetime.datetime.now().timestamp()),
            'session_id': str(uuid.uuid4()),
            'workspace_id': 'error',
            'db_path': 'Error retrieving database path'
        }

@app.route('/api/chats', methods=['GET'])
def get_chats():
    """Get all chat sessions."""
    try:
        logger.info(f"Received request for chats from {request.remote_addr}")
        chats = extract_chats()
        logger.info(f"Retrieved {len(chats)} chats")
        
        # Format each chat for the frontend
        formatted_chats = []
        for chat in chats:
            try:
                formatted_chat = format_chat_for_frontend(chat)
                formatted_chat["messages"] = coalesce_consecutive_messages_by_role(
                    formatted_chat.get("messages", [])
                )
                formatted_chats.append(formatted_chat)
            except Exception as e:
                logger.error(f"Error formatting individual chat: {e}")
                # Skip this chat if it can't be formatted
                continue
        
        logger.info(f"Returning {len(formatted_chats)} formatted chats")
        return jsonify(formatted_chats)
    except Exception as e:
        logger.error(f"Error in get_chats: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/chat/<session_id>', methods=['GET'])
def get_chat(session_id):
    """Get a specific chat session by ID."""
    try:
        logger.info(f"Received request for chat {session_id} from {request.remote_addr}")
        chats = extract_chats()
        
        for chat in chats:
            # Check for a matching composerId safely
            if 'session' in chat and chat['session'] and isinstance(chat['session'], dict):
                if chat['session'].get('composerId') == session_id:
                    formatted_chat = format_chat_for_frontend(chat)
                    formatted_chat["messages"] = coalesce_consecutive_messages_by_role(
                        formatted_chat.get("messages", [])
                    )
                    return jsonify(formatted_chat)
        
        logger.warning(f"Chat with ID {session_id} not found")
        return jsonify({"error": "Chat not found"}), 404
    except Exception as e:
        logger.error(f"Error in get_chat: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

EXPORT_HTML_THEMES = {
    "light": {
        "color_scheme": "light",
        "pygments_style": "default",
        "shell_bg": "#f5f5f5",
        "surface_bg": "#ffffff",
        "border": "#eeeeee",
        "shadow": "rgba(0, 0, 0, 0.1)",
        "text_primary": "#333333",
        "text_secondary": "#555555",
        "heading": "#2c3e50",
        "header_bg": "#f0f7ff",
        "header_text": "#2c3e50",
        "info_bg": "#f9f9f9",
        "info_label": "#555555",
        "link": "#1565c0",
        "inline_code_bg": "rgba(63, 81, 181, 0.08)",
        "pre_bg": "#eef2ff",
        "pre_border": "#dddddd",
        "blockquote_border": "#cfd8dc",
        "blockquote_text": "#546e7a",
        "table_surface": "#ffffff",
        "table_outline": "#d8e2ef",
        "table_header_bg": "#f0f4f8",
        "table_header_text": "#1f3a56",
        "table_row_bg": "#ffffff",
        "table_row_alt_bg": "#f7fbff",
        "table_row_hover_bg": "#eef6ff",
        "table_grid": "#dbe7f3",
        "table_shadow": "rgba(29, 58, 86, 0.08)",
        "image_border": "#dfe7ef",
        "user_message_bg": "#f0f7ff",
        "user_message_border": "#3f51b5",
        "assistant_message_bg": "#f0fff7",
        "assistant_message_border": "#00796b",
        "footer_text": "#999999",
    },
    "dark": {
        "color_scheme": "dark",
        "pygments_style": "native",
        "shell_bg": "#121212",
        "surface_bg": "#1E1E1E",
        "border": "#2a2a2a",
        "shadow": "rgba(0, 0, 0, 0.45)",
        "text_primary": "#FFFFFF",
        "text_secondary": "#B3B3B3",
        "heading": "#FFFFFF",
        "header_bg": "#103748",
        "header_text": "#FFFFFF",
        "info_bg": "#181818",
        "info_label": "#B3B3B3",
        "link": "#66d6ff",
        "inline_code_bg": "rgba(12, 188, 255, 0.18)",
        "pre_bg": "#11181f",
        "pre_border": "#2c4550",
        "blockquote_border": "#35505b",
        "blockquote_text": "#B3B3B3",
        "table_surface": "#151c22",
        "table_outline": "#29414d",
        "table_header_bg": "#1b2b36",
        "table_header_text": "#eaf6ff",
        "table_row_bg": "#182128",
        "table_row_alt_bg": "#141b21",
        "table_row_hover_bg": "#20303a",
        "table_grid": "#263844",
        "table_shadow": "rgba(0, 0, 0, 0.28)",
        "image_border": "#2d3b42",
        "user_message_bg": "#102734",
        "user_message_border": "#00bbff",
        "assistant_message_bg": "#12281d",
        "assistant_message_border": "#3EBD64",
        "footer_text": "#8f8f8f",
    },
}


def resolve_export_theme(theme_param: str | None, theme_cookie: str | None) -> str:
    """Resolve the requested export theme, preferring query param over cookie."""
    normalized_param = (theme_param or "").strip().lower()
    if normalized_param in EXPORT_HTML_THEMES:
        return normalized_param

    normalized_cookie = (theme_cookie or "").strip().lower()
    if normalized_cookie in EXPORT_HTML_THEMES:
        return normalized_cookie

    return "dark"


@app.route('/api/chat/<session_id>/export', methods=['GET'])
def export_chat(session_id):
    """Export a specific chat session as HTML, JSON, or Markdown."""
    try:
        logger.info(f"Received request to export chat {session_id} from {request.remote_addr}")
        export_format = request.args.get('format', 'html').lower()
        chats = extract_chats()
        
        for chat in chats:
            # Check for a matching composerId safely
            if 'session' in chat and chat['session'] and isinstance(chat['session'], dict):
                if chat['session'].get('composerId') == session_id:
                    formatted_chat = format_chat_for_frontend(chat)
                    chat_for_export = {
                        **formatted_chat,
                        "messages": coalesce_consecutive_messages_by_role(
                            formatted_chat.get("messages", [])
                        ),
                    }

                    if export_format == 'json':
                        json_payload = {
                            **chat_for_export,
                            "messages": messages_for_json_export(
                                chat_for_export.get("messages", [])
                            ),
                        }
                        return Response(
                            json.dumps(json_payload, indent=2),
                            mimetype="application/json; charset=utf-8",
                            headers={
                                "Content-Disposition": f'attachment; filename="cursor-chat-{session_id[:8]}.json"',
                                "Cache-Control": "no-store",
                            },
                        )
                    if export_format == 'markdown':
                        md_content = generate_markdown(chat_for_export)
                        md_bytes = md_content.encode("utf-8")
                        return Response(
                            md_content,
                            mimetype="text/markdown; charset=utf-8",
                            headers={
                                "Content-Disposition": f'attachment; filename="cursor-chat-{session_id[:8]}.md"',
                                "Content-Length": str(len(md_bytes)),
                                "Cache-Control": "no-store",
                            },
                        )
                    else:
                        # Default to HTML export
                        export_theme = resolve_export_theme(
                            request.args.get('theme'),
                            request.cookies.get('themeMode'),
                        )
                        html_content = generate_standalone_html(chat_for_export, export_theme)
                        return Response(
                            html_content,
                            mimetype="text/html; charset=utf-8",
                            headers={
                                "Content-Disposition": f'attachment; filename="cursor-chat-{session_id[:8]}.html"',
                                "Content-Length": str(len(html_content)),
                                "Cache-Control": "no-store",
                            },
                        )
        
        logger.warning(f"Chat with ID {session_id} not found for export")
        return jsonify({"error": "Chat not found"}), 404
    except Exception as e:
        logger.error(f"Error in export_chat: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

def generate_markdown(chat):
    """Generate a Markdown representation of the chat."""
    logger.info(f"Generating Markdown for session ID: {chat.get('session_id', 'N/A')}")
    date_display = "Unknown date"
    if chat.get("date"):
        try:
            date_obj = datetime.datetime.fromtimestamp(chat["date"])
            date_display = date_obj.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.warning(f"Error formatting date: {e}")

    project_name = chat.get("project", {}).get("name", "Unknown Project")
    project_path = chat.get("project", {}).get("rootPath", "Unknown Path")
    session_display = chat.get("session_id", "Unknown")

    lines = [
        f"# Cursor Chat: {project_name}",
        "",
        f"- **Project:** {project_name}",
        f"- **Path:** {project_path}",
        f"- **Date:** {date_display}",
        f"- **Session ID:** {session_display}",
        "",
        "---",
        "",
    ]

    messages = chat.get("messages") or []
    if not messages:
        lines.append("*No messages found in this conversation.*")
    else:
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if not content or not isinstance(content, str):
                logger.warning(f"Message {i + 1} has invalid content")
                content = "Content unavailable"
            heading = "**User**" if role == "user" else "**Cursor**"
            lines.extend([heading, "", content.rstrip(), "", "---", ""])

    lines.append("")
    lines.append(
        "*Exported from [Cursor View](https://github.com/DavidBerdik/cursor-view)*"
    )
    return "\n".join(lines)

def infer_language_from_filename(filename: str) -> str | None:
    """Infer a fenced-code language tag from a filename."""
    if not filename:
        return None

    lexer_class = find_lexer_class_for_filename(filename)
    if lexer_class is None:
        return None

    if lexer_class.aliases:
        return lexer_class.aliases[0]
    return None

def normalize_markdown_for_html_export(content: str) -> str:
    """Normalize malformed markdown patterns seen in chat exports."""
    normalized_lines = []
    cursor_metadata_pattern = re.compile(r"^(\d+):(\d+):(.+)$")

    for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]

        if stripped.startswith("```"):
            fence_tail = stripped[3:]

            if fence_tail:
                cursor_metadata = cursor_metadata_pattern.match(fence_tail)
                if cursor_metadata:
                    filename = cursor_metadata.group(3)
                    language = infer_language_from_filename(filename)
                    normalized_lines.append(f"{indent}```{language or ''}")
                    continue

                language_and_content = re.match(r"^([A-Za-z0-9_+-]+)\s+(.+)$", fence_tail)
                if language_and_content:
                    language, inline_code = language_and_content.groups()
                    normalized_lines.append(f"{indent}```{language}")
                    normalized_lines.append(f"{indent}{inline_code}")
                    continue

        normalized_lines.append(line)

    return "\n".join(normalized_lines)

def generate_standalone_html(chat, theme_mode: str = "dark"):
    """Generate a standalone HTML representation of the chat."""
    resolved_theme_mode = theme_mode if theme_mode in EXPORT_HTML_THEMES else "dark"
    theme = EXPORT_HTML_THEMES[resolved_theme_mode]
    logger.info(
        "Generating HTML for session ID: %s using %s theme",
        chat.get('session_id', 'N/A'),
        resolved_theme_mode,
    )
    try:
        # Format date for display
        date_display = "Unknown date"
        if chat.get('date'):
            try:
                date_obj = datetime.datetime.fromtimestamp(chat['date'])
                date_display = date_obj.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.warning(f"Error formatting date: {e}")

        # Get project info
        project_name = chat.get('project', {}).get('name', 'Unknown Project')
        project_path = chat.get('project', {}).get('rootPath', 'Unknown Path')
        safe_project_name = html.escape(project_name)
        safe_project_path = html.escape(project_path)
        safe_date_display = html.escape(date_display)
        safe_session_id = html.escape(chat.get('session_id', 'Unknown'))
        logger.info(f"Project: {project_name}, Path: {project_path}, Date: {date_display}")

        # Build the HTML content
        messages_html = ""
        messages = chat.get('messages', [])
        logger.info(f"Found {len(messages)} messages for the chat.")

        if not messages:
            logger.warning("No messages found in the chat object to generate HTML.")
            messages_html = "<p>No messages found in this conversation.</p>"
        else:
            for i, msg in enumerate(messages):
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                logger.debug(f"Processing message {i+1}/{len(messages)} - Role: {role}, Content length: {len(content)}")

                if not content or not isinstance(content, str):
                    logger.warning(f"Message {i+1} has invalid content: {content}")
                    content = "Content unavailable"

                normalized_content = normalize_markdown_for_html_export(content)

                # Escape raw HTML first, then let the Markdown library convert markdown syntax.
                rendered_content = markdown.markdown(
                    normalized_content,
                    extensions=['fenced_code', 'codehilite', 'sane_lists', 'tables'],
                    extension_configs={
                        'codehilite': {
                            'guess_lang': False,
                            'noclasses': True,
                            'pygments_style': theme['pygments_style'],
                        }
                    },
                    tab_length=2,
                    output_format='html5',
                )

                # Python-Markdown's tables extension keeps escaped pipes (\|) literal
                # inside code spans, unlike remark-gfm which unescapes them. Fix by
                # replacing \| with | only within <td>/<th> elements after rendering.
                rendered_content = re.sub(
                    r'(<t[dh]\b[^>]*>)(.*?)(</t[dh]>)',
                    lambda m: m.group(1) + m.group(2).replace('\\|', '|') + m.group(3),
                    rendered_content,
                )

                avatar = "👤" if role == "user" else "🤖"
                name = "User" if role == "user" else "Cursor"
                bg_color = (
                    theme['user_message_bg']
                    if role == "user"
                    else theme['assistant_message_bg']
                )
                border_color = (
                    theme['user_message_border']
                    if role == "user"
                    else theme['assistant_message_border']
                )

                messages_html += f"""
                <div class="message" style="margin-bottom: 20px;">
                    <div class="message-header" style="display: flex; align-items: center; margin-bottom: 8px;">
                        <div class="avatar" style="width: 32px; height: 32px; border-radius: 50%; background-color: {border_color}; color: #ffffff; display: flex; justify-content: center; align-items: center; margin-right: 10px;">
                            {avatar}
                        </div>
                        <div class="sender" style="font-weight: bold;">{name}</div>
                    </div>
                    <div class="message-content" style="padding: 15px; border-radius: 8px; background-color: {bg_color}; border-left: 4px solid {border_color}; margin-left: {0 if role == 'user' else '40px'}; margin-right: {0 if role == 'assistant' else '40px'};">
                        {rendered_content}
                    </div>
                </div>
                """

        # Create the complete HTML document
        html_document = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cursor Chat - {safe_project_name}</title>
    <style>
        :root {{
            color-scheme: {theme['color_scheme']};
            --shell-bg: {theme['shell_bg']};
            --surface-bg: {theme['surface_bg']};
            --border: {theme['border']};
            --shadow: {theme['shadow']};
            --text-primary: {theme['text_primary']};
            --text-secondary: {theme['text_secondary']};
            --heading: {theme['heading']};
            --header-bg: {theme['header_bg']};
            --header-text: {theme['header_text']};
            --info-bg: {theme['info_bg']};
            --info-label: {theme['info_label']};
            --link: {theme['link']};
            --inline-code-bg: {theme['inline_code_bg']};
            --pre-bg: {theme['pre_bg']};
            --pre-border: {theme['pre_border']};
            --blockquote-border: {theme['blockquote_border']};
            --blockquote-text: {theme['blockquote_text']};
            --table-surface: {theme['table_surface']};
            --table-outline: {theme['table_outline']};
            --table-header-bg: {theme['table_header_bg']};
            --table-header-text: {theme['table_header_text']};
            --table-row-bg: {theme['table_row_bg']};
            --table-row-alt-bg: {theme['table_row_alt_bg']};
            --table-row-hover-bg: {theme['table_row_hover_bg']};
            --table-grid: {theme['table_grid']};
            --table-shadow: {theme['table_shadow']};
            --image-border: {theme['image_border']};
            --footer-text: {theme['footer_text']};
        }}
        html {{
            background-color: var(--shell-bg);
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: var(--text-primary);
            background-color: var(--surface-bg);
            max-width: 900px;
            margin: 20px auto;
            padding: 20px;
            border: 1px solid var(--border);
            box-shadow: 0 2px 5px var(--shadow);
        }}
        h1, h2, h3 {{
            color: var(--heading);
        }}
        .header {{
            background-color: var(--header-bg);
            color: var(--header-text);
            padding: 15px 20px;
            margin: -20px -20px 20px -20px;
        }}
        .header h1 {{
            margin: 0;
            color: inherit;
        }}
        .chat-info {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px 20px;
            margin-bottom: 20px;
            background-color: var(--info-bg);
            padding: 12px 15px;
            border-radius: 8px;
            font-size: 0.9em;
            border: 1px solid var(--border);
        }}
        .info-item {{
            display: flex;
            align-items: center;
        }}
        .info-label {{
            font-weight: bold;
            margin-right: 5px;
            color: var(--info-label);
        }}
        pre {{
            background-color: var(--pre-bg);
            color: var(--text-primary);
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            border: 1px solid var(--pre-border);
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.9em;
            white-space: pre;
        }}
        code {{
            background-color: var(--inline-code-bg);
            padding: 0.1em 0.35em;
            border-radius: 4px;
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.95em;
        }}
        .message-content .codehilite {{
            margin: 1em 0;
            border: 1px solid var(--pre-border);
            border-radius: 5px;
            overflow-x: auto;
        }}
        .message-content .codehilite pre {{
            margin: 0;
            padding: 15px;
            border: none;
            border-radius: 0;
            background: transparent !important;
        }}
        .message-content pre code,
        .message-content .codehilite code {{
            background-color: transparent;
            padding: 0;
        }}
        .message-content {{
            word-wrap: break-word;
            overflow-wrap: break-word;
        }}
        .message-content p:first-child {{
            margin-top: 0;
        }}
        .message-content p:last-child {{
            margin-bottom: 0;
        }}
        .message-content ul,
        .message-content ol {{
            padding-left: 1.5rem;
            margin: 0.75rem 0;
        }}
        .message-content li + li {{
            margin-top: 0.25rem;
        }}
        .message-content a {{
            color: var(--link);
            text-decoration: none;
        }}
        .message-content a:hover {{
            text-decoration: underline;
        }}
        .message-content img {{
            max-width: 100%;
            height: auto;
            border-radius: 6px;
            border: 1px solid var(--image-border);
        }}
        .message-content blockquote {{
            margin: 0.75rem 0;
            padding: 0.25rem 0 0.25rem 1rem;
            border-left: 4px solid var(--blockquote-border);
            color: var(--blockquote-text);
        }}
        .message-content table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            margin: 1.1em 0;
            font-size: 0.92em;
            background-color: var(--table-surface);
            border: 1px solid var(--table-outline);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 10px 24px var(--table-shadow);
        }}
        .message-content thead th {{
            background-color: var(--table-header-bg);
            color: var(--table-header-text);
            font-weight: 700;
            letter-spacing: 0.01em;
        }}
        .message-content th,
        .message-content td {{
            padding: 10px 14px;
            text-align: left;
            border-right: 1px solid var(--table-grid);
            border-bottom: 1px solid var(--table-grid);
        }}
        .message-content th:last-child,
        .message-content td:last-child {{
            border-right: none;
        }}
        .message-content tbody tr {{
            background-color: var(--table-row-bg);
        }}
        .message-content tbody tr:nth-child(even) {{
            background-color: var(--table-row-alt-bg);
        }}
        .message-content tbody tr:hover {{
            background-color: var(--table-row-hover-bg);
        }}
        .message-content tbody tr:last-child td {{
            border-bottom: none;
        }}
        .message-content thead th:first-child {{
            border-top-left-radius: 12px;
        }}
        .message-content thead th:last-child {{
            border-top-right-radius: 12px;
        }}
        .message-content tbody tr:last-child td:first-child {{
            border-bottom-left-radius: 12px;
        }}
        .message-content tbody tr:last-child td:last-child {{
            border-bottom-right-radius: 12px;
        }}
        .message-content td {{
            color: var(--text-primary);
            font-variant-numeric: tabular-nums;
        }}
        .footer {{
            margin-top: 30px;
            font-size: 12px;
            color: var(--footer-text);
            text-align: center;
            border-top: 1px solid var(--border);
            padding-top: 15px;
        }}
        .footer a {{
            color: var(--link);
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Cursor Chat: {safe_project_name}</h1>
    </div>
    <div class="chat-info">
        <div class="info-item"><span class="info-label">Project:</span> <span>{safe_project_name}</span></div>
        <div class="info-item"><span class="info-label">Path:</span> <span>{safe_project_path}</span></div>
        <div class="info-item"><span class="info-label">Date:</span> <span>{safe_date_display}</span></div>
        <div class="info-item"><span class="info-label">Session ID:</span> <span>{safe_session_id}</span></div>
    </div>
    <h2>Conversation History</h2>
    <div class="messages">
{messages_html}
    </div>
    <div class="footer">
        <a href="https://github.com/DavidBerdik/cursor-view" target="_blank" rel="noopener noreferrer">Exported from Cursor View</a>
    </div>
</body>
</html>"""

        logger.info(f"Finished generating HTML. Total length: {len(html_document)}")
        return html_document
    except Exception as e:
        logger.error(f"Error generating HTML for session {chat.get('session_id', 'N/A')}: {e}", exc_info=True)
        # Return an HTML formatted error message
        return f"<html><body><h1>Error generating chat export</h1><p>Error: {e}</p></body></html>"

# Serve React app
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    if path and Path(app.static_folder, path).exists():
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run the Cursor Chat View server')
    parser.add_argument('--port', type=int, default=5000, help='Port to run the server on')
    parser.add_argument('--debug', action='store_true', help='Run in debug mode')
    parser.add_argument('--no-browser', action='store_true',
                        help='Do not open the browser automatically')
    args = parser.parse_args()

    logger.info(f"Starting server on port {args.port}")

    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open,
                        args=[f'http://127.0.0.1:{args.port}']).start()

    app.run(host='127.0.0.1', port=args.port, debug=args.debug)
