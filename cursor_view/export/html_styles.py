"""CSS skin for the standalone HTML export.

:data:`HTML_STYLE_TEMPLATE` is the large CSS block that
:func:`cursor_view.export.html.generate_standalone_html` injects into
every exported document. It lives in its own module so ``html.py`` can
stay focused on the rendering logic (one module == one kind of change)
and so the export-time call site can be grepped as a single
``HTML_STYLE_TEMPLATE.format_map(theme)`` line.

Substitution model: ``str.format_map`` against an ``EXPORT_HTML_THEMES``
palette entry (``{{shell_bg}}`` etc.). CSS literal braces are escaped
as ``{{{{`` / ``}}}}`` in the template source so ``format_map`` leaves
them alone; the rendered output is byte-for-byte identical to the
original inline template, including the mermaid rules added by
:file:`.cursor/plans/mermaid-diagram-rendering_e9f9690c.plan.md`.
"""

HTML_STYLE_TEMPLATE = """\
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
            background-color: var(--pre-bg) !important;
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
        .message-content .message-images {{
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-top: 12px;
        }}
        .message-content .message-images a {{
            display: inline-flex;
            text-decoration: none;
            line-height: 0;
        }}
        .message-content .message-images a:hover {{
            text-decoration: none;
        }}
        .message-content .message-images img {{
            border: 1px solid var(--image-border);
            border-radius: 6px;
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
        .message-content .mermaid {{
            position: relative;
            text-align: center;
            margin: 1em 0;
        }}
        .message-content .mermaid-toggle {{
            position: absolute;
            top: 4px;
            right: 4px;
            background: none;
            border: none;
            cursor: pointer;
            padding: 2px 4px;
            border-radius: 4px;
            color: var(--text-secondary);
            line-height: 0;
            opacity: 0.6;
        }}
        .message-content .mermaid-toggle:hover {{
            color: var(--link);
            opacity: 1;
        }}
        .message-content .mermaid-source {{
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.9em;
            margin: 0;
            padding: 15px;
            white-space: pre;
            text-align: left;
            overflow-x: auto;
            color: var(--text-primary);
            background-color: var(--pre-bg);
            border: 1px solid var(--pre-border);
            border-radius: 5px;
        }}
        .message-content .mermaid-error {{
            text-align: left;
            border: 1px solid #e57373;
            border-radius: 4px;
            padding: 8px 12px;
            margin: 1em 0;
        }}
        .message-content .mermaid-error-msg {{
            color: #e57373;
            font-size: 0.85em;
            margin: 0 0 6px 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        }}
        .message-content .mermaid-error-src {{
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.9em;
            margin: 8px 0 0 0;
            padding: 15px;
            white-space: pre;
            overflow-x: auto;
            color: var(--text-primary);
            background-color: var(--pre-bg);
            border: 1px solid var(--pre-border);
            border-radius: 5px;
        }}"""
