"""Markdown export for chat sessions."""

import datetime
import logging

logger = logging.getLogger(__name__)


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
            if not content or not isinstance(content, str):
                logger.warning("Message %s has invalid content", i + 1)
                content = "Content unavailable"
            heading = "**User**" if role == "user" else "**Cursor**"
            lines.extend([heading, "", content.rstrip(), "", "---", ""])

    lines.append("")
    lines.append(
        "*Exported from [Cursor View](https://github.com/DavidBerdik/cursor-view)*"
    )
    return "\n".join(lines)
