#!/usr/bin/env python3
"""Desktop launcher for Cursor View.

Starts the Flask application on a random loopback port in a background
thread and displays it inside a native OS webview window via pywebview,
giving the app the appearance of a standalone desktop application.
"""

import logging
import socket
import threading

import webview
from werkzeug.serving import make_server

from cursor_view.app_factory import create_app

logger = logging.getLogger(__name__)


def _free_port() -> int:
    """Return an available TCP port on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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

    webview.create_window(
        title="Cursor View",
        url=f"http://127.0.0.1:{port}/",
        width=1200,
        height=800,
        min_size=(900, 600),
    )

    try:
        webview.start()
    finally:
        logger.info("Shutting down Flask server")
        server.shutdown()
        server_thread.join(timeout=5)


if __name__ == "__main__":
    main()
