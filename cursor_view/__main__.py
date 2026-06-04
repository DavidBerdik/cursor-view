#!/usr/bin/env python3
"""Unified Cursor View entry point.

Routes between the native pywebview desktop UI (the default) and the
terminal/Flask server based on command line flags. This is the script
that PyInstaller bundles into the standalone ``cursor-view`` binary.

By default (no flags), the binary launches the desktop UI: it starts the
Flask server on a random loopback port and renders the chat UI inside a
native OS webview window. Passing ``--terminal`` opts back into the
original browser flow (Flask on port 5000 plus the auto-opened browser).
The legacy ``--desktop`` flag is accepted for one release as a no-op so
existing launch scripts keep working, but it now selects what is already
the default.
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
            "Defaults to the native desktop (webview) UI; pass --terminal "
            "to run the Flask server and open the UI in your browser "
            "instead."
        ),
    )
    parser.add_argument(
        "--terminal",
        action="store_true",
        help="Run the Flask server and open the UI in your browser instead of the desktop window.",
    )
    parser.add_argument(
        "--desktop",
        action="store_true",
        help=(
            "Deprecated no-op: the desktop UI is now the default. Accepted "
            "for one release so existing launch scripts keep working."
        ),
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
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help=(
            "Path to an exported chat JSON file to open in the single-chat "
            "desktop viewer. Forces desktop mode (the viewer route lives "
            "only there); used by the macOS file-type association."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.desktop:
        logger.info(
            "%s is now the default and the flag is deprecated; it will be "
            "removed in a future release.",
            "--desktop",
        )

    # A positional file argument always implies the desktop single-chat
    # viewer: the viewer route only exists in desktop mode (run_desktop
    # reads the file and serves it), and the macOS file-type association
    # launches via `open` without any flag. So a file forces desktop even
    # if --terminal was also passed.
    if args.terminal and args.file is not None:
        logger.warning(
            "Ignoring --terminal because a file argument implies the desktop "
            "viewer (%s).",
            args.file,
        )
    terminal_mode = args.terminal and args.file is None

    if terminal_mode:
        from cursor_view.terminal import run_server

        run_server(port=args.port, debug=args.debug, no_browser=args.no_browser)
        return

    # Desktop mode (the default). Terminal-only flags are silently ignored
    # here; warn the user so a misplaced --port doesn't appear to take
    # effect.
    for flag_name, flag_value, default in (
        ("--port", args.port, 5000),
        ("--debug", args.debug, False),
        ("--no-browser", args.no_browser, False),
    ):
        if flag_value != default:
            logger.warning(
                "Ignoring %s in desktop mode (terminal-mode flag).",
                flag_name,
            )

    if args.file is not None and not args.desktop:
        logger.info(
            "Opening %s in the desktop viewer (a file argument implies the "
            "desktop viewer).",
            args.file,
        )

    from cursor_view.desktop import run_desktop

    run_desktop(open_file=args.file)


if __name__ == "__main__":
    main(sys.argv[1:])
