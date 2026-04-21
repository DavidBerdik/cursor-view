"""Persist the ``tool_call_parent`` / ``source_row`` / ``meta`` bookkeeping."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from cursor_view.cache.diff import SourceKey, SourceRowRecord


def _apply_tool_call_parent_updates(
    cur: sqlite3.Cursor, updates: dict[str, str | None]
) -> None:
    """Replay staged ``tool_call_parent`` upserts and deletes in bulk.

    Must run AFTER scoped Passes 5/6 so the persisted map reflects
    the new state for the *next* incremental refresh, not the current
    one. Deletes fire when a tool-call bubble vanished; upserts
    forward the first-seen ``composerId`` recorded by the row-hash
    pass.
    """
    deletes = [(tcid,) for tcid, parent in updates.items() if parent is None]
    upserts = [
        (tcid, parent) for tcid, parent in updates.items() if parent is not None
    ]
    if deletes:
        cur.executemany(
            "DELETE FROM tool_call_parent WHERE tool_call_id=?", deletes
        )
    if upserts:
        cur.executemany(
            """
            INSERT INTO tool_call_parent(tool_call_id, parent_composer_id)
            VALUES(?, ?)
            ON CONFLICT(tool_call_id) DO UPDATE SET
                parent_composer_id=excluded.parent_composer_id
            """,
            upserts,
        )


def _sync_source_row(
    cur: sqlite3.Cursor, snapshot: dict[SourceKey, SourceRowRecord]
) -> None:
    """Reconcile ``source_row`` with the freshly-scanned snapshot.

    Rows absent from the snapshot are deleted (their source DB row
    disappeared or the workspace was removed); rows present are
    upserted. Reading the cached key set inside ``BEGIN IMMEDIATE``
    guarantees consistency with the write half below.
    """
    cur.execute("SELECT db_path, table_name, key FROM source_row")
    cached_keys = {SourceKey(*row) for row in cur.fetchall()}
    to_delete = [
        (sk.db_path, sk.table_name, sk.key)
        for sk in cached_keys
        if sk not in snapshot
    ]
    if to_delete:
        cur.executemany(
            "DELETE FROM source_row WHERE db_path=? AND table_name=? AND key=?",
            to_delete,
        )
    if snapshot:
        cur.executemany(
            """
            INSERT INTO source_row(db_path, table_name, key, row_hash, composer_id)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(db_path, table_name, key) DO UPDATE SET
                row_hash=excluded.row_hash,
                composer_id=excluded.composer_id
            """,
            [
                (
                    rec.db_path,
                    rec.table_name,
                    rec.key,
                    rec.row_hash,
                    rec.composer_id,
                )
                for rec in snapshot.values()
            ],
        )


def _update_meta(
    cur: sqlite3.Cursor,
    source_fingerprint: str,
    sources: list[dict[str, Any]],
) -> None:
    """Refresh the ``meta`` rows the read path and coarse fingerprint consult."""
    cur.execute("SELECT COUNT(*) FROM chat_summary")
    row = cur.fetchone()
    chat_count = int(row[0] if row else 0)
    meta_rows = [
        ("source_fingerprint", source_fingerprint),
        ("source_manifest", json.dumps(sources, sort_keys=True)),
        ("built_at", str(int(time.time()))),
        ("chat_count", str(chat_count)),
    ]
    cur.executemany(
        """
        INSERT INTO meta(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        meta_rows,
    )
