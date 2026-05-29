"""Readiness probe for the desktop launcher's embedded Flask server.

pywebview navigates to the loopback URL the instant the window is
created, but Werkzeug's ``serve_forever`` runs on a background daemon
thread that may not be accepting connections yet on a cold launch.
Without a synchronization point the user briefly sees the embedded
webview's native "site can't be reached" frame before the React app
loads. ``wait_for_server`` is that synchronization point: poll
``GET /`` until the server answers so the window can stay on its splash
until the real page is actually serveable.

Stdlib-only on purpose (no ``requests`` dependency) to keep the
PyInstaller bundle and its import-time cost lean, mirroring the
stdlib-only discipline of the image-loading and export modules.
"""

import logging
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def wait_for_server(port: int, timeout: float = 10.0) -> bool:
    """Poll ``http://127.0.0.1:{port}/`` until it returns HTTP 200.

    Returns ``True`` as soon as the server answers with a 200, or
    ``False`` if ``timeout`` seconds elapse first. Polls every 50ms with
    a 0.5s per-request timeout so a single slow request cannot starve
    the loop and the caller never blocks longer than ``timeout``.

    Connection-refused while the daemon thread is still binding the
    socket is the expected steady state of a cold launch, so the first
    failed attempt is silent; only retries past the first log (lazy
    ``%s``) to surface a genuinely slow start without flooding the log.
    """
    url = f"http://127.0.0.1:{port}/"
    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError) as exc:
            if attempt > 1:
                logger.info(
                    "Flask server not ready on %s (attempt %s): %s",
                    url,
                    attempt,
                    exc,
                )
        time.sleep(0.05)

    logger.warning(
        "Flask server did not become ready on %s within %.1fs", url, timeout
    )
    return False
