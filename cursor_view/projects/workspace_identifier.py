"""Resolve a composer's ``workspaceIdentifier`` block to ``(ws_id, project)``."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re

from cursor_view.projects.name import (
    _normalize_root_path_field,
    _project_from_root,
)
from cursor_view.projects.uris import _path_from_workspace_uri_object

logger = logging.getLogger(__name__)


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

    uri_obj = wsid.get("uri")
    if isinstance(uri_obj, dict):
        root = _path_from_workspace_uri_object(uri_obj)
        project = _project_from_root(root) if root else None
        if project:
            return ws_id, project

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
                logger.debug("Failed to parse .code-workspace %s: %s", cw_path_str, e)
            # Fallback: use the .code-workspace filename stem as the project name.
            stem = pathlib.Path(cw_path_str).stem
            if stem:
                return ws_id, {
                    "name": stem,
                    "rootPath": _normalize_root_path_field(cw_path_str),
                }
    return None
