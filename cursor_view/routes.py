"""Flask HTTP routes for the Cursor View API and static SPA."""

import json
import logging
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request, send_from_directory

from cursor_view.chat_format import (
    coalesce_consecutive_messages_by_role,
    format_chat_for_frontend,
    messages_for_json_export,
)
from cursor_view.extraction import extract_chats
from cursor_view.export_html import (
    generate_markdown,
    generate_standalone_html,
    resolve_export_theme,
)

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)


@bp.route("/api/chats", methods=["GET"])
def get_chats():
    """Get all chat sessions."""
    try:
        logger.info(f"Received request for chats from {request.remote_addr}")
        chats = extract_chats()
        logger.info(f"Retrieved {len(chats)} chats")

        formatted_chats = []
        for chat in chats:
            try:
                formatted_chat = format_chat_for_frontend(chat)
                formatted_chat["messages"] = coalesce_consecutive_messages_by_role(
                    formatted_chat.get("messages", [])
                )
                formatted_chats.append(formatted_chat)
            except Exception as e:
                logger.error(f"Error formatting individual chat: {e}")
                continue

        logger.info(f"Returning {len(formatted_chats)} formatted chats")
        return jsonify(formatted_chats)
    except Exception as e:
        logger.error(f"Error in get_chats: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/api/chat/<session_id>", methods=["GET"])
def get_chat(session_id):
    """Get a specific chat session by ID."""
    try:
        logger.info(f"Received request for chat {session_id} from {request.remote_addr}")
        chats = extract_chats()

        for chat in chats:
            if "session" in chat and chat["session"] and isinstance(chat["session"], dict):
                if chat["session"].get("composerId") == session_id:
                    formatted_chat = format_chat_for_frontend(chat)
                    formatted_chat["messages"] = coalesce_consecutive_messages_by_role(
                        formatted_chat.get("messages", [])
                    )
                    return jsonify(formatted_chat)

        logger.warning(f"Chat with ID {session_id} not found")
        return jsonify({"error": "Chat not found"}), 404
    except Exception as e:
        logger.error(f"Error in get_chat: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/api/chat/<session_id>/export", methods=["GET"])
def export_chat(session_id):
    """Export a specific chat session as HTML, JSON, or Markdown."""
    try:
        logger.info(f"Received request to export chat {session_id} from {request.remote_addr}")
        export_format = request.args.get("format", "html").lower()
        chats = extract_chats()

        for chat in chats:
            if "session" in chat and chat["session"] and isinstance(chat["session"], dict):
                if chat["session"].get("composerId") == session_id:
                    formatted_chat = format_chat_for_frontend(chat)
                    chat_for_export = {
                        **formatted_chat,
                        "messages": coalesce_consecutive_messages_by_role(
                            formatted_chat.get("messages", [])
                        ),
                    }

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

        logger.warning(f"Chat with ID {session_id} not found for export")
        return jsonify({"error": "Chat not found"}), 404
    except Exception as e:
        logger.error(f"Error in export_chat: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@bp.route("/", defaults={"path": ""})
@bp.route("/<path:path>")
def serve_react(path):
    """Serve built static files, or ``index.html`` for client-side routing."""
    static_folder = current_app.static_folder
    if path and Path(static_folder, path).exists():
        return send_from_directory(static_folder, path)
    return send_from_directory(static_folder, "index.html")
