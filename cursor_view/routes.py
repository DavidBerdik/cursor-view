"""Flask HTTP routes for the Cursor View API and static SPA."""

import json
import logging
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request, send_from_directory

from cursor_view.chat_format import messages_for_json_export
from cursor_view.chat_index import get_chat_index
from cursor_view.export import (
    generate_markdown,
    generate_standalone_html,
    resolve_export_theme,
)

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)


def _parse_positive_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(parsed, 0)


def _should_force_refresh() -> bool:
    return request.args.get("refresh", "").lower() in {"1", "true", "yes"}


@bp.route("/api/chats", methods=["GET"])
def get_chats():
    """Get chat summaries, optionally filtered by a search query."""
    try:
        logger.info("Received request for chats from %s", request.remote_addr)
        query = (request.args.get("q") or "").strip()
        limit = _parse_positive_int(request.args.get("limit"))
        offset = _parse_positive_int(request.args.get("offset")) or 0
        payload = get_chat_index().list_summaries(
            query=query,
            limit=limit,
            offset=offset,
            force_refresh=_should_force_refresh(),
        )
        logger.info(
            "Returning %s chat summaries (query=%r total=%s)",
            len(payload["items"]),
            query,
            payload["total"],
        )
        return jsonify(payload)
    except Exception as e:
        logger.error("Error in get_chats: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/api/chat/<session_id>", methods=["GET"])
def get_chat(session_id):
    """Get a specific chat session by ID."""
    try:
        logger.info("Received request for chat %s from %s", session_id, request.remote_addr)
        chat = get_chat_index().get_chat(
            session_id,
            force_refresh=_should_force_refresh(),
        )
        if chat is not None:
            return jsonify(chat)
        logger.warning("Chat with ID %s not found", session_id)
        return jsonify({"error": "Chat not found"}), 404
    except Exception as e:
        logger.error("Error in get_chat: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/api/chat/<session_id>/export", methods=["GET"])
def export_chat(session_id):
    """Export a specific chat session as HTML, JSON, or Markdown."""
    try:
        logger.info(
            "Received request to export chat %s from %s",
            session_id,
            request.remote_addr,
        )
        export_format = request.args.get("format", "html").lower()
        chat_for_export = get_chat_index().get_chat(
            session_id,
            force_refresh=_should_force_refresh(),
        )
        if chat_for_export is None:
            logger.warning("Chat with ID %s not found for export", session_id)
            return jsonify({"error": "Chat not found"}), 404

        if export_format == "json":
            json_payload = {
                **chat_for_export,
                "messages": messages_for_json_export(
                    chat_for_export.get("messages", [])
                ),
            }
            return Response(
                json.dumps(json_payload, indent=2),
                mimetype="application/json; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="cursor-chat-{session_id[:8]}.json"',
                    "Cache-Control": "no-store",
                },
            )

        if export_format == "markdown":
            md_content = generate_markdown(chat_for_export)
            md_bytes = md_content.encode("utf-8")
            return Response(
                md_content,
                mimetype="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="cursor-chat-{session_id[:8]}.md"',
                    "Content-Length": str(len(md_bytes)),
                    "Cache-Control": "no-store",
                },
            )

        export_theme = resolve_export_theme(
            request.args.get("theme"),
            request.cookies.get("themeMode"),
        )
        html_content = generate_standalone_html(chat_for_export, export_theme)
        return Response(
            html_content,
            mimetype="text/html; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="cursor-chat-{session_id[:8]}.html"',
                "Content-Length": str(len(html_content)),
                "Cache-Control": "no-store",
            },
        )
    except Exception as e:
        logger.error("Error in export_chat: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/", defaults={"path": ""})
@bp.route("/<path:path>")
def serve_react(path):
    """Serve built static files, or ``index.html`` for client-side routing."""
    static_folder = current_app.static_folder
    if path and Path(static_folder, path).exists():
        return send_from_directory(static_folder, path)
    return send_from_directory(static_folder, "index.html")
