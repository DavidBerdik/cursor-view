"""Derive a human-readable project name from a resolved root path."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_HOME_DIR_PATTERNS = ("Users", "home")
# Container directories people commonly nest projects under; we skip past
# these when picking a display name so "Documents" never becomes a project.
_PROJECT_CONTAINERS = (
    "Documents",
    "Projects",
    "Code",
    "workspace",
    "repos",
    "git",
    "src",
    "codebase",
)
# OS-owned subtrees under the user home that are never real project roots.
_SYSTEM_DIRS = ("Library", "Applications", "System", "var", "opt", "tmp")


def _is_windows_drive_segment(part: str) -> bool:
    """True if ``part`` is a Windows drive letter segment like ``c:`` or ``C:``."""
    return len(part) == 2 and part[1] == ":" and part[0].isalpha()


def _strip_windows_drive_prefix(path_parts: list[str]) -> tuple[list[str], bool]:
    """Drop a leading Windows drive letter; signal ``True`` when nothing follows.

    Windows file URIs decode to paths like ``c:/Users/name/repos/project``;
    the leading drive segment is never a meaningful project name, and a URI
    that contains only the drive letter has no project to extract.
    """
    if path_parts and _is_windows_drive_segment(path_parts[0]):
        if len(path_parts) == 1:
            return path_parts, True
        return path_parts[1:], False
    return path_parts, False


def _locate_user_home_dir(path_parts: list[str]) -> int:
    """Return the index immediately AFTER the first ``Users`` / ``home`` segment.

    Returns ``-1`` when the path doesn't traverse a recognized user-home
    root, in which case the caller falls back to the basename.
    """
    for i, part in enumerate(path_parts):
        if part in _HOME_DIR_PATTERNS:
            return i + 1
    return -1


def _reject_project_container_names(
    project_name: str, path_parts: list[str], debug: bool = False
) -> str:
    """Advance past a generic container directory to the candidate below it.

    If ``project_name`` is a listed container (``Documents``, ``repos``,
    etc.) we'd rather show the subfolder that actually carries the project
    identity. When the container has no child in the path, leave it alone;
    the caller decides whether to keep it or fall through to another
    heuristic.
    """
    if project_name in _PROJECT_CONTAINERS:
        container_index = path_parts.index(project_name)
        if container_index + 1 < len(path_parts):
            project_name = path_parts[container_index + 1]
            if debug:
                logger.debug(
                    "Skipped container dir, using next component as project name: %s",
                    project_name,
                )
    return project_name


def _choose_project_name_after_home(
    path_parts: list[str],
    username_index: int,
    current_username: str,
    debug: bool = False,
) -> str | None:
    """Pick a project name from segments deeper than the user-home directory.

    Preference order:

    1. The ``Documents/codebase/<name>`` convention some users keep.
    2. The last path component (most common case).
    3. Replace the username itself with ``Home Directory``.
    4. Reject generic container names (``Documents``, ``Projects``, ...).
    5. Final fallback: the first non-system, non-container segment after
       the home directory.
    """
    project_name: str | None = None

    if "Documents" in path_parts and "codebase" in path_parts:
        codebase_index = path_parts.index("codebase")
        if codebase_index + 1 < len(path_parts):
            project_name = path_parts[codebase_index + 1]
            if debug:
                logger.debug(
                    "Found project name in Documents/codebase structure: %s",
                    project_name,
                )

    if not project_name:
        project_name = path_parts[-1]
        if debug:
            logger.debug("Using last path component as project name: %s", project_name)

    if project_name == current_username:
        project_name = "Home Directory"
        if debug:
            logger.debug("Avoided using username as project name")

    project_name = _reject_project_container_names(project_name, path_parts, debug=debug)

    if not project_name and username_index + 1 < len(path_parts):
        for i in range(username_index + 1, len(path_parts)):
            if (
                path_parts[i] not in _SYSTEM_DIRS
                and path_parts[i] not in _PROJECT_CONTAINERS
            ):
                project_name = path_parts[i]
                if debug:
                    logger.debug("Using non-system dir as project name: %s", project_name)
                break

    return project_name


def extract_project_name_from_path(root_path: str, debug: bool = False) -> str:
    """Extract a project name from a path, skipping user directories.

    Split into focused helpers so the top-level recipe stays short and
    each heuristic (Windows drive strip, user-home lookup, container
    rejection) can be audited on its own.
    """
    if not root_path or root_path == "/":
        return "Root"

    path_parts = [p for p in root_path.split("/") if p]

    path_parts, lone_drive = _strip_windows_drive_prefix(path_parts)
    if lone_drive:
        return "Unknown Project"

    current_username = os.path.basename(os.path.expanduser("~"))
    username_index = _locate_user_home_dir(path_parts)

    # Bare ``/Users/<current user>`` with no deeper path is the home
    # folder itself, which is never a project.
    if (
        0 <= username_index < len(path_parts)
        and path_parts[username_index] == current_username
        and len(path_parts) <= username_index + 1
    ):
        return "Home Directory"

    if username_index >= 0 and username_index + 1 < len(path_parts):
        project_name = _choose_project_name_after_home(
            path_parts, username_index, current_username, debug=debug
        )
    else:
        project_name = path_parts[-1] if path_parts else "Root"
        if debug:
            logger.debug("Using basename as project name: %s", project_name)

    if project_name == current_username:
        project_name = "Home Directory"
        if debug:
            logger.debug("Final check: replaced username with 'Home Directory'")

    return project_name if project_name else "Unknown Project"


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
