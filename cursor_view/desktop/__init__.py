"""Desktop launcher for Cursor View.

Starts the Flask application on a random loopback port in a background
thread and displays it inside a native OS webview window via pywebview,
giving the app the appearance of a standalone desktop application.
"""

import logging
import threading

import webview
from werkzeug.serving import make_server

from cursor_view.app_factory import create_app
from cursor_view.cleanup import cleanup_orphan_temp_files
from cursor_view.desktop.api import DesktopApi
from cursor_view.desktop.window_state import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    MIN_HEIGHT,
    MIN_WIDTH,
    centered_position,
    free_port,
    load_window_state,
    save_window_state,
    webview_storage_path,
)

logger = logging.getLogger(__name__)


def run_desktop() -> None:
    """Launch the Cursor View UI inside a native pywebview window."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    cleanup_orphan_temp_files()

    app = create_app()
    port = free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    logger.info("Starting Flask server on http://127.0.0.1:%s", port)

    server_thread = threading.Thread(
        target=server.serve_forever,
        name="cursor-view-flask",
        daemon=True,
    )
    server_thread.start()

    saved = load_window_state()
    if saved is not None:
        width = saved["width"]
        height = saved["height"]
        x = saved["x"]
        y = saved["y"]
        start_maximized = saved["maximized"]
    else:
        width, height = DEFAULT_WIDTH, DEFAULT_HEIGHT
        x, y = centered_position(width, height)
        start_maximized = False

    window = webview.create_window(
        title="Cursor View",
        url=f"http://127.0.0.1:{port}/",
        js_api=DesktopApi(port),
        width=width,
        height=height,
        x=x,
        y=y,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
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
        save_window_state(state)

    window.events.moved += _on_moved
    window.events.resized += _on_resized
    window.events.maximized += _on_maximized
    window.events.restored += _on_restored
    window.events.closing += _on_closing

    try:
        webview.start(
            private_mode=False,
            storage_path=webview_storage_path(),
        )
    finally:
        logger.info("Shutting down Flask server")
        server.shutdown()
        server_thread.join(timeout=5)


def main() -> None:
    """Backwards-compatible alias for ``run_desktop``."""
    run_desktop()


if __name__ == "__main__":
    main()
