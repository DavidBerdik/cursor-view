"""Loopback-token authentication for desktop mode.

The desktop launcher serves the same Flask app on a random ``127.0.0.1``
port that terminal mode does. The random port alone only deters
drive-by scans -- any local process (another browser, ``curl``, malware
running as the same user) that discovers the port can otherwise fetch
every indexed chat. This module gates ``/api/*`` behind a per-launch
secret so only callers that received the token (the embedded webview)
can read data.

Installed **only** from ``cursor_view/desktop/__init__.py::run_desktop``;
terminal mode never calls ``install_auth`` and is unchanged, preserving
the existing browser-mode behavior. Nothing here is imported by
``cursor_view/routes.py`` so the HTTP routes stay free of desktop
concerns.
"""

import hmac
import logging
import secrets

from flask import Flask, Response, jsonify, request

logger = logging.getLogger(__name__)

# Sent by the React app on every axios request (set from the bridge's
# get_token()), and the name the gate looks for first.
TOKEN_HEADER = "X-Cursor-View-Token"
# Set on the SPA shell response so non-axios same-origin requests
# (notably <img src="/api/chat/.../image/...">) carry the token
# automatically without any JS wiring.
TOKEN_COOKIE = "cursor-view-token"


def generate_token() -> str:
    """Return a fresh URL-safe secret for a single desktop launch."""
    return secrets.token_urlsafe(32)


def _is_authorized(token: str) -> bool:
    """Return True iff the request carries the matching token.

    Accepts the token via the ``X-Cursor-View-Token`` header (axios path)
    or the ``cursor-view-token`` cookie (the automatic ``<img>`` path).
    Uses ``hmac.compare_digest`` so the comparison does not leak the
    token through timing.
    """
    provided = request.headers.get(TOKEN_HEADER) or request.cookies.get(TOKEN_COOKIE)
    if not provided:
        return False
    return hmac.compare_digest(provided, token)


def install_auth(app: Flask, token: str) -> None:
    """Gate ``/api/*`` behind ``token`` and bootstrap the cookie.

    Registers two app-level hooks (not a blueprint, which would have to
    shadow the catch-all ``/`` route in ``cursor_view/routes.py`` and
    risk an ambiguous mapping):

    - a ``before_request`` 401 gate on ``/api/*`` for requests missing or
      carrying the wrong token, and
    - an ``after_request`` that sets the ``cursor-view-token`` cookie on
      the SPA HTML shell so the webview holds the token before it issues
      any image request.

    Both run only because ``run_desktop`` called this; ``routes.py`` is
    untouched.
    """

    @app.before_request
    def _require_token() -> Response | None:
        # Only protect the data API. The SPA shell, its static assets,
        # and the desktop focus route are not under /api/ and serve
        # freely so the cookie can be bootstrapped before the first
        # authenticated request. CORS preflight carries no data and must
        # pass so flask-cors can answer it.
        if request.method == "OPTIONS":
            return None
        if not request.path.startswith("/api/"):
            return None
        if _is_authorized(token):
            return None
        logger.warning(
            "Rejecting unauthenticated %s %s from %s",
            request.method,
            request.path,
            request.remote_addr,
        )
        return jsonify({"error": "Unauthorized"}), 401

    @app.after_request
    def _bootstrap_cookie(response: Response) -> Response:
        # Set the token cookie on the SPA HTML shell (served for "/" and
        # any client-side route deep link) so same-origin <img> requests
        # that never touch axios still pass the gate. Skip when the
        # request already presented the cookie to avoid re-sending it on
        # every navigation. HttpOnly: the React app reads the token from
        # the bridge (get_token()), never from document.cookie, so JS
        # never needs read access. Not Secure because the loopback origin
        # is plain http; SameSite=Strict since every legitimate request
        # is same-origin.
        if (
            response.mimetype == "text/html"
            and request.cookies.get(TOKEN_COOKIE) != token
        ):
            response.set_cookie(
                TOKEN_COOKIE,
                token,
                httponly=True,
                samesite="Strict",
                path="/",
            )
        return response
