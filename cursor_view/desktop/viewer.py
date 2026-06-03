"""Open-an-exported-chat support for desktop mode.

When the desktop binary is launched with a file path (from the macOS
file-type association declared in ``cursor-view.spec`` or directly on
the command line), ``run_desktop`` reads that single exported-chat JSON
file once at launch and serves it to the React viewer route. This lets
double-clicking a Cursor View export render that one chat **without
going through the chat-index cache** -- the file is the source of
truth, not the user's local Cursor databases (which may not even
contain the exported chat anymore).

The route lives under ``/api/`` so the desktop loopback-token auth
(:mod:`cursor_view.desktop.auth`) gates it exactly like every other API
endpoint; terminal mode never registers it.
"""

import json
import logging
from pathlib import Path
from typing import Any

from flask import Flask, jsonify

logger = logging.getLogger(__name__)

VIEWER_ROUTE = "/api/viewer/opened"


def load_export_file(path: str) -> dict[str, Any] | None:
    """Parse an exported-chat JSON file, returning ``None`` on any failure.

    Never raises: a missing path, unreadable file, or malformed JSON
    degrades to "nothing to show" (the viewer route then 404s and the
    React viewer renders its not-found state) rather than crashing the
    launcher before any window exists. The format is the JSON produced
    by ``GET /api/chat/<id>/export?format=json`` -- a single chat dict
    in the ``format_chat_for_frontend`` shape with image bytes inlined
    as ``data:`` URIs.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError) as exc:
        logger.warning("Could not read exported chat file %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("Exported chat file %s is not a JSON object", path)
        return None
    return data


def register_viewer_route(app: Flask, opened: dict[str, Any] | None) -> None:
    """Register the desktop-only ``GET /api/viewer/opened`` route.

    ``opened`` is the chat parsed from the file passed at launch, or
    ``None`` when the app launched without a file (the route then 404s,
    which the React viewer surfaces as an empty state). Registered only
    from ``run_desktop`` so ``cursor_view/routes.py`` stays free of
    desktop concerns, mirroring the focus-route registration.
    """

    def _opened():
        if opened is None:
            return jsonify({"error": "No file opened"}), 404
        return jsonify(opened)

    app.add_url_rule(VIEWER_ROUTE, "viewer_opened", _opened, methods=["GET"])
