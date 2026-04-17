"""Window state persistence and platform helpers for the desktop window.

Encapsulates the small bits of platform glue required to launch the
pywebview window in the right place: free-port discovery, screen-aware
centering, the persistent webview profile dir, and load/save of the
last-known window geometry.
"""

import json
import logging
import pathlib
import socket

import webview

from cursor_view.paths import cursor_view_cache_dir

logger = logging.getLogger(__name__)


DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 800
MIN_WIDTH = 900
MIN_HEIGHT = 600


def free_port() -> int:
    """Return an available TCP port on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def webview_storage_path() -> str:
    """Return the directory where pywebview persists cookies / localStorage.

    Isolated in a subfolder of the existing Cursor View cache dir so it does
    not collide with index caches.
    """
    path = cursor_view_cache_dir() / "webview-storage"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _primary_screen():
    """Return the primary screen (origin at 0,0), falling back to screens[0]."""
    screens = list(webview.screens) or []
    for s in screens:
        if s.x == 0 and s.y == 0:
            return s
    return screens[0] if screens else None


def centered_position(width: int, height: int) -> tuple[int | None, int | None]:
    """Compute (x, y) to center a window of the given size on the primary display."""
    screen = _primary_screen()
    if screen is None:
        return None, None
    x = screen.x + max(0, (screen.width - width) // 2)
    y = screen.y + max(0, (screen.height - height) // 2)
    return x, y


def _window_state_path() -> pathlib.Path:
    """Return the path to the persisted window state file."""
    return cursor_view_cache_dir() / "window-state.json"


def load_window_state() -> dict | None:
    """Load the persisted window state, validating it against current screens.

    Returns None if no usable state exists, the file is malformed, the
    geometry violates the minimum size, or the window center would land
    outside every currently-connected display (e.g. user unplugged the
    monitor it was last shown on).
    """
    path = _window_state_path()
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Failed to read window state from %s", path, exc_info=True)
        return None

    try:
        x = int(data["x"])
        y = int(data["y"])
        width = int(data["width"])
        height = int(data["height"])
        maximized = bool(data.get("maximized", False))
    except (KeyError, TypeError, ValueError):
        return None

    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return None

    screens = list(webview.screens) or []
    center_x = x + width // 2
    center_y = y + height // 2
    on_screen = any(
        s.x <= center_x < s.x + s.width and s.y <= center_y < s.y + s.height
        for s in screens
    )
    if screens and not on_screen:
        return None

    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "maximized": maximized,
    }


def save_window_state(state: dict) -> None:
    """Persist window state to disk; failures are logged but non-fatal."""
    path = _window_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        logger.warning("Failed to save window state to %s", path, exc_info=True)
