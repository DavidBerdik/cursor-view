#!/usr/bin/env python3
"""Thin shim so ``python3 terminal.py`` still launches the terminal/server mode.

The real implementation lives in :mod:`cursor_view.terminal`. This file
preserves the familiar top-level invocation while the code itself is
organized inside the ``cursor_view`` package.
"""

from cursor_view.terminal import main


if __name__ == "__main__":
    main()
