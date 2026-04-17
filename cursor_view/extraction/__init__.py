"""Cursor chat extraction pipeline.

Public surface: :func:`extract_chats`. The package internals are split
into :mod:`cursor_view.extraction.core` (the orchestrator plus per-pass
helpers) and :mod:`cursor_view.extraction.diagnostics` (optional probe
gated by the ``CURSOR_CHAT_DIAGNOSTICS`` environment variable).
"""

from cursor_view.extraction.core import extract_chats

__all__ = ["extract_chats"]
