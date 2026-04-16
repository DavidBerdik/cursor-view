"""HTML / Markdown / JSON export for chat sessions."""

import datetime
import html
import logging
import re

import markdown
from pygments.lexers import find_lexer_class_for_filename

logger = logging.getLogger(__name__)

EXPORT_HTML_THEMES = {
    "light": {
        "color_scheme": "light",
        "pygments_style": "default",
        "shell_bg": "#f5f5f5",
        "surface_bg": "#ffffff",
        "border": "#eeeeee",
        "shadow": "rgba(0, 0, 0, 0.1)",
        "text_primary": "#333333",
        "text_secondary": "#555555",
        "heading": "#2c3e50",
        "header_bg": "#f0f7ff",
        "header_text": "#2c3e50",
        "info_bg": "#f9f9f9",
        "info_label": "#555555",
        "link": "#1565c0",
        "inline_code_bg": "rgba(63, 81, 181, 0.08)",
        "pre_bg": "#eef2ff",
        "pre_border": "#dddddd",
        "blockquote_border": "#cfd8dc",
        "blockquote_text": "#546e7a",
        "table_surface": "#ffffff",
        "table_outline": "#d8e2ef",
        "table_header_bg": "#f0f4f8",
        "table_header_text": "#1f3a56",
        "table_row_bg": "#ffffff",
        "table_row_alt_bg": "#f7fbff",
        "table_row_hover_bg": "#eef6ff",
        "table_grid": "#dbe7f3",
        "table_shadow": "rgba(29, 58, 86, 0.08)",
        "image_border": "#dfe7ef",
        "user_message_bg": "#f0f7ff",
        "user_message_border": "#3f51b5",
        "assistant_message_bg": "#f0fff7",
        "assistant_message_border": "#00796b",
        "footer_text": "#999999",
    },
    "dark": {
        "color_scheme": "dark",
        "pygments_style": "native",
        "shell_bg": "#121212",
        "surface_bg": "#1E1E1E",
        "border": "#2a2a2a",
        "shadow": "rgba(0, 0, 0, 0.45)",
        "text_primary": "#FFFFFF",
        "text_secondary": "#B3B3B3",
        "heading": "#FFFFFF",
        "header_bg": "#103748",
        "header_text": "#FFFFFF",
        "info_bg": "#181818",
        "info_label": "#B3B3B3",
        "link": "#66d6ff",
        "inline_code_bg": "rgba(12, 188, 255, 0.18)",
        "pre_bg": "#11181f",
        "pre_border": "#2c4550",
        "blockquote_border": "#35505b",
        "blockquote_text": "#B3B3B3",
        "table_surface": "#151c22",
        "table_outline": "#29414d",
        "table_header_bg": "#1b2b36",
        "table_header_text": "#eaf6ff",
        "table_row_bg": "#182128",
        "table_row_alt_bg": "#141b21",
        "table_row_hover_bg": "#20303a",
        "table_grid": "#263844",
        "table_shadow": "rgba(0, 0, 0, 0.28)",
        "image_border": "#2d3b42",
        "user_message_bg": "#102734",
        "user_message_border": "#00bbff",
        "assistant_message_bg": "#12281d",
        "assistant_message_border": "#3EBD64",
        "footer_text": "#8f8f8f",
    },
}


def resolve_export_theme(theme_param: str | None, theme_cookie: str | None) -> str:
    """Resolve the requested export theme, preferring query param over cookie."""
    normalized_param = (theme_param or "").strip().lower()
    if normalized_param in EXPORT_HTML_THEMES:
        return normalized_param

    normalized_cookie = (theme_cookie or "").strip().lower()
    if normalized_cookie in EXPORT_HTML_THEMES:
        return normalized_cookie

    return "dark"


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

def infer_language_from_filename(filename: str) -> str | None:
    """Infer a fenced-code language tag from a filename."""
    if not filename:
        return None

    lexer_class = find_lexer_class_for_filename(filename)
    if lexer_class is None:
        return None

    if lexer_class.aliases:
        return lexer_class.aliases[0]
    return None

