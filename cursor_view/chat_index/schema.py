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
# A bump forces a **synchronous** rebuild on the first launch that observes
# the drift: ``ChatIndex.ensure_current`` routes schema-version mismatches
# through the same full-rebuild recipe used for first-build and corrupt-cache
# recovery, so API responses never mix old-schema rows with readers that
# expect the new shape. Pure fingerprint-only drift (source-DB mtimes moved
# but the row shapes are still current) remains on the stale-while-revalidate
# path; the two are deliberately distinct routes.
#
# Two independent signals gate that synchronous path. The fingerprint hash in
# ``fingerprint.py`` already folds this constant into its SHA-256, so bumping
# it is by itself sufficient to make ``_cached_index_up_to_date`` return
# False. The ``schema_version`` meta row written by ``_rebuild`` is the
# second, direct signal -- ``ensure_current`` reads it via
# ``_cached_schema_version`` specifically so the router can tell schema drift
# apart from a fingerprint-only miss and pick synchronous vs. background
# accordingly.
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
#        regenerate it. The later ``chat_image`` content table also
#        landed under v2 for the same reason -- no shipped caches to
#        invalidate, and the same delete-or-Refresh escape hatch
#        covers developers who need to pick up the new table.
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

        -- Image attachments materialized from the bubble stream. Bytes
        -- live here (never in chat_search_* / chat_search_fts, which
        -- would break FTS5 tokenization, and never in composer_hash,
        -- which would inflate the watermark column). ``uuid`` is
        -- intentionally NOT unique per session: a single image can
        -- legitimately be attached to multiple turns -- Cursor
        -- represents that as two bubbles that both reference the same
        -- uuid -- so ``get_image`` uses ``LIMIT 1`` (the bytes are
        -- identical regardless of which row it picks). Do NOT add a
        -- UNIQUE constraint on (session_id, uuid) or repeat-attachment
        -- chats will fail to insert.
        CREATE TABLE chat_image (
            session_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            image_index INTEGER NOT NULL,
            uuid TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            width INTEGER,
            height INTEGER,
            data BLOB NOT NULL,
            PRIMARY KEY (session_id, position, image_index)
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

        -- Delete-by-session scan used by _delete_cid_rows on the
        -- incremental-refresh path; the (session_id, uuid) index
        -- supports the GET /api/chat/<id>/image/<uuid> lookup without
        -- a composite-PK scan.
        CREATE INDEX idx_chat_image_session
        ON chat_image(session_id);

        CREATE INDEX idx_chat_image_uuid
        ON chat_image(session_id, uuid);

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
