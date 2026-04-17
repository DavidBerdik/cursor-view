#!/usr/bin/env python3
"""
Simple API server to serve Cursor chat data for the web interface.
"""

import argparse
import logging
import threading
import webbrowser

from cursor_view.app_factory import create_app
from cursor_view.paths import cursor_view_cache_dir

logger = logging.getLogger(__name__)


def _cleanup_orphan_temp_files() -> None:
    """Remove ``chat-index.*.tmp*`` files left in the cache dir from prior
    runs that were terminated mid-rebuild (see ``ChatIndex._rebuild``).

    Sweeps only the top level of ``cursor_view_cache_dir()`` so that any
    sibling subdirectories are untouched. Files held open by a
    concurrently-running instance will fail to delete on Windows; those
    errors are logged at debug level and skipped.
    """
    cache_dir = cursor_view_cache_dir()
    removed = 0
    for path in cache_dir.glob("chat-index.*.tmp*"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            logger.debug("Could not remove orphan temp file %s", path, exc_info=True)
    if removed:
        logger.info("Removed %d orphan temp file(s) from %s", removed, cache_dir)


_cleanup_orphan_temp_files()

app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Cursor Chat View server")
    parser.add_argument("--port", type=int, default=5000, help="Port to run the server on")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser automatically",
    )
    args = parser.parse_args()

    logger.info(f"Starting server on port {args.port}")

    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=[f"http://127.0.0.1:{args.port}"]).start()

    app.run(host="127.0.0.1", port=args.port, debug=args.debug)
