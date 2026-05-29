"""Native startup-error dialog for the desktop launcher.

When the desktop launch sequence fails before the main window can load
(a port that lost the ``free_port`` race and is now bound, no privileges
to bind the loopback socket, a ``cleanup_orphan_temp_files`` error, or a
server that never answers the readiness probe), there is nowhere useful
for a traceback to go: terminal mode would print it, but the desktop
binary is headless on Windows once the console is suppressed
(Improvement 07). This module surfaces the failure in a small native
pywebview window instead so the user sees *something* actionable.

The error markup is rendered via ``webview.create_window(html=...)``
rather than a ``data:`` URI for the same reason as the splash
(:mod:`cursor_view.desktop.splash`): Chromium-based backends block
top-level ``data:`` navigation. The user-supplied message and traceback
are always HTML-escaped before they reach the markup so a failure string
containing ``<`` / ``&`` cannot break (or inject into) the page.
"""

import html
import logging

import webview

logger = logging.getLogger(__name__)


_ERROR_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cursor View</title>
<style>
  html, body {{ margin: 0; height: 100%; }}
  body {{
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 28px 32px;
    background: #0b1f29;
    color: #e6edf3;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      Helvetica, Arial, sans-serif;
  }}
  h1 {{ font-size: 20px; margin: 0; }}
  .message {{ font-size: 14px; line-height: 1.5; white-space: pre-wrap; }}
  details {{
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(230, 237, 243, 0.12);
    border-radius: 6px;
    padding: 10px 12px;
    font-size: 12px;
  }}
  summary {{ cursor: pointer; user-select: none; }}
  pre {{
    margin: 10px 0 0;
    max-height: 220px;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo,
      monospace;
    color: #c9d1d9;
  }}
  .actions {{ margin-top: auto; }}
  button {{
    font: inherit;
    padding: 8px 18px;
    border: 0;
    border-radius: 6px;
    background: #2a9fd6;
    color: #04222e;
    font-weight: 600;
    cursor: pointer;
  }}
</style>
</head>
<body>
  <h1>Cursor View couldn&#39;t start</h1>
  <div class="message">{message}</div>
  {traceback_block}
  <div class="actions">
    <button onclick="window.pywebview.api.close()">Close</button>
  </div>
</body>
</html>"""


_TRACEBACK_BLOCK_TEMPLATE = """<details>
    <summary>Technical details</summary>
    <pre>{traceback}</pre>
  </details>"""


def build_error_html(message: str, traceback_text: str | None = None) -> str:
    """Return the startup-error page markup with all dynamic text escaped.

    Separated from :func:`show_startup_error` so the same page can be
    loaded into an already-open window (e.g. the splash window when the
    readiness probe times out after ``webview.start`` is already running
    and a second ``webview.start`` is therefore not possible).
    """
    if traceback_text:
        traceback_block = _TRACEBACK_BLOCK_TEMPLATE.format(
            traceback=html.escape(traceback_text)
        )
    else:
        traceback_block = ""
    return _ERROR_PAGE_TEMPLATE.format(
        message=html.escape(message or "An unknown error occurred."),
        traceback_block=traceback_block,
    )


class _CloseApi:
    """Minimal JS bridge so the page's Close button can dismiss the window.

    ``window.close()`` from script is unreliable across the embedded
    backends for a window navigated via the native string-loader, so the
    button routes through this bridge instead. The native window close
    button works regardless; this just makes the in-page button work too.
    """

    def __init__(self) -> None:
        self._window: webview.Window | None = None

    def bind(self, window: "webview.Window") -> None:
        self._window = window

    def close(self) -> None:
        if self._window is not None:
            self._window.destroy()


def show_startup_error(message: str, traceback_text: str | None = None) -> None:
    """Show a blocking native error window and return once it is dismissed.

    Runs its own ``webview.start()`` loop, so it must only be called when
    the main GUI loop is not already running (i.e. for failures that
    happen before ``run_desktop`` reaches ``webview.start``). The caller
    is responsible for exiting with a non-zero status afterward.
    """
    logger.error("Showing startup-error window: %s", message)
    api = _CloseApi()
    window = webview.create_window(
        title="Cursor View",
        html=build_error_html(message, traceback_text),
        js_api=api,
        width=620,
        height=440,
    )
    api.bind(window)
    webview.start()
