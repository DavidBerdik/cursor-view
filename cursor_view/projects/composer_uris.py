"""Mine composerData for file/folder URIs and infer a project from them."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable

from cursor_view.projects.name import _project_from_root
from cursor_view.projects.uris import _normalize_uri_to_path, _path_group_key
from cursor_view.projects.workspace_sources import _project_root_from_history


def _extract_composerdata_context_uris(data: Any) -> tuple[list[str], list[str]]:
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


def _project_from_folder_uri_list(uris: Iterable[str]) -> dict[str, Any] | None:
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


def _project_from_uri_list(uris: Iterable[str]) -> dict[str, Any] | None:
    """Infer a project from a flat list of *file* URIs.

    The last path segment is treated as a filename and stripped before
    common-prefix logic runs. Use ``_project_from_folder_uri_list`` for
    folder URIs (``workspaceUris`` etc.).
    """
    if not uris:
        return None
    paths: list[str] = []
    for u in uris:
        p = _normalize_uri_to_path(u)
        if p:
            paths.append(p)
    if not paths:
        return None
    root = _project_root_from_history(paths)
    return _project_from_root(root) if root else None


def _project_from_global_composer_files(data: Any) -> dict[str, Any] | None:
    """Infer a project from composer-level file/folder signals.

    Sources mined:

    - ``originalFileStates`` keys (file URIs).
    - ``allAttachedFileCodeChunksUris`` entries (file URIs).
    - ``context.mentions.fileSelections`` / ``folderSelections`` /
      ``selections`` via :func:`_extract_composerdata_context_uris`.

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
