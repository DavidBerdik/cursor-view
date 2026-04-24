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


def _markdown_header_lines(chat: dict[str, Any]) -> list[str]:
    """Return the leading header block for a chat's Markdown export.

    Covers the ``# Cursor Chat: ...`` title, the four info bullets
    (project / path / date / session id), and the trailing ``---``
    thematic break plus its blank line before the message stream.
    Date formatting falls back to ``"Unknown date"`` when the
    ``date`` field is missing or unparseable so the header never
    bubbles an exception out of the export path.
    """
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

    return [
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


def _markdown_message_lines(msg: dict[str, Any], index: int) -> list[str]:
    """Return the Markdown lines for one message, images included.

    Emits, in order: the role heading, a blank line, the trimmed
    content (with a ``"Content unavailable"`` fallback for truly
    empty turns and for non-string content -- mirrors the coalescer
    convention), another blank line, the ``<img>`` lines from
    :func:`_render_message_images_markdown`, a blank separator when
    the helper produced any image lines (see intent comment below),
    and a trailing ``---`` thematic break + blank line. ``index``
    is the message's 0-based position and is used only to identify
    the turn in the non-string-content warning log.
    """
    role = msg.get("role", "unknown")
    content = msg.get("content", "")
    images = msg.get("images") or []
    if not isinstance(content, str):
        logger.warning("Message %s has invalid content", index + 1)
        content = "Content unavailable"
    elif not content and not images:
        content = "Content unavailable"
    heading = "**User**" if role == "user" else "**Cursor**"
    lines = [heading, "", content.rstrip(), ""]
    image_lines = _render_message_images_markdown(images)
    if image_lines:
        lines.extend(image_lines)
        # Blank line so CommonMark renders the trailing ``---`` as a
        # thematic break, not a setext-H2 underline of the preceding
        # paragraph (the final ``<img>`` tag) or as literal dashes.
        # Text-only messages already have this blank from the
        # ``content.rstrip()`` + ``""`` pair above; images would
        # otherwise butt up against the ``---``.
        lines.append("")
    lines.extend(["---", ""])
    return lines


def generate_markdown(chat):
    """Generate a Markdown representation of the chat."""
    logger.info("Generating Markdown for session ID: %s", chat.get('session_id', 'N/A'))
    lines = _markdown_header_lines(chat)
    messages = chat.get("messages") or []
    if not messages:
        lines.append("*No messages found in this conversation.*")
    else:
        for i, msg in enumerate(messages):
            lines.extend(_markdown_message_lines(msg, i))
    lines.append("")
    lines.append(
        "*Exported from [Cursor View](https://github.com/DavidBerdik/cursor-view)*"
    )
    return "\n".join(lines)
