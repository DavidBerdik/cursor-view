"""Schema version constant and DDL for the chat-index cache."""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

# Bump ``INDEX_SCHEMA_VERSION`` when either (a) the on-disk table layout built
# in ``_create_schema`` changes in a backwards-incompatible way (columns added /
# removed / retyped, indices renamed, etc.), or (b) an extraction-logic change
# must immediately invalidate existing caches on first launch rather than
# waiting for a natural source-DB mtime change to flip the fingerprint. The
# source fingerprint alone only tracks Cursor's own ``state.vscdb`` files, so
# pure code changes to ``cursor_view`` never invalidate it; this field is the
# one lever we have to force a rebuild for those cases.
#
# History:
#   1 -> initial schema (content tables only).
#   2 -> added composer_state / source_row / tool_call_parent for the
#        incremental-refresh path. Current version. Note that the
#        later bubble-ordering fix (extraction now sorts bubbles by
#        ``composerData.fullConversationHeadersOnly`` instead of the
#        alphabetical bubbleId order cursorDiskKV returned) did NOT
#        bump the version: the scrambled caches never shipped to
#        users, so there is no on-first-launch rebuild to force.
#        Developers with a stale local cache can delete
#        ``chat-index.sqlite3`` or hit the UI's Refresh button to
#        regenerate it.
INDEX_SCHEMA_VERSION = 2


def _create_schema(con: sqlite3.Connection) -> None:
    """Create every non-FTS table and index used by the cache."""
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE chat_summary (
            session_id TEXT PRIMARY KEY,
            project_name TEXT NOT NULL,
            project_root_path TEXT NOT NULL,
            date INTEGER,
            workspace_id TEXT NOT NULL,
            db_path TEXT NOT NULL,
            message_count INTEGER NOT NULL,
            preview TEXT NOT NULL,
            sort_key_ms INTEGER NOT NULL
        );

        CREATE TABLE chat_message (
            session_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            PRIMARY KEY (session_id, position)
        );

        CREATE TABLE chat_search_text (
            session_id TEXT PRIMARY KEY,
            content TEXT NOT NULL
        );

        -- Per-composer watermark used by the incremental refresh path.
        -- ``last_updated_ms`` mirrors composerData.lastUpdatedAt as a cheap
        -- monotonic signal, while ``composer_hash`` lets us detect content
        -- changes that don't bump the timestamp. ``bubble_count`` is kept
        -- to catch the rare bubble-delete case where both timestamp and
        -- top-level composer hash look unchanged.
        CREATE TABLE composer_state (
            session_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            db_path TEXT NOT NULL,
            last_updated_ms INTEGER,
            composer_hash TEXT NOT NULL,
            bubble_count INTEGER NOT NULL
        );

        -- Row-level content hashes for every Cursor source row the
        -- extraction pipeline consumes. A row's (db_path, table_name, key)
        -- tuple is stable across Cursor runs, so a change in ``row_hash``
        -- is what flips a composer into the dirty set. ``composer_id`` is
        -- denormalized so the diff can join straight to affected sessions
        -- without re-parsing keys; it may be empty for container rows
        -- (e.g. ``workbench.panel.composerChatViewPane.<paneId>``) whose
        -- cids are only known after decoding the value.
        CREATE TABLE source_row (
            db_path TEXT NOT NULL,
            table_name TEXT NOT NULL,
            key TEXT NOT NULL,
            row_hash TEXT NOT NULL,
            composer_id TEXT NOT NULL,
            PRIMARY KEY (db_path, table_name, key)
        );

        -- Persisted form of the in-memory map that Pass 2 of extraction
        -- builds: toolFormerData.toolCallId -> the composerId whose bubble
        -- fired that tool. Needed so Pass 5
        -- (_link_task_subagents_to_parents) can resolve ``task-<toolCallId>``
        -- subagent parents incrementally without re-scanning every bubble
        -- in the global DB.
        CREATE TABLE tool_call_parent (
            tool_call_id TEXT PRIMARY KEY,
            parent_composer_id TEXT NOT NULL
        );

        CREATE INDEX idx_chat_summary_sort
        ON chat_summary(sort_key_ms DESC, session_id);

        CREATE INDEX idx_chat_message_session
        ON chat_message(session_id, position);

        CREATE INDEX idx_composer_state_workspace
        ON composer_state(workspace_id);

        CREATE INDEX idx_source_row_composer
        ON source_row(composer_id);

        -- Reverse lookup for dirty-set propagation: given a dirty parent
        -- composer, find every task-<toolCallId> subagent that inherited
        -- from it so those children can be folded into the dirty set.
        CREATE INDEX idx_tool_call_parent_composer
        ON tool_call_parent(parent_composer_id);
        """
    )
    cur.close()


def _create_fts_table(cur: sqlite3.Cursor) -> bool:
    """Create the FTS5 virtual table; return True when FTS5 is available.

    Older / minimal SQLite builds lack the FTS5 extension, in which case
    the cache falls back to ``LIKE`` scans over ``chat_search_text``.
    """
    try:
        cur.execute(
            """
            CREATE VIRTUAL TABLE chat_search_fts
            USING fts5(session_id UNINDEXED, content)
            """
        )
        return True
    except sqlite3.DatabaseError as exc:
        logger.warning("FTS5 unavailable, falling back to LIKE search: %s", exc)
        return False
