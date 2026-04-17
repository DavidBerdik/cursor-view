"""Chat export: Markdown generator, HTML generator, and theme resolution.

Package internals:

- :mod:`cursor_view.export.themes` — the ``EXPORT_HTML_THEMES`` palette and
  :func:`resolve_export_theme` used by the HTTP layer to pick a theme.
- :mod:`cursor_view.export.markdown` — :func:`generate_markdown` for the
  ``.md`` export format.
- :mod:`cursor_view.export.markdown_fences` — fence normalization helpers
  that rewrite Cursor's ``start:end:path`` fence header into a real
  language tag before Python-Markdown sees it.
- :mod:`cursor_view.export.html` — :func:`generate_standalone_html`, which
  renders the single-file HTML export and owns the CSS template.
"""

from cursor_view.export.html import generate_standalone_html
from cursor_view.export.markdown import generate_markdown
from cursor_view.export.themes import EXPORT_HTML_THEMES, resolve_export_theme

__all__ = [
    "EXPORT_HTML_THEMES",
    "generate_markdown",
    "generate_standalone_html",
    "resolve_export_theme",
]
