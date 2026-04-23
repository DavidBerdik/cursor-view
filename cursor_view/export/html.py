"""Standalone HTML export for chat sessions.

The large CSS skin that wraps the export lives in
:mod:`cursor_view.export.html_styles` as the public
:data:`HTML_STYLE_TEMPLATE` constant; this module imports and
``format_map``-substitutes it with an :data:`EXPORT_HTML_THEMES` palette
entry inside :func:`generate_standalone_html`. Keeping the CSS in a
sibling module keeps ``html.py`` focused on rendering logic and gives
future contributors a single obvious home for new style rules.
"""

import datetime
import html
import logging
import re
from typing import Any

import markdown

from cursor_view.export.html_styles import HTML_STYLE_TEMPLATE
from cursor_view.export.markdown_fences import normalize_markdown_for_html_export
from cursor_view.export.mermaid import (
    build_mermaid_init_script,
    load_vendored_mermaid_js,
    transform_mermaid_fences_to_html,
)
from cursor_view.export.themes import EXPORT_HTML_THEMES

logger = logging.getLogger(__name__)


def _render_message_images_html(
    images: list[dict[str, Any]],
    role: str,
    theme: dict[str, Any],
) -> str:
    """Return a ``<div class="message-images">`` block for one message.

    ``theme`` is reserved for a future tinted-placeholder fallback
    that will need access to palette tokens without re-importing
    :data:`EXPORT_HTML_THEMES`; v1 does not consume it. Sizing is
    inherited from the pre-existing ``.message-content img`` ruleset
    so this helper does not re-declare ``max-width``.
    """
    del theme  # intentionally unused in v1; documented above
    if not images:
        return ""
    who = "user" if role == "user" else "Cursor"
    alt = html.escape(f"Image attached by {who}")
    tags = [
        f'<img src="{img.get("data_uri", "")}" alt="{alt}" />'
        for img in images
        if isinstance(img, dict)
    ]
    if not tags:
        return ""
    return '<div class="message-images">\n' + "\n".join(tags) + '\n</div>'


def _build_messages_html(messages: list[dict[str, Any]], theme: dict[str, Any]) -> str:
    """Render every message dict into the ``.messages`` container body.

    Extracted from :func:`generate_standalone_html` so the parent
    function stays under the 100-line function soft limit and the
    per-message rendering pass has a single responsibility. Preserves
    the pre-refactor byte-for-byte output: same inline styles, same
    avatar codepoints, same ``_render_message_images_html`` hook.
    """
    if not messages:
        logger.warning("No messages found in the chat object to generate HTML.")
        return "<p>No messages found in this conversation.</p>"
    parts: list[str] = []
    for i, msg in enumerate(messages):
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        images = msg.get("images") or []
        logger.debug(
            "Processing message %s/%s - Role: %s, Content length: %s",
            i + 1, len(messages), role, len(content),
        )

        if not isinstance(content, str):
            logger.warning("Message %s has invalid content: %s", i + 1, content)
            content = "Content unavailable"
        elif not content and not images:
            content = "Content unavailable"

        normalized_content = normalize_markdown_for_html_export(content)
        normalized_content = transform_mermaid_fences_to_html(normalized_content)
        # Escape raw HTML first, then let the Markdown library convert markdown syntax.
        rendered_content = markdown.markdown(
            normalized_content,
            extensions=['fenced_code', 'codehilite', 'sane_lists', 'tables'],
            extension_configs={
                'codehilite': {
                    'guess_lang': False,
                    'noclasses': True,
                    'pygments_style': theme['pygments_style'],
                }
            },
            tab_length=2,
            output_format='html5',
        )
        # Python-Markdown's tables extension keeps escaped pipes (\|) literal
        # inside code spans, unlike remark-gfm which unescapes them. Fix by
        # replacing \| with | only within <td>/<th> elements after rendering.
        rendered_content = re.sub(
            r'(<t[dh]\b[^>]*>)(.*?)(</t[dh]>)',
            lambda m: m.group(1) + m.group(2).replace('\\|', '|') + m.group(3),
            rendered_content,
        )
        rendered_content += _render_message_images_html(images, role, theme)

        avatar = "\U0001f464" if role == "user" else "\U0001f916"
        name = "User" if role == "user" else "Cursor"
        bg_color = (
            theme['user_message_bg'] if role == "user" else theme['assistant_message_bg']
        )
        border_color = (
            theme['user_message_border']
            if role == "user"
            else theme['assistant_message_border']
        )

        parts.append(f"""
                <div class="message" style="margin-bottom: 20px;">
                    <div class="message-header" style="display: flex; align-items: center; margin-bottom: 8px;">
                        <div class="avatar" style="width: 32px; height: 32px; border-radius: 50%; background-color: {border_color}; color: #ffffff; display: flex; justify-content: center; align-items: center; margin-right: 10px;">
                            {avatar}
                        </div>
                        <div class="sender" style="font-weight: bold;">{name}</div>
                    </div>
                    <div class="message-content" style="padding: 15px; border-radius: 8px; background-color: {bg_color}; border-left: 4px solid {border_color}; margin-left: {0 if role == 'user' else '40px'}; margin-right: {0 if role == 'assistant' else '40px'};">
                        {rendered_content}
                    </div>
                </div>
                """)
    return "".join(parts)


