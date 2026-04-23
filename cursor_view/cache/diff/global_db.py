"""Diff passes for the global ``state.vscdb`` (cursorDiskKV + legacy chatdata)."""

from __future__ import annotations

import logging
import pathlib
import sqlite3

from cursor_view.cache.diff.hashing import (
    _LEGACY_CHATDATA_KEY,
    _bubble_id_from_kv_key,
    _composer_id_from_kv_key,
    _hash_value,
    _header_bubble_ids_from_composer,
    _legacy_tab_ids,
    _tool_call_id_from_bubble,
)
from cursor_view.cache.diff.types import (
    TN_CURSOR_DISK_KV,
    TN_ITEM_TABLE,
    DirtySet,
    SourceKey,
    _record,
)

logger = logging.getLogger(__name__)


def _diff_global_cursor_disk_kv(
    cur: sqlite3.Cursor,
    db_path_str: str,
    cached: dict[SourceKey, tuple[str, str]],
    dirty: DirtySet,
) -> None:
    """Hash ``bubbleId:*`` / ``composerData:*`` rows in the global ``cursorDiskKV``.

    Writes the full snapshot, adds changed-composer ids to
    ``modified_cids``, and stages ``tool_call_parent`` upserts from
    changed bubble rows (first-seen wins, matching Pass 2 semantics).

    Orphan bubbles -- ``bubbleId:<cid>:<bid>`` rows whose ``<bid>`` is
    absent from the composer's ``fullConversationHeadersOnly`` array --
    do not stage ``tool_call_parent`` upserts. Cursor prunes those
    bubbles out of its canonical transcript (summarization checkpoints,
    conversation restarts) but leaves the row on disk; persisting a
    dead ``toolu_*`` pointer from one would resurrect a stale subagent
    parent link on the next refresh's ``task-<toolCallId>`` lookup.
    The row hash is still recorded so hash churn on an orphan continues
    to flip the cid into ``modified_cids`` and a re-extract properly
    drops it via the matching filter in ``_collect_global_bubbles``.
    """
    try:
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'"
        )
        if not cur.fetchone():
            return
        cur.execute(
            "SELECT key, value FROM cursorDiskKV "
            "WHERE key LIKE 'bubbleId:%' OR key LIKE 'composerData:%'"
        )
        rows = cur.fetchall()
    except sqlite3.DatabaseError as e:
        logger.debug("Error scanning cursorDiskKV in %s: %s", db_path_str, e)
        return

    # Build the per-cid allowlist of canonical bubbleIds before the
    # bubble rows are processed. ``None`` means "legacy composer, no
    # headers array" -- the orphan filter is disabled for that cid and
    # every bubble flows through unchanged, matching the encounter-order
    # fallback in ``_collect_global_bubbles``.
    header_allowlist_by_cid: dict[str, frozenset[str] | None] = {}
    for key, value in rows:
        if key.startswith("composerData:"):
            cid = _composer_id_from_kv_key(key)
            if cid:
                header_allowlist_by_cid[cid] = _header_bubble_ids_from_composer(value)

    for key, value in rows:
        row_hash = _hash_value(value)
        cid = _composer_id_from_kv_key(key)
        _record(dirty.source_row_snapshot, db_path_str, TN_CURSOR_DISK_KV, key, row_hash, cid)
        old_hash = cached.get(SourceKey(db_path_str, TN_CURSOR_DISK_KV, key), (None, None))[0]
        if old_hash == row_hash:
            continue
        if cid:
            dirty.modified_cids.add(cid)
        if key.startswith("bubbleId:"):
            allowlist = header_allowlist_by_cid.get(cid)
            if allowlist is not None:
                bid = _bubble_id_from_kv_key(key)
                if bid and bid not in allowlist:
                    continue
            tcid = _tool_call_id_from_bubble(value)
            if tcid:
                dirty.tool_call_parent_updates.setdefault(tcid, cid)


def _diff_global_legacy_chatdata(
    cur: sqlite3.Cursor,
    db_path_str: str,
    cached: dict[SourceKey, tuple[str, str]],
    dirty: DirtySet,
) -> None:
    """Hash the single legacy-chatdata ``ItemTable`` key Pass 7 consumes."""
    try:
        cur.execute("SELECT value FROM ItemTable WHERE key=?", (_LEGACY_CHATDATA_KEY,))
        row = cur.fetchone()
    except sqlite3.DatabaseError as e:
        logger.debug("Error reading global legacy chatdata: %s", e)
        return
    if row is None:
        return
    value = row[0]
    row_hash = _hash_value(value)
    _record(dirty.source_row_snapshot, db_path_str, TN_ITEM_TABLE, _LEGACY_CHATDATA_KEY, row_hash, "")
    old_hash = cached.get(SourceKey(db_path_str, TN_ITEM_TABLE, _LEGACY_CHATDATA_KEY), (None, None))[0]
    if old_hash == row_hash:
        return
    for tid in _legacy_tab_ids(value):
        dirty.modified_cids.add(tid)


def _diff_global_db(
    db: pathlib.Path,
    cached: dict[SourceKey, tuple[str, str]],
    dirty: DirtySet,
) -> None:
    """Run both global-DB sub-diffs against one opened read-only connection."""
    db_path_str = str(db)
    con = None
    try:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            cur = con.cursor()
        except sqlite3.DatabaseError as e:
            logger.debug("Error opening global DB %s: %s", db, e)
            return
        _diff_global_cursor_disk_kv(cur, db_path_str, cached, dirty)
        _diff_global_legacy_chatdata(cur, db_path_str, cached, dirty)
    finally:
        if con is not None:
            con.close()
