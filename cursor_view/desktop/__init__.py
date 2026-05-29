"""Desktop launcher for Cursor View.

Starts the Flask application on a random loopback port in a background
thread and displays it inside a native OS webview window via pywebview,
giving the app the appearance of a standalone desktop application.
"""

import logging
import signal
import sys
import threading
import traceback

import webview
from werkzeug.serving import make_server

from cursor_view.app_factory import create_app
from cursor_view.cleanup import cleanup_orphan_temp_files
from cursor_view.desktop.api import DesktopApi
from cursor_view.desktop.error_window import build_error_html, show_startup_error
from cursor_view.desktop.readiness import wait_for_server
from cursor_view.desktop.splash import splash_html
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

    # Everything up to a bound listening socket can fail before there is
    # any window to surface a traceback in (a lost free_port race that
    # leaves the port bound, no privilege to bind loopback, a cleanup
    # error). Route those to a native error window instead of dying with
    # a traceback the headless desktop binary would never show, then exit
    # non-zero. This boundary runs before webview.start, so it is safe for
    # show_startup_error to run its own GUI loop.
    try:
        cleanup_orphan_temp_files()
        app = create_app()
        port = free_port()
        server = make_server("127.0.0.1", port, app, threaded=True)
    except Exception as exc:
        logger.exception("Desktop startup failed before the window could open")
        show_startup_error(str(exc), traceback.format_exc())
        sys.exit(1)

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

    # Open on a self-contained splash instead of the loopback URL: the
    # daemon Flask thread may not be accepting connections yet on a cold
    # launch, and navigating straight to it briefly flashes the webview's
    # native "site can't be reached" frame. The real URL is loaded by
    # _navigate_when_ready below, only after wait_for_server confirms the
    # server answers. The splash is passed as html= (not a data: URL):
    # Chromium-based backends block top-level data: navigation, which
    # resolves as a relative path against the loopback origin and 404s.
    target_url = f"http://127.0.0.1:{port}/"
    window = webview.create_window(
        title="Cursor View",
        html=splash_html(),
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

    # webview.start() blocks the main thread inside the native GUI loop,
    # so a SIGTERM (e.g. `kill <pid>`, a supervisor stop) would otherwise
    # be deferred until the loop happens to return. Destroying the window
    # unblocks webview.start() and lets the finally block below drain the
    # Flask server cleanly. Skipped on Windows, where SIGTERM is not a
    # real signal (CRT maps it to immediate process termination, so a
    # handler cannot run the orderly shutdown anyway).
    if sys.platform != "win32":

        def _handle_sigterm(_signum: int, _frame: object) -> None:
            logger.info("Received SIGTERM; destroying window to begin shutdown")
            try:
                window.destroy()
            except Exception as exc:
                logger.warning("Failed to destroy window on SIGTERM: %s", exc)

        signal.signal(signal.SIGTERM, _handle_sigterm)

    def _navigate_when_ready() -> None:
        # Runs on pywebview's worker thread once the GUI loop is up, so it
        # can block on the readiness probe without freezing the window
        # painting the splash. On timeout the main loop is already running,
        # so a second webview.start() (and thus show_startup_error) is not
        # possible -- load the error page into the existing splash window
        # instead of stranding the user on the spinner or flashing the
        # webview's own "site can't be reached" frame.
        if wait_for_server(port):
            window.load_url(target_url)
        else:
            logger.error(
                "Flask server never answered the readiness probe on port %s", port
            )
            window.load_html(
                build_error_html(
                    "The local Cursor View server did not respond in time, "
                    "so the app could not load."
                )
            )

    try:
        webview.start(
            _navigate_when_ready,
            private_mode=False,
            storage_path=webview_storage_path(),
        )
    except KeyboardInterrupt:
        # Ctrl-C while the GUI loop is running surfaces here on the main
        # thread; fall through to the finally so the server still drains.
        logger.info("Interrupted; shutting down")
    finally:
        logger.info("Shutting down Flask server")
        server.shutdown()
        join_timeout = 5
        server_thread.join(timeout=join_timeout)
        if server_thread.is_alive():
            # daemon=True means the process can still exit, but a thread
            # stuck mid-request points at a Werkzeug shutdown that did not
            # take; surface it so a hanging exit is diagnosable.
            logger.warning(
                "Flask server thread did not exit within %ss", join_timeout
            )


def main() -> None:
    """Backwards-compatible alias for ``run_desktop``."""
    run_desktop()


if __name__ == "__main__":
    main()
