"""Read ``composerData:*`` rows and build the per-composer bubble order map."""

from __future__ import annotations

import json
import logging
import pathlib
import sqlite3
from contextlib import closing
from typing import Iterable

from cursor_view.sources.sqlite_util import _connect_cursor_disk_kv

logger = logging.getLogger(__name__)

# Chunk size for ``WHERE key IN (?, ?, ...)`` queries: SQLite's default
# ``SQLITE_MAX_VARIABLE_NUMBER`` is 999, so 500 leaves room for other
# binds without needing to introspect the compiled limit.
_COMPOSER_CHUNK_SIZE = 500


def iter_composer_data(db: pathlib.Path) -> Iterable[tuple[str, dict, str]]:
    """Yield (composerId, composerData, db_path) from the global ``cursorDiskKV`` table.

    Shares the ``_connect_cursor_disk_kv`` handshake with the cid-scoped
    form and with the bubble iterators, so the "open + probe" path lives
    in exactly one place.
    """
    con = _connect_cursor_disk_kv(db)
    if con is None:
        return
    with closing(con):
        cur = con.cursor()
        try:
            cur.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")
        except sqlite3.DatabaseError as e:
            logger.debug("Database error reading composerData in %s: %s", db, e)
            return
        db_path_str = str(db)
        for k, v in cur:
            if v is None:
                continue
            try:
                composer_data = json.loads(v)
            except Exception as e:
                logger.debug("Failed to parse composer data for key %s: %s", k, e)
                continue
            composer_id = k.split(":")[1] if ":" in k else ""
            if not composer_id:
                continue
            yield composer_id, composer_data, db_path_str


def iter_composer_data_for_cids(
    db: pathlib.Path,
    cids: Iterable[str],
) -> Iterable[tuple[str, dict, str]]:
    """Cid-scoped form of :func:`iter_composer_data`.

    Unlike bubbles, each composer has exactly one ``composerData:<cid>``
    row, so a batched ``WHERE key IN (...)`` query stays within
    SQLite's 999-parameter default limit for every realistic dirty set
    (and chunks above that).
    """
    cids_list = [c for c in cids if isinstance(c, str) and c]
    if not cids_list:
        return
    con = _connect_cursor_disk_kv(db)
    if con is None:
        return
    with closing(con):
        cur = con.cursor()
        db_path_str = str(db)
        for start in range(0, len(cids_list), _COMPOSER_CHUNK_SIZE):
            chunk = cids_list[start:start + _COMPOSER_CHUNK_SIZE]
            keys = [f"composerData:{c}" for c in chunk]
            placeholders = ",".join("?" for _ in keys)
            try:
                cur.execute(
                    f"SELECT key, value FROM cursorDiskKV WHERE key IN ({placeholders})",
                    keys,
                )
                rows = cur.fetchall()
            except sqlite3.DatabaseError as e:
                logger.debug("Database error reading composerData chunk in %s: %s", db, e)
                continue
            for k, v in rows:
                if v is None:
                    continue
                try:
                    composer_data = json.loads(v)
                except Exception as e:
                    logger.debug("Failed to parse composer data for key %s: %s", k, e)
                    continue
                composer_id = k.split(":")[1] if ":" in k else ""
                if not composer_id:
                    continue
                yield composer_id, composer_data, db_path_str


def build_bubble_order_map(
    db: pathlib.Path,
    cids: Iterable[str] | None = None,
) -> dict[str, dict[str, int]]:
    """Read Cursor's canonical per-composer bubble ordering.

    For each target composer, opens the ``composerData:<cid>`` row in
    ``cursorDiskKV`` and reads ``fullConversationHeadersOnly`` -- the
    array of ``{bubbleId, type, ...}`` records Cursor writes in
    chronological turn order. Returns a ``{cid -> {bubbleId -> ordinal}}``
    map the extraction pipeline uses to sort the bubble-id-keyed
    ``bubbleId:<cid>:<bid>`` rows, which SQLite otherwise returns in
    primary-key order (effectively random for UUIDv4 bubbleIds).

    ``cids=None`` performs a full scan of ``composerData:*`` rows so the
    full-rebuild path can build the order map without an extra
    round-trip. A bounded ``cids`` iterable uses the same chunked
    ``key IN (...)`` shape as :func:`iter_composer_data_for_cids` to
    keep cost proportional to the dirty set.

    Composers with no ``composerData`` row are omitted; composers whose
    value lacks ``fullConversationHeadersOnly`` yield an empty inner
    dict. Callers that encounter a missing or empty inner dict should
    fall through to "append bubbles in encountered order", which is
    the legacy behavior and the correct fallback for old Cursor builds
    that predate the headers array.
    """
    cids_list: list[str] | None
    if cids is None:
        cids_list = None
    else:
        cids_list = [c for c in cids if isinstance(c, str) and c]
        if not cids_list:
            return {}
    con = _connect_cursor_disk_kv(db)
    if con is None:
        return {}
    order: dict[str, dict[str, int]] = {}
    with closing(con):
        cur = con.cursor()
        rows: list[tuple[str, object]] = []
        if cids_list is None:
            try:
                cur.execute(
                    "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"
                )
                rows = list(cur.fetchall())
            except sqlite3.DatabaseError as e:
                logger.debug("Database error scanning composerData in %s: %s", db, e)
                return order
        else:
            for start in range(0, len(cids_list), _COMPOSER_CHUNK_SIZE):
                chunk = cids_list[start:start + _COMPOSER_CHUNK_SIZE]
                keys = [f"composerData:{c}" for c in chunk]
                placeholders = ",".join("?" for _ in keys)
                try:
                    cur.execute(
                        f"SELECT key, value FROM cursorDiskKV WHERE key IN ({placeholders})",
                        keys,
                    )
                    rows.extend(cur.fetchall())
                except sqlite3.DatabaseError as e:
                    logger.debug(
                        "Database error reading composerData chunk in %s: %s", db, e
                    )
                    continue
        for k, v in rows:
            if v is None:
                continue
            try:
                data = json.loads(v)
            except Exception as e:
                logger.debug("Failed to parse composer data for key %s: %s", k, e)
                continue
            if not isinstance(data, dict):
                continue
            cid = k.split(":", 1)[1] if ":" in k else ""
            if not cid:
                continue
            headers = data.get("fullConversationHeadersOnly")
            if not isinstance(headers, list):
                order[cid] = {}
                continue
            per_cid: dict[str, int] = {}
            for idx, entry in enumerate(headers):
                if not isinstance(entry, dict):
                    continue
                bid = entry.get("bubbleId")
                # First-seen wins: a bubbleId should appear at most once
                # in a well-formed headers array, but we guard against
                # duplicates so a later malformed entry can't shift an
                # earlier bubble's ordinal out of chronological order.
                if isinstance(bid, str) and bid and bid not in per_cid:
                    per_cid[bid] = idx
            order[cid] = per_cid
    return order