def generate_standalone_html(chat, theme_mode: str = "dark"):
    """Generate a standalone HTML representation of the chat."""
    resolved_theme_mode = theme_mode if theme_mode in EXPORT_HTML_THEMES else "dark"
    theme = EXPORT_HTML_THEMES[resolved_theme_mode]
    logger.info(
        "Generating HTML for session ID: %s using %s theme",
        chat.get('session_id', 'N/A'),
        resolved_theme_mode,
    )
    try:
        # Format date for display
        date_display = "Unknown date"
        if chat.get('date'):
            try:
                date_obj = datetime.datetime.fromtimestamp(chat['date'])
                date_display = date_obj.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.warning("Error formatting date: %s", e)

        # Get project info
        project_name = chat.get('project', {}).get('name', 'Unknown Project')
        project_path = chat.get('project', {}).get('rootPath', 'Unknown Path')
        safe_project_name = html.escape(project_name)
        safe_project_path = html.escape(project_path)
        safe_date_display = html.escape(date_display)
        safe_session_id = html.escape(chat.get('session_id', 'Unknown'))
        logger.info("Project: %s, Path: %s, Date: %s", project_name, project_path, date_display)

        messages = chat.get('messages', [])
        logger.info("Found %s messages for the chat.", len(messages))
        messages_html = _build_messages_html(messages, theme)

        style_block = HTML_STYLE_TEMPLATE.format_map(theme)
        mermaid_lib = load_vendored_mermaid_js()
        mermaid_init = build_mermaid_init_script(resolved_theme_mode)
        html_document = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cursor Chat - {safe_project_name}</title>
    <style>
{style_block}
    </style>
</head>
<body>
    <div class="header">
        <h1>Cursor Chat: {safe_project_name}</h1>
    </div>
    <div class="chat-info">
        <div class="info-item"><span class="info-label">Project:</span> <span>{safe_project_name}</span></div>
        <div class="info-item"><span class="info-label">Path:</span> <span>{safe_project_path}</span></div>
        <div class="info-item"><span class="info-label">Date:</span> <span>{safe_date_display}</span></div>
        <div class="info-item"><span class="info-label">Session ID:</span> <span>{safe_session_id}</span></div>
    </div>
    <h2>Conversation History</h2>
    <div class="messages">
{messages_html}
    </div>
    <div class="footer">
        <a href="https://github.com/DavidBerdik/cursor-view" target="_blank" rel="noopener noreferrer">Exported from Cursor View</a>
    </div>
    <script>{mermaid_lib}</script>
    {mermaid_init}
</body>
</html>"""

        logger.info("Finished generating HTML. Total length: %s", len(html_document))
        return html_document
    except Exception as e:
        logger.error(
            "Error generating HTML for session %s: %s",
            chat.get('session_id', 'N/A'),
            e,
            exc_info=True,
        )
        # Return an HTML formatted error message
        return f"<html><body><h1>Error generating chat export</h1><p>Error: {e}</p></body></html>"
