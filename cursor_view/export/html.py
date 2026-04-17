"""Standalone HTML export for chat sessions.

The large CSS block that skins the export lives in
:data:`_HTML_STYLE_TEMPLATE` at the top of the module so the
:func:`generate_standalone_html` body stays readable. The template uses
``str.format_map`` substitution with theme keys (``{shell_bg}`` etc.);
literal CSS braces are doubled (``{{`` / ``}}``) exactly as they were in
the original inline f-string, so the rendered output is byte-for-byte
identical to the pre-refactor version.
"""

import datetime
import html
import logging
import re

import markdown

from cursor_view.export.markdown_fences import normalize_markdown_for_html_export
from cursor_view.export.themes import EXPORT_HTML_THEMES

logger = logging.getLogger(__name__)


# CSS for the standalone HTML export. Substituted with theme values via
# ``_HTML_STYLE_TEMPLATE.format_map(theme)``. CSS literal braces are
# escaped as ``{{`` / ``}}`` so ``format_map`` leaves them alone; theme
# keys match the ``EXPORT_HTML_THEMES`` palette entries.
_HTML_STYLE_TEMPLATE = """\
        :root {{
            color-scheme: {color_scheme};
            --shell-bg: {shell_bg};
            --surface-bg: {surface_bg};
            --border: {border};
            --shadow: {shadow};
            --text-primary: {text_primary};
            --text-secondary: {text_secondary};
            --heading: {heading};
            --header-bg: {header_bg};
            --header-text: {header_text};
            --info-bg: {info_bg};
            --info-label: {info_label};
            --link: {link};
            --inline-code-bg: {inline_code_bg};
            --pre-bg: {pre_bg};
            --pre-border: {pre_border};
            --blockquote-border: {blockquote_border};
            --blockquote-text: {blockquote_text};
            --table-surface: {table_surface};
            --table-outline: {table_outline};
            --table-header-bg: {table_header_bg};
            --table-header-text: {table_header_text};
            --table-row-bg: {table_row_bg};
            --table-row-alt-bg: {table_row_alt_bg};
            --table-row-hover-bg: {table_row_hover_bg};
            --table-grid: {table_grid};
            --table-shadow: {table_shadow};
            --image-border: {image_border};
            --footer-text: {footer_text};
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
        }}"""


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

                avatar = "\U0001f464" if role == "user" else "\U0001f916"
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

        style_block = _HTML_STYLE_TEMPLATE.format_map(theme)
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
</body>
</html>"""

        logger.info(f"Finished generating HTML. Total length: {len(html_document)}")
        return html_document
    except Exception as e:
        logger.error(f"Error generating HTML for session {chat.get('session_id', 'N/A')}: {e}", exc_info=True)
        # Return an HTML formatted error message
        return f"<html><body><h1>Error generating chat export</h1><p>Error: {e}</p></body></html>"
