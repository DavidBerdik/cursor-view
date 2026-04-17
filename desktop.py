#!/usr/bin/env python3
"""Desktop launcher for Cursor View.

Starts the Flask application on a random loopback port in a background
thread and displays it inside a native OS webview window via pywebview,
giving the app the appearance of a standalone desktop application.
"""

import json
import logging
import pathlib
import socket
import threading
import urllib.request

import webview
from werkzeug.serving import make_server

from cursor_view.app_factory import create_app
from cursor_view.paths import cursor_view_cache_dir

logger = logging.getLogger(__name__)


_EXTENSIONS: dict[str, str] = {
    "html": "html",
    "json": "json",
    "markdown": "md",
}

_DEFAULT_WIDTH = 1200
_DEFAULT_HEIGHT = 800
_MIN_WIDTH = 900
_MIN_HEIGHT = 600


def _free_port() -> int:
    """Return an available TCP port on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _webview_storage_path() -> str:
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


def _centered_position(width: int, height: int) -> tuple[int | None, int | None]:
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


def _load_window_state() -> dict | None:
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

    if width < _MIN_WIDTH or height < _MIN_HEIGHT:
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


def _save_window_state(state: dict) -> None:
    """Persist window state to disk; failures are logged but non-fatal."""
    path = _window_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        logger.warning("Failed to save window state to %s", path, exc_info=True)


class DesktopApi:
    """JS-to-Python bridge exposed to the React UI via pywebview.

    The embedded webviews (WebView2 / WKWebView / WebKitGTK) do not honor
    the ``<a download>`` blob trick the browser UI uses, so exports need
    to be written to disk from Python using a native save dialog.
    """

    def __init__(self, port: int) -> None:
        self._port = port

    def save_export(
        self,
        session_id: str,
        fmt: str,
        theme: str | None = None,
    ) -> dict:
        """Prompt for a save location and write the exported chat to disk.

        Returns a JSON-serializable result describing the outcome so the
        frontend can surface appropriate feedback.
        """
        if not isinstance(session_id, str) or not session_id:
            return {"saved": False, "error": "Missing session id"}

        ext = _EXTENSIONS.get(fmt)
        if ext is None:
            return {"saved": False, "error": f"Unsupported format: {fmt}"}

        default_name = f"cursor-chat-{session_id[:8]}.{ext}"
        win = webview.active_window()
        if win is None and webview.windows:
            win = webview.windows[0]
        if win is None:
            return {"saved": False, "error": "No active window"}

        picked = win.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=default_name,
            file_types=(
                f"{ext.upper()} files (*.{ext})",
                "All files (*.*)",
            ),
        )
        if not picked:
            return {"saved": False, "cancelled": True}
        path = picked if isinstance(picked, str) else picked[0]

        url = (
            f"http://127.0.0.1:{self._port}"
            f"/api/chat/{session_id}/export?format={fmt}"
        )
        if theme in ("light", "dark"):
            url += f"&theme={theme}"

        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
            pathlib.Path(path).write_bytes(data)
        except Exception as e:
            logger.exception("Failed to save export to %s", path)
            return {"saved": False, "error": str(e)}

        return {"saved": True, "path": path}


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = create_app()
    port = _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    logger.info("Starting Flask server on http://127.0.0.1:%s", port)

    server_thread = threading.Thread(
        target=server.serve_forever,
        name="cursor-view-flask",
        daemon=True,
    )
    server_thread.start()

    saved = _load_window_state()
    if saved is not None:
        width = saved["width"]
        height = saved["height"]
        x = saved["x"]
        y = saved["y"]
        start_maximized = saved["maximized"]
    else:
        width, height = _DEFAULT_WIDTH, _DEFAULT_HEIGHT
        x, y = _centered_position(width, height)
        start_maximized = False

    window = webview.create_window(
        title="Cursor View",
        url=f"http://127.0.0.1:{port}/",
        js_api=DesktopApi(port),
        width=width,
        height=height,
        x=x,
        y=y,
        min_size=(_MIN_WIDTH, _MIN_HEIGHT),
        text_select=True,
        maximized=start_maximized,
    )

    # Tracks the latest non-maximized geometry plus the maximized flag.
    # We only update geometry when the window isn't maximized so that on
    # restore we snap back to the user's prior size, mirroring how Discord
    # and similar apps remember window state across launches.
    state = {
        "x": x if x is not None else 0,
        "y": y if y is not None else 0,
        "width": width,
        "height": height,
        "maximized": start_maximized,
    }

    def _on_moved(new_x: int, new_y: int) -> None:
        if not state["maximized"]:
            state["x"] = int(new_x)
            state["y"] = int(new_y)

    def _on_resized(new_w: int, new_h: int) -> None:
        if not state["maximized"]:
            state["width"] = int(new_w)
            state["height"] = int(new_h)

    def _on_maximized() -> None:
        state["maximized"] = True

    def _on_restored() -> None:
        state["maximized"] = False

    def _on_closing() -> None:
        _save_window_state(state)

    window.events.moved += _on_moved
    window.events.resized += _on_resized
    window.events.maximized += _on_maximized
    window.events.restored += _on_restored
    window.events.closing += _on_closing

    try:
        webview.start(
            private_mode=False,
            storage_path=_webview_storage_path(),
        )
    finally:
        logger.info("Shutting down Flask server")
        server.shutdown()
        server_thread.join(timeout=5)


if __name__ == "__main__":
    main()
