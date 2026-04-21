"""One-shot backfill of the delta-only tables during a full rebuild."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from cursor_view.cache.delta.composer_rows import _upsert_composer_state
from cursor_view.cache.delta.metadata import (
    _apply_tool_call_parent_updates,
    _sync_source_row,
)
from cursor_view.cache.diff import compute_source_diff
from cursor_view.chat_format import (
    coalesce_consecutive_messages_by_role,
    format_chat_for_frontend,
)

logger = logging.getLogger(__name__)


def backfill_incremental_tables(
    con: sqlite3.Connection,
    chats: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> None:
    """Populate the delta-only tables during a full rebuild.

    Called by :meth:`cursor_view.chat_index.ChatIndex._build_index_to_temp`
    after the content tables (``chat_summary`` / ``chat_message`` /
    ``chat_search_text`` / ``chat_search_fts``) are populated. Writes:

    - ``composer_state`` — one watermark row per extracted chat,
      reusing :func:`_upsert_composer_state` so the row shape matches
      what the incremental path maintains in the steady state.
    - ``source_row`` — full row-hash snapshot of every Cursor source
      row the extraction pipeline consumes, derived by running
      :func:`cursor_view.cache.compute_source_diff` against the
      freshly-created (and otherwise empty) incremental tables.
    - ``tool_call_parent`` — the ``toolCallId -> parent_composer_id``
      map the diff pass builds as a side-effect of hashing
      ``bubbleId:*`` rows.

    The diff's ``modified_cids`` / ``deleted_cids`` are intentionally
    discarded: every cid lands in ``modified_cids`` the first time
    because the cache starts empty, but the content tables are
    already correct for this refresh (``_insert_chat`` ran against
    the freshly-extracted chats), so acting on that dirty set would
    simply redo work.

    Writes go through the connection's auto-transaction; callers are
    expected to ``con.commit()`` after the surrounding full-rebuild
    metadata writes, matching the one-transaction guarantee of
    :func:`cursor_view.cache.delta.apply_delta` in the steady-state
    path.
    """
    cur = con.cursor()
    for chat in chats:
        formatted = format_chat_for_frontend(chat)
        messages = coalesce_consecutive_messages_by_role(
            formatted.get("messages", [])
        )
        _upsert_composer_state(cur, chat, formatted, messages)
    dirty = compute_source_diff(sources, con)
    _sync_source_row(cur, dirty.source_row_snapshot)
    _apply_tool_call_parent_updates(cur, dirty.tool_call_parent_updates)
    logger.info(
        "Full-rebuild backfill: %s composer_state rows, %s source_row rows, "
        "%s tool_call_parent rows",
        len(chats),
        len(dirty.source_row_snapshot),
        len(dirty.tool_call_parent_updates),
    )
