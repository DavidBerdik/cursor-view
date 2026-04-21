"""Row-hash-based source diff for the chat-index incremental refresh.

:func:`compute_source_diff` walks the Cursor source databases the
extraction pipeline consumes, compares each row's content hash against
the ``source_row`` snapshot persisted in the chat-index cache, and
returns a :class:`DirtySet` that drives the apply step in
:mod:`cursor_view.chat_index`. The output is deliberately minimal: only
cids whose underlying data actually moved are surfaced, with two
exceptions documented on each branch of
:mod:`cursor_view.cache.diff.workspace_db` (``composer.composerData``
and ``aiService.*`` in a workspace DB conservatively widen to every
cid currently cached for that workspace, because their values enumerate
per-composer state we can't cheaply de-alias without a JSON decode).
"""

from cursor_view.cache.diff.engine import compute_source_diff
from cursor_view.cache.diff.types import DirtySet, SourceKey, SourceRowRecord

__all__ = [
    "DirtySet",
    "SourceKey",
    "SourceRowRecord",
    "compute_source_diff",
]
