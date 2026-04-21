"""Resolve a workspace's project root from the ``workspace.json`` sidecar."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re

from cursor_view.projects.uris import _file_uri_to_path

logger = logging.getLogger(__name__)


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
        logger.debug("Failed to read %s: %s", ws_json, e)
        return None
    if not isinstance(data, dict):
        return None

    folder_uri = data.get("folder")
    if isinstance(folder_uri, str) and folder_uri:
        p = _file_uri_to_path(folder_uri)
        if p:
            logger.debug("Project root from workspace.json folder: %s", p)
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
                                    "Project root from .code-workspace first folder: %s",
                                    first_norm,
                                )
                                return first_norm
                            resolved = (cw_path.parent / first_norm).resolve()
                            resolved_str = str(resolved).replace("\\", "/")
                            logger.debug(
                                "Project root from .code-workspace resolved folder: %s",
                                resolved_str,
                            )
                            return resolved_str
            except Exception as e:
                logger.debug("Failed to parse .code-workspace %s: %s", cw_path_str, e)
    return None
