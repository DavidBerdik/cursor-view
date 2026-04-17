"""JS-to-Python bridge exposed to the React UI via pywebview."""

import logging
import pathlib
import urllib.request

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
