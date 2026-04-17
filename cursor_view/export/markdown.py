"""Markdown export for chat sessions."""

import datetime
import logging

logger = logging.getLogger(__name__)


def generate_markdown(chat):
    """Generate a Markdown representation of the chat."""
    logger.info(f"Generating Markdown for session ID: {chat.get('session_id', 'N/A')}")
    date_display = "Unknown date"
    if chat.get("date"):
        try:
            date_obj = datetime.datetime.fromtimestamp(chat["date"])
            date_display = date_obj.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.warning(f"Error formatting date: {e}")

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
                logger.warning(f"Message {i + 1} has invalid content")
                content = "Content unavailable"
            heading = "**User**" if role == "user" else "**Cursor**"
            lines.extend([heading, "", content.rstrip(), "", "---", ""])

    lines.append("")
    lines.append(
        "*Exported from [Cursor View](https://github.com/DavidBerdik/cursor-view)*"
    )
    return "\n".join(lines)
