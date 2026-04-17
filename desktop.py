#!/usr/bin/env python3
"""Thin shim so ``python3 desktop.py`` still launches the desktop mode.

The real implementation lives in :mod:`cursor_view.desktop`.
"""

from cursor_view.desktop import main


if __name__ == "__main__":
    main()
