"""Markdown export for chat sessions."""

import datetime
import html
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _render_message_images_markdown(images: list[dict[str, Any]]) -> list[str]:
    """Render each image attachment as a raw HTML ``<img>`` line.

    Uses raw HTML rather than ``![alt](uri)`` because markdown
    data-URI references in ``![]()`` are not uniformly supported
    across renderers (GitHub / GitLab / VS Code preview all handle
    raw HTML verbatim, which guarantees the exported file renders
    the same everywhere).

    ``uuid`` flows from upstream bubble JSON and is HTML-escaped
    before interpolation so a uuid containing ``"`` or ``>`` cannot
    break out of the ``alt`` attribute when the exported ``.md`` is
    viewed in a renderer that passes raw HTML through (GitHub /
    GitLab / VS Code preview all do). ``data_uri`` is generated
    locally from the sanitized MIME prefix plus the base64 alphabet,
    so its grammar is already safe for direct interpolation.
    """
    if not images:
        return []
    return [
        '<img src="{src}" alt="Image {uuid}" />'.format(
            src=img.get("data_uri", ""),
            uuid=html.escape(str(img.get("uuid", "")), quote=True),
        )
        for img in images
        if isinstance(img, dict)
    ]


def generate_markdown(chat):
    """Generate a Markdown representation of the chat."""
    logger.info("Generating Markdown for session ID: %s", chat.get('session_id', 'N/A'))
    date_display = "Unknown date"
    if chat.get("date"):
        try:
            date_obj = datetime.datetime.fromtimestamp(chat["date"])
            date_display = date_obj.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.warning("Error formatting date: %s", e)

    project_name = chat.get("project", {}).get("name", "Unknown Project")
    project_path = chat.get("project", {}).get("rootPath", "Unknown Path")
    session_display = chat.get("session_id", "Unknown")

    lines = [
        f"# Cursor Chat: {project_name}",
        "",
        f"- **Project:** {project_name}",
        f"- **Path:** {project_path}",
        f"- **Date:** {date_display}",
        f"- **Session ID:** {session_display}",
        "",
        "---",
        "",
    ]

    messages = chat.get("messages") or []
    if not messages:
        lines.append("*No messages found in this conversation.*")
    else:
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            images = msg.get("images") or []
            if not isinstance(content, str):
                logger.warning("Message %s has invalid content", i + 1)
                content = "Content unavailable"
            elif not content and not images:
                # Truly empty turn: mirror the coalescer's fallback.
                content = "Content unavailable"
            heading = "**User**" if role == "user" else "**Cursor**"
            lines.extend([heading, "", content.rstrip(), ""])
            lines.extend(_render_message_images_markdown(images))
            lines.extend(["---", ""])

    lines.append("")
    lines.append(
        "*Exported from [Cursor View](https://github.com/DavidBerdik/cursor-view)*"
    )
    return "\n".join(lines)
