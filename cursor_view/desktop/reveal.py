"""OS file-manager integration for desktop mode.

Backs the "Reveal exported file", "Open Cache Folder", and "View Logs"
bridge methods. Everything here shells out to the platform's own file
manager / default handler via :mod:`subprocess` (plus ``os.startfile``
on Windows) -- deliberately no Pillow / Qt / GTK file-dialog dependency,
keeping the PyInstaller bundle and its import cost lean (the same
stdlib-only discipline the image-loading and readiness modules follow).

Both helpers return ``bool`` and never raise: a failed reveal/open is a
quality-of-life miss, not something that should bubble an exception
across the JS bridge. Each failure path logs with lazy ``%s`` formatting.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def reveal_in_file_manager(path: Path) -> bool:
    """Reveal ``path`` in the OS file manager, selecting it when possible.

    macOS (``open -R``) and Windows (``explorer /select,``) select the
    file inside its folder. Linux ``xdg-open`` has no select-a-file flag,
    so it opens the parent folder instead (documented limitation). Returns
    True if the file-manager process was launched, False otherwise.
    """
    if not isinstance(path, Path):
        path = Path(path)
    if not path.exists():
        logger.warning("Cannot reveal missing path: %s", path)
        return False
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        elif sys.platform == "win32":
            # explorer exits non-zero even on success, so fire-and-forget
            # via Popen rather than checking a return code. The "/select,"
            # token must stay a single argument (trailing comma included).
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            # xdg-open offers no select-the-file option; open the
            # containing folder so the user can still find the file.
            subprocess.Popen(["xdg-open", str(path.parent)])
    except Exception as exc:
        logger.warning("Failed to reveal %s in file manager: %s", path, exc)
        return False
    return True


def open_path(path: Path) -> bool:
    """Open ``path`` (a file or folder) with the platform default handler.

    A folder opens in the file manager; a file opens in whatever app the
    OS associates with it (a text editor for ``desktop.log``). Returns
    True if the handler was launched, False otherwise.
    """
    if not isinstance(path, Path):
        path = Path(path)
    if not path.exists():
        logger.warning("Cannot open missing path: %s", path)
        return False
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform == "win32":
            # os.startfile is the idiomatic Windows "open with default
            # handler" and exists only on Windows.
            os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        logger.warning("Failed to open %s: %s", path, exc)
        return False
    return True
