"""Apply the output of :mod:`cursor_view.cache.diff` to the live cache.

The write half of the incremental refresh described in
``.cursor/plans/incremental_chat_cache_refresh_765d5b84.plan.md``. Flow,
matching section 3.5 of that plan:

1. ``BEGIN IMMEDIATE`` on the writable cache connection (WAL is already
   enabled via the caller's configure step).
2. Read the post-change ``tool_call_parent`` view and ancestor state
   from the cache so Passes 5/6 of scoped extraction have everything
   they need without re-scanning bubbles for non-dirty composers.
3. Run :func:`cursor_view.extraction.extract_chats` with the dirty cid
   set.
4. For every deleted cid, drop its rows from the five content tables
   plus ``composer_state``. For every modified cid, drop then re-insert
   via the caller's ``insert_chat`` hook and upsert the corresponding
   ``composer_state`` watermark.
5. Apply workspace-scoped project-only ``UPDATE`` for any workspace in
   ``workspace_project_dirty`` whose freshly-inferred project is
   named.
6. Replay the staged ``tool_call_parent`` upserts/deletes AFTER
   Passes 5/6 have run so the persisted map reflects the next
   refresh's starting point.
7. Reconcile ``source_row`` against the snapshot (``INSERT OR REPLACE``
   new rows, delete ones no longer seen).
8. Refresh the ``meta`` book-keeping and ``COMMIT``; any failure inside
   the transaction triggers a ``ROLLBACK`` so the cache is left in the
   state it was in before the call.

Public surface:

- :func:`apply_delta` — steady-state incremental refresh entry point.
- :func:`backfill_incremental_tables` — one-shot populate of the
  delta-only tables during a full rebuild.
"""

from cursor_view.cache.delta.backfill import backfill_incremental_tables
from cursor_view.cache.delta.engine import apply_delta

__all__ = ["apply_delta", "backfill_incremental_tables"]
