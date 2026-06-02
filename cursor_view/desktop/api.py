"""JS-to-Python bridge exposed to the React UI via pywebview."""

import importlib.metadata
import json
import logging
import pathlib
import platform
import sys
import urllib.request
import webbrowser
from typing import Any
from urllib.parse import urlparse

import webview

from cursor_view import __version__
from cursor_view.desktop.reveal import open_path, reveal_in_file_manager
from cursor_view.paths import cursor_view_cache_dir, cursor_view_log_dir

logger = logging.getLogger(__name__)


# Maps the API's ``format`` parameter (which matches the HTTP export endpoint's
# ``?format=`` query string) to the file extension used in the save dialog.
EXTENSIONS: dict[str, str] = {
    "html": "html",
    "json": "json",
    "markdown": "md",
}

# Custom-event names dispatched into the React app for menu actions that
# the frontend (not Python) owns. The string values MUST stay
# byte-for-byte in sync with the constants in
# ``frontend/src/utils/desktopEvents.js``; the matching listeners live in
# ``frontend/src/hooks/useDesktopMenuEvents.js``.
EVENT_TOGGLE_THEME = "cursor-view:toggle-theme"
EVENT_OPEN_ABOUT = "cursor-view:open-about"


class DesktopApi:
    """JS-to-Python bridge exposed to the React UI via pywebview.

    The embedded webviews (WebView2 / WKWebView / WebKitGTK) do not honor
    the ``<a download>`` blob trick the browser UI uses, so exports need
    to be written to disk from Python using a native save dialog.
    """

    def __init__(
        self,
        port: int,
        debug: bool = False,
        token: str | None = None,
        log_path: "pathlib.Path | None" = None,
    ) -> None:
        self._port = port
        # Private so pywebview's js_api introspection (which exposes every
        # public, non-underscore attribute of this object to JS) does not
        # surface it. menu.py reads it directly to gate the debug-only
        # developer-tools menu item.
        self._debug = debug
        # The loopback-auth token (cursor_view/desktop/auth.py). Private
        # for the same introspection reason; the React app reads it via
        # the public get_token() bridge method below, never as an
        # auto-exposed attribute.
        self._token = token
        # Path to the desktop.log file (cursor_view/desktop/logging_setup.py),
        # stashed for the future "View Logs" / "Open Log File" menu item
        # (Improvement 12). Private for the same introspection reason.
        self._log_path = log_path

    def _active_window(self) -> "webview.Window | None":
        """Return the window menu / bridge actions should target.

        Mirrors :meth:`save_export`'s lookup: prefer the focused window,
        fall back to the first created one, and tolerate the brief
        startup window where neither exists yet.
        """
        win = webview.active_window()
        if win is None and webview.windows:
            win = webview.windows[0]
        return win

    def _dispatch_event(self, event_name: str) -> dict[str, Any]:
        """Dispatch a window ``CustomEvent`` into the embedded React app.

        Menu actions the frontend owns (theme toggle today) are delivered
        as events rather than mutated from Python, so the React app stays
        the single source of truth for its own state. ``json.dumps``
        quotes the event name so an unexpected value cannot break out of
        the evaluated JS string. Returns the ``{ok, error}`` shape rather
        than raising, matching the bridge's never-raise-across-JS rule.
        """
        win = self._active_window()
        if win is None:
            logger.warning("Cannot dispatch %s: no active window", event_name)
            return {"ok": False, "error": "No active window"}
        try:
            win.evaluate_js(
                f"window.dispatchEvent(new CustomEvent({json.dumps(event_name)}))"
            )
        except Exception as exc:
            logger.warning("Failed to dispatch %s to the webview: %s", event_name, exc)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "error": None}

    def get_token(self) -> str:
        """Return the loopback-auth token for the React app to use.

        Called once at boot by the frontend ``useDesktopAuth`` hook,
        which sets it as the default ``X-Cursor-View-Token`` axios
        header so every ``/api/*`` request passes the desktop-mode
        auth gate (see ``cursor_view/desktop/auth.py``). Returns an
        empty string if no token was configured (defensive; desktop
        launches always pass one). Exposing the token to the page is
        safe -- the bridge is reachable only from inside our own
        embedded webview, and the token's purpose is to lock out
        *other* local processes that can read neither the bridge nor
        the in-page value.
        """
        return self._token or ""

    def toggle_theme(self) -> dict[str, Any]:
        """Ask the React app to flip its color scheme.

        The View -> Toggle Theme menu item routes here instead of
        touching theme state in Python: the theme lives entirely in the
        React app (``ThemeModeContext`` plus the persisted cookie), so
        the bridge stays the single source of truth by dispatching the
        same ``cursor-view:toggle-theme`` event the frontend listens for
        via ``useDesktopMenuEvents``.
        """
        return self._dispatch_event(EVENT_TOGGLE_THEME)

    def open_about(self) -> dict[str, Any]:
        """Ask the React app to open the About dialog.

        The Help -> About menu item routes here; the dialog itself lives
        in the React app (it fetches diagnostics via get_diagnostics), so
        the bridge just dispatches the cursor-view:open-about event the
        frontend's useDesktopMenuEvents listens for, mirroring
        toggle_theme.
        """
        return self._dispatch_event(EVENT_OPEN_ABOUT)

    def reload_window(self) -> dict[str, Any]:
        """Reload the current page in the desktop window.

        Uses ``window.location.reload()`` so the in-app route is
        preserved (a ``load_url`` back to ``/`` would always bounce the
        user to the chat list). Returns the ``{ok, error}`` shape and
        never raises across the JS boundary.
        """
        win = self._active_window()
        if win is None:
            logger.warning("reload_window called with no active window")
            return {"ok": False, "error": "No active window"}
        try:
            win.evaluate_js("window.location.reload()")
        except Exception as exc:
            logger.warning("Failed to reload the desktop window: %s", exc)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "error": None}

    def quit_app(self) -> dict[str, Any]:
        """Close the desktop window, unblocking ``webview.start``.

        Destroying every window returns control from the native GUI loop
        so ``run_desktop``'s ``finally`` drains the Flask server and
        releases the single-instance lock. Returns the ``{ok, error}``
        shape; a failure to destroy is logged rather than raised so a
        menu click never escapes pywebview's menu thread.
        """
        windows = list(webview.windows)
        if not windows:
            logger.warning("quit_app called with no windows to destroy")
            return {"ok": False, "error": "No window"}
        try:
            for win in windows:
                win.destroy()
        except Exception as exc:
            logger.warning("Failed to destroy window(s) on quit: %s", exc)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "error": None}

    def toggle_devtools(self) -> dict[str, Any]:
        """Toggle the embedded webview's developer tools (debug builds only).

        pywebview has no portable runtime devtools toggle: dev tools are
        enabled wholesale by ``webview.start(debug=True)`` and surfaced
        through each backend's own affordance (right-click Inspect on
        WebView2 / WKWebView). This method is wired into the menu only
        when the bridge was constructed with ``debug=True``, so the item
        never appears in release builds; it calls the window's
        ``toggle_devtools`` if a backend exposes one and otherwise
        reports the gap in the ``{ok, error}`` shape rather than raising.
        """
        if not self._debug:
            return {
                "ok": False,
                "error": "Developer tools are available in debug builds only",
            }
        win = self._active_window()
        if win is None:
            return {"ok": False, "error": "No active window"}
        toggler = getattr(win, "toggle_devtools", None)
        if not callable(toggler):
            logger.info("Active webview backend exposes no developer-tools toggle")
            return {
                "ok": False,
                "error": "Developer tools toggle is not supported by this backend",
            }
        try:
            toggler()
        except Exception as exc:
            logger.warning("Failed to toggle developer tools: %s", exc)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "error": None}

    def open_log_file(self) -> dict[str, Any]:
        """Open the desktop ``desktop.log`` file in the default handler.

        Backs the View -> View Logs menu item. The path was stashed at
        launch by ``run_desktop`` (Improvement 11). Returns the standard
        ``{ok, error}`` shape; never raises across the JS boundary.
        """
        if self._log_path is None:
            logger.warning("open_log_file called but no log path is configured")
            return {"ok": False, "error": "Log file path is not available"}
        if open_path(self._log_path):
            return {"ok": True, "error": None}
        return {"ok": False, "error": "Could not open the log file"}

    def open_cache_folder(self) -> dict[str, Any]:
        """Open the Cursor View cache directory in the file manager.

        Backs the File -> Open Cache Folder menu item. This is the folder
        holding ``webview-storage/``, ``desktop.lock``, ``logs/``, and the
        chat-index cache.
        """
        try:
            cache_dir = cursor_view_cache_dir()
        except Exception as exc:
            logger.warning("Failed to resolve cache dir: %s", exc)
            return {"ok": False, "error": str(exc)}
        if open_path(cache_dir):
            return {"ok": True, "error": None}
        return {"ok": False, "error": "Could not open the cache folder"}

    def reveal_export(self, path: str) -> dict[str, Any]:
        """Reveal a just-exported file in the OS file manager.

        Called from the post-export Snackbar's "Reveal" action with the
        ``path`` ``save_export`` returned. Selects the file in Finder /
        Explorer (or opens its parent folder on Linux). Returns the
        standard ``{ok, error}`` shape.
        """
        if not isinstance(path, str) or not path:
            logger.warning("reveal_export called without a path: %r", path)
            return {"ok": False, "error": "Missing path"}
        if reveal_in_file_manager(pathlib.Path(path)):
            return {"ok": True, "error": None}
        return {"ok": False, "error": "Could not reveal the file"}

    def get_diagnostics(self) -> dict[str, Any]:
        """Return environment details for the About dialog / bug reports.

        Backs the Help -> About modal. Every value is resolved
        defensively so a single lookup failure (e.g. pywebview metadata
        missing in an odd packaging) degrades to "unknown" rather than
        raising across the JS boundary. ``webview.guilib`` is the active
        platform module once ``webview.start`` is running (it is ``None``
        before that), and its ``renderer`` attribute is the backend name
        (``edgechromium`` / ``cocoa`` / ``gtk`` / ``qt``).
        """
        try:
            pywebview_version = importlib.metadata.version("pywebview")
        except Exception:
            pywebview_version = "unknown"
        backend = getattr(getattr(webview, "guilib", None), "renderer", None) or "unknown"
        try:
            cache_dir = str(cursor_view_cache_dir())
        except Exception:
            cache_dir = "unknown"
        try:
            log_dir = str(cursor_view_log_dir())
        except Exception:
            log_dir = "unknown"
        return {
            "version": __version__,
            "platform": f"{platform.system()} {platform.release()}",
            "pywebview_version": pywebview_version,
            "pywebview_backend": backend,
            "python_version": platform.python_version(),
            "cache_dir": cache_dir,
            "log_dir": log_dir,
        }

    def save_export(
        self,
        session_id: str,
        fmt: str,
        theme: str | None = None,
    ) -> dict:
        """Prompt for a save location and write the exported chat to disk.

        Returns a JSON-serializable result describing the outcome so the
        frontend can surface appropriate feedback.
        """
        if not isinstance(session_id, str) or not session_id:
            return {"saved": False, "error": "Missing session id"}

        ext = EXTENSIONS.get(fmt)
        if ext is None:
            return {"saved": False, "error": f"Unsupported format: {fmt}"}

        default_name = f"cursor-chat-{session_id[:8]}.{ext}"
        win = webview.active_window()
        if win is None and webview.windows:
            win = webview.windows[0]
        if win is None:
            return {"saved": False, "error": "No active window"}

        picked = win.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=default_name,
            file_types=(
                f"{ext.upper()} files (*.{ext})",
                "All files (*.*)",
            ),
        )
        if not picked:
            return {"saved": False, "cancelled": True}
        path = picked if isinstance(picked, str) else picked[0]

        url = (
            f"http://127.0.0.1:{self._port}"
            f"/api/chat/{session_id}/export?format={fmt}"
        )
        if theme in ("light", "dark"):
            url += f"&theme={theme}"

        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
            pathlib.Path(path).write_bytes(data)
        except Exception as e:
            logger.exception("Failed to save export to %s", path)
            return {"saved": False, "error": str(e)}

        return {"saved": True, "path": path}

    def open_url_in_browser(self, url: str) -> dict[str, Any]:
        """Open ``url`` in the user's system default browser.

        Called from the chat context menu when a desktop-mode user
        picks "Open in Browser Tab". Inside a pywebview window, a
        plain ``window.open`` behaves inconsistently across embedded
        webview backends (WebView2 / WKWebView / WebKitGTK /
        QtWebEngine) -- it may be blocked, open a new pywebview
        window, or navigate the current webview away from the chat.
        Round-tripping through the Python bridge and letting stdlib
        :mod:`webbrowser` pick the user's default handler is the
        reliable way to get a sibling system-browser tab.

        The scheme is restricted to ``http`` / ``https`` so a
        compromised frontend (or a malformed href in stored chat
        content) cannot ask the OS to navigate to ``file:///``,
        ``javascript:``, ``data:``, or other schemes that have
        historically been abused. Returns a JSON-serializable dict
        matching the :meth:`save_export` shape rather than raising:
        pywebview marshals the return value back to JS, but any
        exception on this boundary becomes a JS-side opaque error
        that costs the caller the failure mode -- so every failure
        path is logged with lazy ``%s`` formatting and folded into
        an ``error`` key the caller can inspect.
        """
        if not isinstance(url, str) or not url:
            logger.warning("open_url_in_browser called without a URL: %r", url)
            return {"opened": False, "error": "Missing URL"}
        try:
            scheme = urlparse(url).scheme
        except Exception as exc:
            logger.warning("Invalid URL for open_url_in_browser: %s (%s)", url, exc)
            return {"opened": False, "error": "Invalid URL"}
        if scheme not in ("http", "https"):
            logger.warning("Refusing to open non-http(s) URL: %s", url)
            return {"opened": False, "error": "Unsupported scheme"}
        try:
            opened = webbrowser.open(url, new=2)
        except Exception as exc:
            logger.warning("webbrowser.open failed for %s: %s", url, exc)
            return {"opened": False, "error": str(exc)}
        return {"opened": bool(opened), "error": None}
