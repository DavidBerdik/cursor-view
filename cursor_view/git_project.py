"""Fallback project name from SCM git repository metadata."""

import logging
import sqlite3
from urllib.parse import unquote

from cursor_view.paths import cursor_root
from cursor_view.sqlite_data import j

logger = logging.getLogger(__name__)


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
        if not git_data or not isinstance(git_data, dict) or "all" not in git_data:
            if debug:
                logger.debug(f"No git repositories found in workspace {workspace_id}, git_data: {git_data}")
            con.close()
            return None

        # Extract repo paths from the 'all' key
        repos = git_data.get("all", [])
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
                path_parts = [p for p in path.split("/") if p]

                if path_parts:
                    # Use the last part as the project name
                    project_name = path_parts[-1]
                    if debug:
                        logger.debug(
                            f"Found project name '{project_name}' from git repo in workspace {workspace_id}"
                        )
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