def normalize_markdown_for_html_export(content: str) -> str:
    """Normalize malformed markdown patterns seen in chat exports."""
    normalized_lines = []
    cursor_metadata_pattern = re.compile(r"^(\d+):(\d+):(.+)$")

    for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]

        if stripped.startswith("```"):
            fence_tail = stripped[3:]

            if fence_tail:
                cursor_metadata = cursor_metadata_pattern.match(fence_tail)
                if cursor_metadata:
                    filename = cursor_metadata.group(3)
                    language = infer_language_from_filename(filename)
                    normalized_lines.append(f"{indent}```{language or ''}")
                    continue

                language_and_content = re.match(r"^([A-Za-z0-9_+-]+)\s+(.+)$", fence_tail)
                if language_and_content:
                    language, inline_code = language_and_content.groups()
                    normalized_lines.append(f"{indent}```{language}")
                    normalized_lines.append(f"{indent}{inline_code}")
                    continue

        normalized_lines.append(line)

    return "\n".join(normalized_lines)

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
                logger.warning(f"Error formatting date: {e}")

        # Get project info
        project_name = chat.get('project', {}).get('name', 'Unknown Project')
        project_path = chat.get('project', {}).get('rootPath', 'Unknown Path')
        safe_project_name = html.escape(project_name)
        safe_project_path = html.escape(project_path)
        safe_date_display = html.escape(date_display)
        safe_session_id = html.escape(chat.get('session_id', 'Unknown'))
        logger.info(f"Project: {project_name}, Path: {project_path}, Date: {date_display}")

        # Build the HTML content
        messages_html = ""
        messages = chat.get('messages', [])
        logger.info(f"Found {len(messages)} messages for the chat.")

        if not messages:
            logger.warning("No messages found in the chat object to generate HTML.")
            messages_html = "<p>No messages found in this conversation.</p>"
        else:
            for i, msg in enumerate(messages):
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                logger.debug(f"Processing message {i+1}/{len(messages)} - Role: {role}, Content length: {len(content)}")

                if not content or not isinstance(content, str):
                    logger.warning(f"Message {i+1} has invalid content: {content}")
                    content = "Content unavailable"

                normalized_content = normalize_markdown_for_html_export(content)

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

                avatar = "👤" if role == "user" else "🤖"
                name = "User" if role == "user" else "Cursor"
                bg_color = (
                    theme['user_message_bg']
                    if role == "user"
                    else theme['assistant_message_bg']
                )
                border_color = (
                    theme['user_message_border']
                    if role == "user"
                    else theme['assistant_message_border']
                )

                messages_html += f"""
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
                """

        # Create the complete HTML document
        html_document = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cursor Chat - {safe_project_name}</title>
    <style>
        :root {{
            color-scheme: {theme['color_scheme']};
            --shell-bg: {theme['shell_bg']};
            --surface-bg: {theme['surface_bg']};
            --border: {theme['border']};
            --shadow: {theme['shadow']};
            --text-primary: {theme['text_primary']};
            --text-secondary: {theme['text_secondary']};
            --heading: {theme['heading']};
            --header-bg: {theme['header_bg']};
            --header-text: {theme['header_text']};
            --info-bg: {theme['info_bg']};
            --info-label: {theme['info_label']};
            --link: {theme['link']};
            --inline-code-bg: {theme['inline_code_bg']};
            --pre-bg: {theme['pre_bg']};
            --pre-border: {theme['pre_border']};
            --blockquote-border: {theme['blockquote_border']};
            --blockquote-text: {theme['blockquote_text']};
            --table-surface: {theme['table_surface']};
            --table-outline: {theme['table_outline']};
            --table-header-bg: {theme['table_header_bg']};
            --table-header-text: {theme['table_header_text']};
            --table-row-bg: {theme['table_row_bg']};
            --table-row-alt-bg: {theme['table_row_alt_bg']};
            --table-row-hover-bg: {theme['table_row_hover_bg']};
            --table-grid: {theme['table_grid']};
            --table-shadow: {theme['table_shadow']};
            --image-border: {theme['image_border']};
            --footer-text: {theme['footer_text']};
        }}
        html {{
            background-color: var(--shell-bg);
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: var(--text-primary);
            background-color: var(--surface-bg);
            max-width: 900px;
            margin: 20px auto;
            padding: 20px;
            border: 1px solid var(--border);
            box-shadow: 0 2px 5px var(--shadow);
        }}
        h1, h2, h3 {{
            color: var(--heading);
        }}
        .header {{
            background-color: var(--header-bg);
            color: var(--header-text);
            padding: 15px 20px;
            margin: -20px -20px 20px -20px;
        }}
        .header h1 {{
            margin: 0;
            color: inherit;
        }}
        .chat-info {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px 20px;
            margin-bottom: 20px;
            background-color: var(--info-bg);
            padding: 12px 15px;
            border-radius: 8px;
            font-size: 0.9em;
            border: 1px solid var(--border);
        }}
        .info-item {{
            display: flex;
            align-items: center;
        }}
        .info-label {{
            font-weight: bold;
            margin-right: 5px;
            color: var(--info-label);
        }}
        pre {{
            background-color: var(--pre-bg);
            color: var(--text-primary);
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            border: 1px solid var(--pre-border);
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.9em;
            white-space: pre;
        }}
        code {{
            background-color: var(--inline-code-bg);
            padding: 0.1em 0.35em;
            border-radius: 4px;
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.95em;
        }}
        .message-content .codehilite {{
            margin: 1em 0;
            border: 1px solid var(--pre-border);
            border-radius: 5px;
            overflow-x: auto;
        }}
        .message-content .codehilite pre {{
            margin: 0;
            padding: 15px;
            border: none;
            border-radius: 0;
            background: transparent !important;
        }}
        .message-content pre code,
        .message-content .codehilite code {{
            background-color: transparent;
            padding: 0;
        }}
        .message-content {{
            word-wrap: break-word;
            overflow-wrap: break-word;
        }}
        .message-content p:first-child {{
            margin-top: 0;
        }}
        .message-content p:last-child {{
            margin-bottom: 0;
        }}
        .message-content ul,
        .message-content ol {{
            padding-left: 1.5rem;
            margin: 0.75rem 0;
        }}
        .message-content li + li {{
            margin-top: 0.25rem;
        }}
        .message-content a {{
            color: var(--link);
            text-decoration: none;
        }}
        .message-content a:hover {{
            text-decoration: underline;
        }}
        .message-content img {{
            max-width: 100%;
            height: auto;
            border-radius: 6px;
            border: 1px solid var(--image-border);
        }}
        .message-content blockquote {{
            margin: 0.75rem 0;
            padding: 0.25rem 0 0.25rem 1rem;
            border-left: 4px solid var(--blockquote-border);
            color: var(--blockquote-text);
        }}
        .message-content table {{
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            margin: 1.1em 0;
            font-size: 0.92em;
            background-color: var(--table-surface);
            border: 1px solid var(--table-outline);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 10px 24px var(--table-shadow);
        }}
        .message-content thead th {{
            background-color: var(--table-header-bg);
            color: var(--table-header-text);
            font-weight: 700;
            letter-spacing: 0.01em;
        }}
        .message-content th,
        .message-content td {{
            padding: 10px 14px;
            text-align: left;
            border-right: 1px solid var(--table-grid);
            border-bottom: 1px solid var(--table-grid);
        }}
        .message-content th:last-child,
        .message-content td:last-child {{
            border-right: none;
        }}
        .message-content tbody tr {{
            background-color: var(--table-row-bg);
        }}
        .message-content tbody tr:nth-child(even) {{
            background-color: var(--table-row-alt-bg);
        }}
        .message-content tbody tr:hover {{
            background-color: var(--table-row-hover-bg);
        }}
        .message-content tbody tr:last-child td {{
            border-bottom: none;
        }}
        .message-content thead th:first-child {{
            border-top-left-radius: 12px;
        }}
        .message-content thead th:last-child {{
            border-top-right-radius: 12px;
        }}
        .message-content tbody tr:last-child td:first-child {{
            border-bottom-left-radius: 12px;
        }}
        .message-content tbody tr:last-child td:last-child {{
            border-bottom-right-radius: 12px;
        }}
        .message-content td {{
            color: var(--text-primary);
            font-variant-numeric: tabular-nums;
        }}
        .footer {{
            margin-top: 30px;
            font-size: 12px;
            color: var(--footer-text);
            text-align: center;
            border-top: 1px solid var(--border);
            padding-top: 15px;
        }}
        .footer a {{
            color: var(--link);
        }}
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
</body>
</html>"""

        logger.info(f"Finished generating HTML. Total length: {len(html_document)}")
        return html_document
    except Exception as e:
        logger.error(f"Error generating HTML for session {chat.get('session_id', 'N/A')}: {e}", exc_info=True)
        # Return an HTML formatted error message
        return f"<html><body><h1>Error generating chat export</h1><p>Error: {e}</p></body></html>"

