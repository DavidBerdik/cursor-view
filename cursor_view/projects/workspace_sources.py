"""Workspace-DB derived fallbacks for the project root (tree view + history)."""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Dict

from cursor_view.projects.uris import _file_uri_to_path, _path_group_key
from cursor_view.sources.sqlite_data import j

logger = logging.getLogger(__name__)


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
        logger.debug("Project root from explorer.treeViewState: %s", resolved)
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
    logger.debug("Project root from history common prefix: %s", project_root)
    return project_root
