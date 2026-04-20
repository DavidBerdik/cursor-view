"""Cache-layer helpers for the chat-index incremental refresh.

Public surface: :class:`DirtySet` and :func:`compute_source_diff`.
Internals live in :mod:`cursor_view.cache.source_diff`; the package
exists so :mod:`cursor_view.chat_index` doesn't grow past the
module-size soft limit when the apply-delta code lands.
"""

from cursor_view.cache.source_diff import DirtySet, compute_source_diff

__all__ = ["DirtySet", "compute_source_diff"]
