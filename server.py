#!/usr/bin/env python3
"""
Simple API server to serve Cursor chat data for the web interface.
"""

import argparse
import logging
import threading
import webbrowser

from cursor_view.app_factory import create_app

logger = logging.getLogger(__name__)

app = create_app()


def run_server(port: int = 5000, debug: bool = False, no_browser: bool = False) -> None:
    """Start the Flask development server, optionally auto-opening the browser."""
    logger.info(f"Starting server on port {port}")

    if not no_browser:
        threading.Timer(1.5, webbrowser.open, args=[f"http://127.0.0.1:{port}"]).start()

    app.run(host="127.0.0.1", port=port, debug=debug)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Cursor Chat View server")
    parser.add_argument("--port", type=int, default=5000, help="Port to run the server on")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser automatically",
    )
    args = parser.parse_args()
    run_server(port=args.port, debug=args.debug, no_browser=args.no_browser)


if __name__ == "__main__":
    main()
