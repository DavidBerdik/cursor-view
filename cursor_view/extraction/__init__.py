"""Cursor chat extraction pipeline.

Public surface: :func:`extract_chats` and the :class:`CachedExtractionState`
helper dataclass that scoped callers use to thread prior-run state into
Passes 5 and 6. Package internals are split into
:mod:`cursor_view.extraction.core` (the orchestrator plus per-pass
helpers) and :mod:`cursor_view.extraction.diagnostics` (optional probe
gated by the ``CURSOR_CHAT_DIAGNOSTICS`` environment variable).
"""

from cursor_view.extraction.core import CachedExtractionState, extract_chats

__all__ = ["CachedExtractionState", "extract_chats"]
