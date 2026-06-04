"""Dataclasses and table-name constants shared by the diff passes."""

from __future__ import annotations

from dataclasses import dataclass, field

# Discriminator for ``source_row.table_name``. Cursor's own table names
# are reused verbatim for cursorDiskKV / ItemTable; workspace.json uses
# a synthetic name so the sidecar file shares the same
# ``(db_path, table_name, key)`` PK space as SQLite rows.
TN_CURSOR_DISK_KV = "cursorDiskKV"
TN_ITEM_TABLE = "ItemTable"
TN_WORKSPACE_JSON = "workspace.json"


@dataclass(frozen=True)
class SourceKey:
    """Immutable primary key of the ``source_row`` table; usable as a dict key."""

    db_path: str
    table_name: str
    key: str


@dataclass
class SourceRowRecord:
    """One row destined for ``source_row`` when the apply step runs."""

    db_path: str
    table_name: str
    key: str
    row_hash: str
    composer_id: str


@dataclass
class DirtySet:
    """Everything the incremental refresh path needs to apply a diff.

    Produced by :func:`cursor_view.cache.diff.compute_source_diff` and
    consumed by the apply step in :mod:`cursor_view.chat_index`. Each
    collection holds the minimum work required; callers may fold
    additional cids into :attr:`modified_cids` when extra safety is
    warranted.
    """

    modified_cids: set[str] = field(default_factory=set)
    deleted_cids: set[str] = field(default_factory=set)
    # Workspace ids whose project dict may have changed without any
    # composer's messages changing. One UPDATE per workspace at apply.
    workspace_project_dirty: set[str] = field(default_factory=set)
    # Per-workspace set of cids promoted into / removed from that
    # workspace via pane-view keys. Every cid here is also in
    # ``modified_cids``; kept separately for observability.
    workspace_comp2ws_dirty: dict[str, set[str]] = field(default_factory=dict)
    # toolCallId -> parent_composer_id on upsert, toolCallId -> None
    # for rows to delete. Applied after Pass 5/6 run so the next
    # refresh sees the new map.
    tool_call_parent_updates: dict[str, str | None] = field(default_factory=dict)
    # Full new ``source_row`` snapshot. Apply step writes this wholesale
    # (INSERT OR REPLACE + DELETE rows not present here).
    source_row_snapshot: dict[SourceKey, SourceRowRecord] = field(default_factory=dict)
    # Subset of ``modified_cids`` that entered the set via subagent
    # parent-chain propagation (``task-<toolCallId>`` descendants of a
    # propagation trigger). Populated by the apply-time gated walk in
    # :mod:`cursor_view.cache.delta.propagation`, NOT by
    # :func:`cursor_view.cache.diff.compute_source_diff` -- the diff
    # leaves this set empty so the apply step can build the trigger
    # frontier from real project shifts (post-extraction
    # ``chat_summary`` tuple differs from the cached row), parent
    # deletions, and ``tool_call_parent`` edge churn instead of every
    # parent that happened to have a row-hash flip. Tracked for
    # observability so the refresh log can distinguish content-driven
    # dirtiness from link-driven dirtiness; apply behavior is
    # identical for propagated and direct cids.
    subagent_propagated_cids: set[str] = field(default_factory=set)
    # Source DB paths whose read FAILED this pass (exists-but-unreadable:
    # a transient lock or corruption), as opposed to genuinely empty. The
    # deletion pass skips cached rows under these paths so a failed read
    # never deletes a still-present source's chats.
    unreadable_db_paths: set[str] = field(default_factory=set)

    def has_changes(self) -> bool:
        """True iff the apply step has any work to do."""
        return bool(
            self.modified_cids
            or self.deleted_cids
            or self.workspace_project_dirty
            or self.tool_call_parent_updates
        )


def _record(
    snapshot: dict[SourceKey, SourceRowRecord],
    db_path: str,
    table_name: str,
    key: str,
    row_hash: str,
    composer_id: str,
) -> None:
    """Write a new ``SourceRowRecord`` into the in-progress snapshot."""
    sk = SourceKey(db_path, table_name, key)
    snapshot[sk] = SourceRowRecord(
        db_path=db_path,
        table_name=table_name,
        key=key,
        row_hash=row_hash,
        composer_id=composer_id,
    )
