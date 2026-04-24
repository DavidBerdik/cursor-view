"""JS-to-Python bridge exposed to the React UI via pywebview."""

import logging
import pathlib
import urllib.request
import webbrowser
from typing import Any
from urllib.parse import urlparse

import webview

logger = logging.getLogger(__name__)


# Maps the API's ``format`` parameter (which matches the HTTP export endpoint's
# ``?format=`` query string) to the file extension used in the save dialog.
EXTENSIONS: dict[str, str] = {
    "html": "html",
    "json": "json",
    "markdown": "md",
}


class DesktopApi:
    """JS-to-Python bridge exposed to the React UI via pywebview.

    The embedded webviews (WebView2 / WKWebView / WebKitGTK) do not honor
    the ``<a download>`` blob trick the browser UI uses, so exports need
    to be written to disk from Python using a native save dialog.
    """

    def __init__(self, port: int) -> None:
        self._port = port

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
