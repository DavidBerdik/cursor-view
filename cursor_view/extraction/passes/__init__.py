"""Per-pass modules of the Cursor chat extraction pipeline.

Each module owns one of the eight ordered passes ``extract_chats``
dispatches in :mod:`cursor_view.extraction.core`. The split keeps each
pass small enough to read as a unit while preserving the original
orchestrator's pass-ordering invariants (notably Pass 5 before Pass 6
and Pass 4 after Pass 3).
"""

from cursor_view.extraction.passes.finalize import _finalize_sessions
from cursor_view.extraction.passes.global_bubbles import _collect_global_bubbles
from cursor_view.extraction.passes.global_composers import _collect_global_composers
from cursor_view.extraction.passes.item_table_chats import (
    _collect_global_item_table_chats,
)
from cursor_view.extraction.passes.subagent_inheritance import (
    _apply_subagent_inheritance,
)
from cursor_view.extraction.passes.task_subagents import (
    _link_task_subagents_to_parents,
)
from cursor_view.extraction.passes.uri_fallbacks import _apply_uri_fallbacks
from cursor_view.extraction.passes.workspace_messages import (
    _collect_workspace_messages,
)

__all__ = [
    "_apply_subagent_inheritance",
    "_apply_uri_fallbacks",
    "_collect_global_bubbles",
    "_collect_global_composers",
    "_collect_global_item_table_chats",
    "_collect_workspace_messages",
    "_finalize_sessions",
    "_link_task_subagents_to_parents",
]
