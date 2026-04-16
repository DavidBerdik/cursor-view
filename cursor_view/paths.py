"""Cursor install paths and workspace / global storage discovery."""

import os
import pathlib
import platform
import sys


def _get_base_path() -> str:
    """Return the application root directory (PyInstaller bundle or repo root)."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    # Repo root: parent of the cursor_view package
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_PATH = _get_base_path()


def cursor_root() -> pathlib.Path:
    """Return the OS-specific directory where Cursor stores user data."""
    h = pathlib.Path.home()
    s = platform.system()
    if s == "Darwin":
        return h / "Library" / "Application Support" / "Cursor"
    if s == "Windows":
        return h / "AppData" / "Roaming" / "Cursor"
    if s == "Linux":
        return h / ".config" / "Cursor"
    raise RuntimeError(f"Unsupported OS: {s}")


def workspaces(base: pathlib.Path):
    """Yield ``(workspace_id, state.vscdb path)`` for each Cursor workspace storage folder."""
    ws_root = base / "User" / "workspaceStorage"
    if not ws_root.exists():
        return
    for folder in ws_root.iterdir():
        db = folder / "state.vscdb"
        if db.exists():
            yield folder.name, db


def global_storage_path(base: pathlib.Path) -> pathlib.Path | None:
    """Return path to the global storage state.vscdb."""
    global_db = base / "User" / "globalStorage" / "state.vscdb"
    if global_db.exists():
        return global_db

    # Legacy paths
    g_dirs = [
        base / "User" / "globalStorage" / "cursor.cursor",
        base / "User" / "globalStorage" / "cursor",
    ]
    for d in g_dirs:
        if d.exists():
            for file in d.glob("*.sqlite"):
                return file

    return None
