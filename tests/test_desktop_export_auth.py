"""Regression coverage for the desktop ``save_export`` auth-token fix.

Pins the contract that ``DesktopApi.save_export`` attaches the
loopback-auth token to its own in-process request. Pre-fix, the method
issued a bare ``urllib.request.urlopen(url)`` with no
``X-Cursor-View-Token`` header and no ``cursor-view-token`` cookie, so
the ``install_auth`` ``before_request`` gate (Improvement 10) 401'd it
and the desktop "Save as..." flow reported an error with no file
written. Post-fix the method builds a ``urllib.request.Request`` and adds
the header from ``self._token`` before opening it.

The test imports ``cursor_view.desktop.api`` (which imports ``webview``);
guard the suite with a SkipTest so an environment without pywebview stays
green, mirroring the import-safety posture of the other desktop tests.
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest
import urllib.request
from unittest.mock import patch

try:
    import webview  # noqa: F401
except Exception as exc:  # pragma: no cover - env without pywebview
    raise unittest.SkipTest(f"pywebview not importable: {exc}")

from cursor_view.desktop.api import DesktopApi
from cursor_view.desktop.auth import TOKEN_HEADER


class _FakeWindow:
    """Stand-in for a pywebview window that returns a fixed save path."""

    def __init__(self, save_path: str) -> None:
        self._save_path = save_path

    def create_file_dialog(self, *args, **kwargs) -> str:
        return self._save_path


class _FakeResponse:
    """Context-manager stand-in for ``urllib.request.urlopen``'s return."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def read(self) -> bytes:
        return self._data


class SaveExportAttachesTokenTest(unittest.TestCase):
    """``save_export`` must present the loopback token on its export fetch."""

    TOKEN = "test-token-abc123"
    EXPORTED = b"exported-bytes"
    SESSION_ID = "11111111-1111-1111-1111-111111111111"

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cursor-view-export-")
        self.save_path = str(pathlib.Path(self._tmp) / "out.json")
        self.api = DesktopApi(port=54321, token=self.TOKEN)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_export_attaches_token_header(self) -> None:
        captured: list[urllib.request.Request] = []

        def capturing_urlopen(req, *args, **kwargs):
            captured.append(req)
            return _FakeResponse(self.EXPORTED)

        with patch(
            "cursor_view.desktop.api.webview.active_window",
            return_value=_FakeWindow(self.save_path),
        ), patch(
            "cursor_view.desktop.api.urllib.request.urlopen",
            side_effect=capturing_urlopen,
        ):
            result = self.api.save_export(self.SESSION_ID, "json")

        self.assertEqual(result, {"saved": True, "path": self.save_path})

        self.assertEqual(
            len(captured), 1,
            "save_export should open exactly one loopback request",
        )
        request = captured[0]
        self.assertIsInstance(
            request, urllib.request.Request,
            "save_export must pass a Request (not a bare URL) so it can carry the token",
        )
        # urllib capitalizes header keys, so X-Cursor-View-Token is stored
        # as X-cursor-view-token; get_header normalizes the same way.
        self.assertEqual(
            request.get_header(TOKEN_HEADER.capitalize()),
            self.TOKEN,
            "the export request must carry the loopback-auth token header",
        )

        self.assertEqual(
            pathlib.Path(self.save_path).read_bytes(),
            self.EXPORTED,
            "the fetched export bytes must be written to the picked path",
        )


if __name__ == "__main__":
    unittest.main()
