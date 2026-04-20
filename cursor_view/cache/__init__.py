"""Cache-layer helpers for the chat-index incremental refresh.

Public surface: :class:`DirtySet`, :func:`compute_source_diff`,
:func:`apply_delta`, and :func:`backfill_incremental_tables`. Internals
are split between :mod:`cursor_view.cache.source_diff` (read-only diff
pass) and :mod:`cursor_view.cache.apply_delta` (single-transaction
write pass, plus the one-shot full-rebuild backfill helper) so
:mod:`cursor_view.chat_index` doesn't grow past the module-size soft
limit.
"""

from cursor_view.cache.apply_delta import apply_delta, backfill_incremental_tables
from cursor_view.cache.source_diff import DirtySet, compute_source_diff

__all__ = [
    "DirtySet",
    "apply_delta",
    "backfill_incremental_tables",
    "compute_source_diff",
]
