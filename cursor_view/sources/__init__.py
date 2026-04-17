"""Cursor source-database access helpers.

Currently exposes :mod:`cursor_view.sources.sqlite_data` for read-only
access to the workspace and global ``state.vscdb`` files. Future Cursor
data sources (filesystem-backed caches, IPC-based sources, etc.) should
land alongside it.
"""
