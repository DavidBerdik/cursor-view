"""Cursor View server package: chat extraction, API, and export."""

# Single source of truth for the application version. Consumed by
# cursor-view.spec for the macOS .app bundle's CFBundleShortVersionString /
# CFBundleVersion. Keep this a plain literal with no imports so reading it
# (e.g. `from cursor_view import __version__` at spec-eval time) stays free
# of import-time side effects per python-standards.mdc.
__version__ = "0.1.0"
