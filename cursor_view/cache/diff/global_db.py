"""Diff passes for the global ``state.vscdb`` (cursorDiskKV + legacy chatdata)."""

from __future__ import annotations

import logging
import pathlib
import sqlite3

from cursor_view.cache.diff.hashing import (
    _LEGACY_CHATDATA_KEY,
    _composer_id_from_kv_key,
    _hash_value,
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
    still stage ``tool_call_parent`` upserts: an upstream-model-unique
    ``toolCallId`` is a structural edge, not display content, and the
    spawned ``task-<toolCallId>`` subagent composer outlives any
    Cursor-side pruning of the parent bubble (summarization
    checkpoints, conversation restarts). Suppressing the edge here
    orphans the subagent on Pass 5 and surfaces it as ``(unknown)`` /
    ``(global)`` even though its real parent is alive (Cause 1 in
    the project-resolution diagnostic). Display-side suppression of
    orphan rows happens in ``_collect_global_bubbles`` (no message,
    no URIs, no ``comp_meta`` seed, no ``db_path`` write); the row
    hash is still recorded here so hash churn on an orphan flips the
    cid into ``modified_cids`` and a re-extract picks up the latest
    state.
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
        dirty.unreadable_db_paths.add(db_path_str)
        return

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
        dirty.unreadable_db_paths.add(db_path_str)
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
            dirty.unreadable_db_paths.add(db_path_str)
            return
        _diff_global_cursor_disk_kv(cur, db_path_str, cached, dirty)
        _diff_global_legacy_chatdata(cur, db_path_str, cached, dirty)
    finally:
        if con is not None:
            con.close()
