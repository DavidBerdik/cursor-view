"""Loopback-token auth coverage for the desktop launcher.

Pins the contract ``cursor_view/desktop/auth.py::install_auth`` enforces:
``/api/*`` is 401 without a valid token (header or cookie), 200 with one,
non-``/api`` paths are never gated, and the SPA HTML shell bootstraps the
``cursor-view-token`` cookie so non-axios same-origin requests inherit it.

Uses a minimal Flask app with stub routes rather than ``create_app`` so
the middleware is exercised in isolation from the chat-index cache and
the user's on-disk Cursor data.
"""

from __future__ import annotations

import unittest

from flask import Flask, Response, jsonify

from cursor_view.desktop import auth


def _build_app(token: str) -> Flask:
    app = Flask(__name__)

    @app.route("/api/ping")
    def _ping():
        return jsonify(ok=True)

    @app.route("/")
    def _index():
        return Response("<html></html>", mimetype="text/html")

    auth.install_auth(app, token)
    return app


class DesktopAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.token = auth.generate_token()
        self.app = _build_app(self.token)
        self.client = self.app.test_client()

    def test_generate_token_is_random_and_nonempty(self) -> None:
        self.assertTrue(self.token)
        self.assertNotEqual(self.token, auth.generate_token())

    def test_api_rejects_missing_token(self) -> None:
        resp = self.client.get("/api/ping")
        self.assertEqual(resp.status_code, 401)

    def test_api_rejects_wrong_header(self) -> None:
        resp = self.client.get(
            "/api/ping", headers={auth.TOKEN_HEADER: "not-the-token"}
        )
        self.assertEqual(resp.status_code, 401)

    def test_api_accepts_correct_header(self) -> None:
        resp = self.client.get(
            "/api/ping", headers={auth.TOKEN_HEADER: self.token}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"ok": True})

    def test_api_accepts_correct_cookie(self) -> None:
        # Mirrors the <img> path: no header, only the bootstrapped cookie.
        self.client.set_cookie(auth.TOKEN_COOKIE, self.token)
        resp = self.client.get("/api/ping")
        self.assertEqual(resp.status_code, 200)

    def test_api_rejects_wrong_cookie(self) -> None:
        self.client.set_cookie(auth.TOKEN_COOKIE, "not-the-token")
        resp = self.client.get("/api/ping")
        self.assertEqual(resp.status_code, 401)

    def test_non_api_path_is_not_gated(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_html_shell_bootstraps_cookie(self) -> None:
        resp = self.client.get("/")
        set_cookie = resp.headers.get("Set-Cookie")
        self.assertIsNotNone(set_cookie)
        self.assertIn(f"{auth.TOKEN_COOKIE}={self.token}", set_cookie)
        # Defense-in-depth attributes: not readable by JS, same-site only.
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)

    def test_options_preflight_passes_without_token(self) -> None:
        # CORS preflight carries no data and must not be gated, or
        # flask-cors cannot answer it.
        resp = self.client.options("/api/ping")
        self.assertNotEqual(resp.status_code, 401)

    def test_cookie_not_resent_when_already_present(self) -> None:
        # Once the client holds the cookie, the HTML shell should not keep
        # re-issuing Set-Cookie on every navigation.
        self.client.set_cookie(auth.TOKEN_COOKIE, self.token)
        resp = self.client.get("/")
        self.assertIsNone(resp.headers.get("Set-Cookie"))


if __name__ == "__main__":
    unittest.main()
