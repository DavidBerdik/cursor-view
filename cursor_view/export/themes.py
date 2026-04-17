"""HTML export theme palettes and resolution."""

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
