"""URI and path-shape helpers shared by the workspace/composer resolvers."""

from __future__ import annotations

import os
import re
from urllib.parse import unquote


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


def _normalize_uri_to_path(u: str) -> str | None:
    """Convert a URI or raw fsPath string to a forward-slash path, or ``None``."""
    if not isinstance(u, str) or not u:
        return None
    p = _file_uri_to_path(u)
    if p:
        return p
    if os.path.isabs(u) or re.match(r"^[a-zA-Z]:", u):
        return u.replace("\\", "/")
    return None


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
