"""Inline HTML splash payload shown while the Flask server warms up.

The desktop window renders this self-contained splash the instant it is
created so the user sees the Cursor View wordmark instead of the
embedded webview's native blank / "site can't be reached" frame during
the readiness probe in :mod:`cursor_view.desktop.readiness`.

The splash is fed to ``webview.create_window(html=...)`` rather than a
``data:`` URI: Chromium-based backends (notably WebView2 on Windows)
block *top-level* navigation to ``data:`` URLs, so an initial
``url="data:text/html;..."`` is resolved as a relative path against the
loopback origin and 404s. ``html=`` routes through each backend's
native string-loader (WebView2 ``NavigateToString``, WKWebView
``loadHTMLString``, WebKitGTK ``load_html``) which has no such
restriction. Keeping the markup inline (not a file under
``cursor_view/export/vendor/``, which is reserved for HTML-export
third-party assets per ``project-layout.mdc``) means it needs no disk
read and ships inside the PyInstaller bundle for free.
"""

# Neutral dark background rather than a theme-matched one: the splash is
# only on screen for the duration of the readiness probe (typically well
# under a second) and the real React app immediately re-themes from the
# persisted preference, so matching the user's light/dark choice here is
# not worth threading the cookie into the launcher.
_SPLASH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cursor View</title>
<style>
  html, body { margin: 0; height: 100%; }
  body {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 22px;
    background: #0b1f29;
    color: #e6edf3;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      Helvetica, Arial, sans-serif;
  }
  .spinner {
    width: 38px;
    height: 38px;
    border: 3px solid rgba(230, 237, 243, 0.18);
    border-top-color: #2a9fd6;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  .wordmark {
    font-size: 26px;
    font-weight: 600;
    letter-spacing: 0.5px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) {
    .spinner { animation: none; }
  }
</style>
</head>
<body>
  <div class="spinner"></div>
  <div class="wordmark">Cursor View</div>
</body>
</html>"""


def splash_html() -> str:
    """Return the splash screen markup for ``webview.create_window(html=...)``."""
    return _SPLASH_HTML
