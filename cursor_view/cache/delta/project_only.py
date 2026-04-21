"""Workspace-scoped project-only refresh path (no composer re-extraction)."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from cursor_view.paths import cursor_root, workspaces
from cursor_view.projects.inference import workspace_info

logger = logging.getLogger(__name__)


def _project_only_refresh(
    cur: sqlite3.Cursor,
    workspace_id: str,
    workspace_db: Path | None,
) -> int:
    """UPDATE every ``chat_summary`` row in one workspace with the fresh project.

    Returns the number of ``chat_summary`` rows the UPDATE touched
    (``0`` when the UPDATE was skipped). Skipping on unnamed projects
    matches extraction's preference order (``_finalize_sessions``
    prefers a named ``ws_project`` over an inferred one) so we never
    demote a cached inferred project just because the workspace's
    project inference happened to come back unknown this run.
    """
    if workspace_db is None or not workspace_db.exists():
        return 0
    project, _meta = workspace_info(workspace_db)
    name = project.get("name") if isinstance(project, dict) else None
    if not name or name == "(unknown)":
        return 0
    cur.execute(
        "UPDATE chat_summary SET project_name=?, project_root_path=? WHERE workspace_id=?",
        (name, project.get("rootPath") or "Unknown", workspace_id),
    )
    # ``cur.rowcount`` is the number of rows the UPDATE actually
    # modified; negative values (older SQLite builds that can't
    # report a count) are clamped to 0 so the caller's running total
    # is always a non-negative cid count.
    return max(cur.rowcount, 0)


def _workspace_db_lookup() -> dict[str, Path]:
    """Build a single ``workspace_id -> state.vscdb`` map for the refresh.

    :func:`cursor_view.paths.workspaces` walks the workspaceStorage
    tree; doing that once per refresh (instead of once per dirty
    workspace) keeps the project-only branch O(|workspace_project_dirty|)
    rather than O(|workspaces| * |workspace_project_dirty|).
    """
    try:
        return {ws_id: db for ws_id, db in workspaces(cursor_root()) or []}
    except Exception:
        logger.debug("Failed to enumerate workspaces for project-only refresh", exc_info=True)
        return {}
