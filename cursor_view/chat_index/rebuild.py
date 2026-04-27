"""Full-rebuild path for the chat-index cache (build to temp + atomic swap)."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cursor_view.cache import backfill_incremental_tables
from cursor_view.chat_index.rows import _insert_chat
from cursor_view.chat_index.schema import (
    INDEX_SCHEMA_VERSION,
    _create_fts_table,
    _create_schema,
)
from cursor_view.extraction import extract_chats

if TYPE_CHECKING:
    from cursor_view.chat_index.index import ChatIndex

logger = logging.getLogger(__name__)


def _rebuild(
    index: "ChatIndex",
    source_fingerprint: str,
    sources: list[dict[str, Any]],
) -> None:
    """Rebuild the cache from scratch: build-to-temp, then atomic swap into place."""
    logger.info("Rebuilding chat index at %s", index.db_path)
    index.db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = index.db_path.parent / f"{index.db_path.stem}.{uuid.uuid4().hex}.tmp"
    try:
        _build_index_to_temp(index, temp_path, source_fingerprint, sources)
        _swap_temp_into_place(index, temp_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def _build_index_to_temp(
    index: "ChatIndex",
    temp_path: Path,
    source_fingerprint: str,
    sources: list[dict[str, Any]],
) -> None:
    """Phase A: populate a new index file; does not touch ``index.db_path``.

    Also runs :func:`cursor_view.cache.backfill_incremental_tables`
    after the content tables are populated so the new ``v2``
    tables (``composer_state`` / ``source_row`` /
    ``tool_call_parent``) are filled in during this one full
    rebuild. Subsequent ``ensure_current`` calls can then take the
    incremental apply path instead of triggering a second full
    rebuild to acquire a baseline.
    """
    if temp_path.exists():
        temp_path.unlink()
    con = sqlite3.connect(temp_path, check_same_thread=False)
    try:
        index._configure_connection(con)
        _create_schema(con)
        cur = con.cursor()
        fts_enabled = _create_fts_table(cur)
        chats = extract_chats()
        # Collect the (chat, formatted, messages) triples produced by the
        # insert loop so ``backfill_incremental_tables`` can hand them
        # straight to ``_upsert_composer_state`` without re-running
        # ``format_chat_for_frontend`` + ``coalesce_consecutive_messages_by_role``
        # on every chat.
        formatted_chats: list[
            tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]
        ] = []
        for chat in chats:
            try:
                formatted, messages = _insert_chat(cur, chat, fts_enabled)
            except Exception:
                # A malformed chat must not kill the whole rebuild. Skip
                # with a logged warning so the cache stays consistent
                # (no ghost stub row, no synthetic UUID under the real
                # cid) and the remaining chats land. See
                # cursor_view/chat_format.py::format_chat_for_frontend
                # for why bad input now propagates instead of returning
                # a stub.
                cid = (chat.get("session") or {}).get("composerId")
                logger.exception("Skipping chat that failed to insert; cid=%s", cid)
                continue
            formatted_chats.append((chat, formatted, messages))
        backfill_incremental_tables(con, formatted_chats, sources)
        now = str(int(time.time()))
        meta_rows = [
            ("schema_version", str(INDEX_SCHEMA_VERSION)),
            ("source_fingerprint", source_fingerprint),
            ("source_manifest", json.dumps(sources, sort_keys=True)),
            ("built_at", now),
            ("chat_count", str(len(chats))),
        ]
        cur.executemany("INSERT INTO meta(key, value) VALUES(?, ?)", meta_rows)
        con.commit()
    except Exception:
        con.close()
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise
    else:
        con.close()


def _swap_temp_into_place(index: "ChatIndex", temp_path: Path) -> None:
    """Phase B: atomically replace the live index; waits for readers to release the file."""
    with index._swap_cv:
        index._swap_pending = True
        while index._active_readers > 0:
            index._swap_cv.wait()
        try:
            temp_path.replace(index.db_path)
        finally:
            index._swap_pending = False
            index._swap_cv.notify_all()
