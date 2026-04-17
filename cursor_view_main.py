#!/usr/bin/env python3
"""Thin shim so PyInstaller and ``python3 cursor_view_main.py`` still work.

The real unified entry point lives in :mod:`cursor_view.__main__`. The
``cursor-view.spec`` file still references this path, so the shim is kept
to avoid requiring a spec update.
"""

import sys

from cursor_view.__main__ import main


if __name__ == "__main__":
    main(sys.argv[1:])
