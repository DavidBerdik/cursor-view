"""Native menu bar for the desktop window.

Builds the File / Edit / View / Help menu tree that ``run_desktop``
passes to ``webview.start(menu=...)``. Every cross-mode action (theme
toggle, reload, quit, external links) routes through a
:class:`cursor_view.desktop.api.DesktopApi` method so the bridge stays
the single source of truth shared with terminal mode and the
keyboard-shortcut path (Improvement 06): the menu never reimplements an
action the bridge already owns. The clipboard edit commands are the one
exception -- they are pure embedded-webview operations with no
cross-mode meaning, so they are delegated straight to the webview via
``document.execCommand`` rather than round-tripping through Python.

``build_menu`` is pure: it constructs and returns the tree with no side
effects, so importing this module never touches process state. Some
pywebview backends (notably WebKitGTK) silently ignore ``menu=``;
``run_desktop`` gates construction behind a ``hasattr`` check and falls
back to no menu (see the "Native menu bar" invariant in
``.cursor/rules/desktop-mode.mdc``).
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import webview

if TYPE_CHECKING:
    from cursor_view.desktop.api import DesktopApi

logger = logging.getLogger(__name__)

# pywebview's webview.menu.MenuAction takes only (title, function) -- it has
# no shortcut/key parameter (the upstream class still carries a
# "# TODO: support platform-agnostic shortcut" stub), and no backend binds an
# accelerator from the menu. The actual key handling therefore lives in the
# frontend (frontend/src/hooks/useGlobalKeyboardShortcuts.js, wired from
# App.js in desktop mode for Reload / Quit / Toggle Theme; clipboard edit keys
# are handled natively by the embedded webview). The accelerator strings below
# are display-only hints appended to the item titles so the shortcuts are
# discoverable in the menu, using the platform-correct modifier (Cmd on macOS,
# Ctrl elsewhere).
_IS_MAC = sys.platform == "darwin"


def _with_accelerator(title: str, key: str) -> str:
    """Append a platform-correct, display-only accelerator hint to a title.

    pywebview cannot bind the accelerator (see the module note), so this is
    purely a discoverability hint; the binding lives in the frontend hook
    and must use the same combo.
    """
    combo = f"\u2318{key}" if _IS_MAC else f"Ctrl+{key}"
    return f"{title} ({combo})"

# Canonical project URLs surfaced by the Help menu. These are the
# project's own repository (mirrored by the Header GitHub button), not
# user-specific configuration, so a literal here is intentional. Both
# open through the bridge's open_url_in_browser so the embedded webview
# never becomes a general-purpose browser tab.
GITHUB_URL = "https://github.com/DavidBerdik/cursor-view"
DOCUMENTATION_URL = f"{GITHUB_URL}#readme"


def _run_edit_command(command: str) -> None:
    """Run a clipboard / selection ``document.execCommand`` in the webview.

    The Edit menu items are deliberately *not* bridge methods: cut /
    copy / paste / select-all are native embedded-webview operations
    with no terminal-mode counterpart, so they are delegated to the
    active window's DOM rather than routed through Python state. Any
    failure is logged with lazy ``%s`` formatting and swallowed -- a
    menu click must never raise out of pywebview's menu thread.
    """
    window = webview.active_window()
    if window is None and webview.windows:
        window = webview.windows[0]
    if window is None:
        logger.warning("Edit command %s fired with no active window", command)
        return
    try:
        window.evaluate_js(f"document.execCommand('{command}')")
    except Exception as exc:
        logger.warning("Edit command %s failed in the webview: %s", command, exc)


def build_menu(api: "DesktopApi") -> list["webview.menu.Menu"]:
    """Return the File / Edit / View / Help menu tree for ``webview.start``.

    Each leaf action is a thin wrapper around a bridge method so the
    desktop menu, the future keyboard shortcuts, and the React UI all
    drive the same code path. The View menu's developer-tools item is
    appended only for debug builds (``api`` constructed with
    ``debug=True``) so release builds never expose it.
    """
    Menu = webview.menu.Menu
    Action = webview.menu.MenuAction
    Separator = webview.menu.MenuSeparator

    file_menu = Menu(
        "File",
        [
            Action(_with_accelerator("Reload", "R"), api.reload_window),
            Action("Open Cache Folder", api.open_cache_folder),
            Separator(),
            Action(_with_accelerator("Quit", "Q"), api.quit_app),
        ],
    )

    edit_menu = Menu(
        "Edit",
        [
            Action(_with_accelerator("Cut", "X"), lambda: _run_edit_command("cut")),
            Action(_with_accelerator("Copy", "C"), lambda: _run_edit_command("copy")),
            Action(_with_accelerator("Paste", "V"), lambda: _run_edit_command("paste")),
            Separator(),
            Action(
                _with_accelerator("Select All", "A"),
                lambda: _run_edit_command("selectAll"),
            ),
        ],
    )

    view_items = [
        Action(_with_accelerator("Toggle Theme", "T"), api.toggle_theme),
        Action("View Logs", api.open_log_file),
    ]
    # Underscore attribute read is intentional: _debug is private to the
    # bridge and must stay out of the JS-exposed surface pywebview builds
    # from DesktopApi's public methods, so menu.py (a sibling in the same
    # subpackage) reads it directly rather than via an exposed accessor.
    if api._debug:
        view_items.append(Separator())
        view_items.append(Action("Toggle Developer Tools", api.toggle_devtools))
    view_menu = Menu("View", view_items)

    help_menu = Menu(
        "Help",
        [
            Action("Documentation", lambda: api.open_url_in_browser(DOCUMENTATION_URL)),
            Action("GitHub", lambda: api.open_url_in_browser(GITHUB_URL)),
        ],
    )

    return [file_menu, edit_menu, view_menu, help_menu]
