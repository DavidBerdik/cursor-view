#!/usr/bin/env python3
"""Unified Cursor View entry point.

Routes between the terminal/Flask server (default) and the experimental
pywebview-based desktop UI based on command line flags. This is the script
that PyInstaller bundles into the standalone ``cursor-view`` binary.

By default (no flags), the binary behaves like the original ``cursor-view``
on every platform: it starts the Flask server on port 5000 and opens the
chat UI in the user's default browser. Passing ``--desktop`` opts into the
experimental webview UI added on the ``1.0.5-dev`` branch.
"""

import argparse
import logging
import sys


logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cursor-view",
        description=(
            "View, search, and export Cursor AI chat histories. "
            "Defaults to the terminal/server mode that opens the UI in your "
            "browser; pass --desktop to launch the experimental webview UI "
            "instead."
        ),
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="Launch the experimental desktop (pywebview) UI instead of the browser.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port for the Flask server to listen on (terminal mode only). Default: 5000",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run the Flask server in debug mode (terminal mode only).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser automatically (terminal mode only).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.desktop:
        # Terminal-only flags are silently ignored in desktop mode; warn the
        # user so a misplaced --port doesn't appear to take effect.
        for flag_name, flag_value, default in (
            ("--port", args.port, 5000),
            ("--debug", args.debug, False),
            ("--no-browser", args.no_browser, False),
        ):
            if flag_value != default:
                logger.warning(
                    "Ignoring %s in --desktop mode (terminal-mode flag).",
                    flag_name,
                )

        from desktop import run_desktop

        run_desktop()
        return

    from server import run_server

    run_server(port=args.port, debug=args.debug, no_browser=args.no_browser)


if __name__ == "__main__":
    main(sys.argv[1:])
