"""Apply a :class:`DirtySet` to the live chat-index cache in one transaction.

This module is the write half of the incremental refresh described in
``.cursor/plans/incremental_chat_cache_refresh_765d5b84.plan.md``. It is
deliberately kept independent of :mod:`cursor_view.chat_index` so the
latter does not grow past the python-standards module-size soft limit;
the chat index owns the connection lifecycle and invokes
:func:`apply_delta` once per incremental refresh.

Flow, matching section 3.5 of the plan:

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
   named; an unknown re-inference is a no-op so rows keep any
   ``_inferred_project`` values from the row-hash pass.
6. Replay the staged ``tool_call_parent`` upserts/deletes AFTER
   Passes 5/6 have run so the persisted map reflects the next
   refresh's starting point.
7. Reconcile ``source_row`` against the snapshot (``INSERT OR REPLACE``
   new rows, delete ones no longer seen).
8. Refresh the ``meta`` book-keeping and ``COMMIT``; any failure inside
   the transaction triggers a ``ROLLBACK`` so the cache is left in the
   state it was in before the call.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from cursor_view.cache.diff import (
    DirtySet,
    SourceKey,
    SourceRowRecord,
    compute_source_diff,
)
from cursor_view.chat_format import (
    coalesce_consecutive_messages_by_role,
    format_chat_for_frontend,
)
from cursor_view.extraction import CachedExtractionState, extract_chats
from cursor_view.paths import cursor_root, workspaces
from cursor_view.projects.inference import workspace_info
from cursor_view.timestamps import session_sort_key_ms

logger = logging.getLogger(__name__)

# Sentinel matching the string written to ``comp2ws`` for composers
# without a workspace in ``_collect_global_bubbles`` /
# ``_collect_global_composers``. Used here to gate the
# ancestor-inferred-project cache seed: only ``(global)``-tagged rows
# carry inferred_project values in the cache (workspace-tagged rows
# use their workspace's project directly).
_GLOBAL_WS = "(global)"


def _load_cached_tool_call_parent(
    cur: sqlite3.Cursor, updates: dict[str, str | None]
) -> dict[str, str]:
    """Return the persisted ``tool_call_parent`` map with staged updates applied.

    Pass 5 of scoped extraction prefers the in-memory map built by
    scoped Pass 2 for toolCallIds both halves cover, so we only need
    the cached view to cover toolCallIds whose parent bubble was NOT
    in the dirty set. Applying the staged upserts/deletes here lets
    ``_link_task_subagents_to_parents`` resolve parents correctly even
    when a fresh bubble's cid isn't itself in ``modified_cids`` (e.g.
    a pane-key-only promotion).
    """
    cur.execute("SELECT tool_call_id, parent_composer_id FROM tool_call_parent")
    tcp: dict[str, str] = {row[0]: row[1] for row in cur.fetchall()}
    for tcid, parent in updates.items():
        if parent is None:
            tcp.pop(tcid, None)
        else:
            tcp[tcid] = parent
    return tcp


def _load_ancestor_state(
    cur: sqlite3.Cursor, dirty: DirtySet
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Snapshot ``comp2ws`` / ``_inferred_project`` for every non-dirty composer.

    Pass 6 walks up ``subagent_parent`` looking for a resolved
    ancestor. In scoped mode the ancestor may be outside the dirty set
    and thus absent from the current run's ``comp2ws`` /
    ``sessions[ancestor]``; seeding both from the cache lets the walk
    reach a resolution without Pass 6 having to re-scan workspaces.
    The ``(global)`` filter on ``ancestor_inferred_project`` matches
    the extraction-time invariant that non-``(global)`` rows in
    ``chat_summary`` carry the workspace's own project, not an
    inferred one.
    """
    skip = dirty.modified_cids | dirty.deleted_cids
    cur.execute("SELECT session_id, workspace_id FROM composer_state")
    ancestor_comp2ws: dict[str, str] = {
        row[0]: row[1] for row in cur.fetchall() if row[0] not in skip
    }
    cur.execute(
        "SELECT session_id, workspace_id, project_name, project_root_path FROM chat_summary"
    )
    ancestor_inferred: dict[str, dict[str, Any]] = {}
    for session_id, workspace_id, project_name, project_root in cur.fetchall():
        if session_id in skip:
            continue
        if workspace_id != _GLOBAL_WS:
            continue
        if not project_name or project_name == "(unknown)":
            continue
        ancestor_inferred[session_id] = {
            "name": project_name,
            "rootPath": project_root or "(unknown)",
        }
    return ancestor_comp2ws, ancestor_inferred


def _compose_cached_state(
    cur: sqlite3.Cursor, dirty: DirtySet
) -> CachedExtractionState:
    """Assemble the :class:`CachedExtractionState` for scoped extraction."""
    tcp = _load_cached_tool_call_parent(cur, dirty.tool_call_parent_updates)
    ancestor_comp2ws, ancestor_inferred = _load_ancestor_state(cur, dirty)
    return CachedExtractionState(
        tool_call_parent=tcp,
        ancestor_comp2ws=ancestor_comp2ws,
        ancestor_inferred_project=ancestor_inferred,
    )


def _delete_cid_rows(cur: sqlite3.Cursor, cid: str, fts_enabled: bool) -> None:
    """Drop every cache row tied to one composer id.

    Includes ``composer_state`` so a subsequently-deleted cid does not
    linger as a ghost ancestor for Pass 6 on the next refresh.
    """
    cur.execute("DELETE FROM chat_summary WHERE session_id=?", (cid,))
    cur.execute("DELETE FROM chat_message WHERE session_id=?", (cid,))
    cur.execute("DELETE FROM chat_search_text WHERE session_id=?", (cid,))
    if fts_enabled:
        cur.execute("DELETE FROM chat_search_fts WHERE session_id=?", (cid,))
    cur.execute("DELETE FROM composer_state WHERE session_id=?", (cid,))


def _composer_hash(
    chat_formatted: dict[str, Any], messages: list[dict[str, Any]]
) -> str:
    """Return a stable content hash for one composer's frontend-shaped payload.

    Mirrors the role of ``source_row.row_hash`` one granularity up; a
    caller that only reads ``composer_state`` can compare this column
    against a freshly derived payload to detect drift without joining
    back to ``chat_message``.
    """
    payload = {
        "project_name": chat_formatted.get("project", {}).get("name", ""),
        "project_root": chat_formatted.get("project", {}).get("rootPath", ""),
        "workspace_id": chat_formatted.get("workspace_id", ""),
        "db_path": chat_formatted.get("db_path", ""),
        "date": chat_formatted.get("date"),
        "messages": [
            {"role": m.get("role"), "content": m.get("content")} for m in messages
        ],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _upsert_composer_state(
    cur: sqlite3.Cursor,
    chat: dict[str, Any],
    chat_formatted: dict[str, Any],
    messages: list[dict[str, Any]],
) -> None:
    """Write the per-composer watermark row for one (re-)extracted chat."""
    session_obj = chat.get("session") or {}
    session_id = chat_formatted["session_id"]
    workspace_id = chat_formatted.get("workspace_id") or _GLOBAL_WS
    db_path = chat_formatted.get("db_path") or "Unknown database path"
    last_updated_ms = session_sort_key_ms(session_obj)
    composer_hash = _composer_hash(chat_formatted, messages)
    cur.execute(
        """
        INSERT INTO composer_state(
            session_id, workspace_id, db_path,
            last_updated_ms, composer_hash, bubble_count
        ) VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            workspace_id=excluded.workspace_id,
            db_path=excluded.db_path,
            last_updated_ms=excluded.last_updated_ms,
            composer_hash=excluded.composer_hash,
            bubble_count=excluded.bubble_count
        """,
        (
            session_id,
            workspace_id,
            db_path,
            last_updated_ms,
            composer_hash,
            len(messages),
        ),
    )


def _project_only_refresh(
    cur: sqlite3.Cursor,
    workspace_id: str,
    workspace_db: Path | None,
) -> int:
    """UPDATE every ``chat_summary`` row in one workspace with the fresh project.

    Returns the number of ``chat_summary`` rows the UPDATE touched
    (``0`` when the UPDATE was skipped). Skipping on unnamed projects
    matches extraction's preference order (``_finalize_sessions``
    prefers a named ``ws_project`` over an inferred one) so we never
    demote a cached inferred project just because the workspace's
    project inference happened to come back unknown this run.
    """
    if workspace_db is None or not workspace_db.exists():
        return 0
    project, _meta = workspace_info(workspace_db)
    name = project.get("name") if isinstance(project, dict) else None
    if not name or name == "(unknown)":
        return 0
    cur.execute(
        "UPDATE chat_summary SET project_name=?, project_root_path=? WHERE workspace_id=?",
        (name, project.get("rootPath") or "Unknown", workspace_id),
    )
    # ``cur.rowcount`` is the number of rows the UPDATE actually
    # modified; negative values (older SQLite builds that can't
    # report a count) are clamped to 0 so the caller's running total
    # is always a non-negative cid count.
    return max(cur.rowcount, 0)


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


def _workspace_db_lookup() -> dict[str, Path]:
    """Build a single ``workspace_id -> state.vscdb`` map for the refresh.

    :func:`cursor_view.paths.workspaces` walks the workspaceStorage
    tree; doing that once per refresh (instead of once per dirty
    workspace) keeps the project-only branch O(|workspace_project_dirty|)
    rather than O(|workspaces| * |workspace_project_dirty|).
    """
    try:
        return {ws_id: db for ws_id, db in workspaces(cursor_root()) or []}
    except Exception:
        logger.debug("Failed to enumerate workspaces for project-only refresh", exc_info=True)
        return {}


def _extract_modified_chats(
    dirty: DirtySet, cached_state: CachedExtractionState
) -> dict[str, dict[str, Any]]:
    """Run scoped extraction for ``dirty.modified_cids`` and key by composerId.

    Composers whose fresh extraction yields no messages are filtered
    out by ``_finalize_sessions`` and never appear in the returned
    dict; the caller treats that as "delete the cached rows and move
    on" so a composer that lost all its bubbles cleanly disappears
    from the cache without a dedicated deletion code path.
    """
    if not dirty.modified_cids:
        return {}
    extracted = extract_chats(
        cids=set(dirty.modified_cids), cached_state=cached_state
    )
    out: dict[str, dict[str, Any]] = {}
    for chat in extracted:
        cid = (chat.get("session") or {}).get("composerId")
        if cid:
            out[cid] = chat
    return out


def apply_delta(
    con: sqlite3.Connection,
    dirty: DirtySet,
    source_fingerprint: str,
    sources: list[dict[str, Any]],
    insert_chat: Callable[[sqlite3.Cursor, dict[str, Any], bool], None],
    database_has_fts: Callable[[sqlite3.Connection], bool],
) -> None:
    """Apply ``dirty`` to the live cache in a single ``BEGIN IMMEDIATE`` tx.

    ``insert_chat`` is injected so the apply step reuses the caller's
    existing row-insertion logic (normally
    ``ChatIndex._insert_chat``) without :mod:`cursor_view.cache`
    having to import :mod:`cursor_view.chat_index` and create a
    cycle. The caller owns the connection lifecycle, concurrency
    serialization (``_rebuild_build_lock``), and the choice between
    this path and the full-rebuild fallback.
    """
    cur = con.cursor()
    fts_enabled = database_has_fts(con)
    workspace_dbs = _workspace_db_lookup()

    prior_isolation = con.isolation_level
    # Python's sqlite3 module auto-begins a transaction for DML under
    # the default isolation level; switching to None lets us issue the
    # BEGIN IMMEDIATE / COMMIT / ROLLBACK explicitly so the cache
    # write is framed by a single predictable transaction.
    con.isolation_level = None
    try:
        cur.execute("BEGIN IMMEDIATE")
        try:
            cached_state = _compose_cached_state(cur, dirty)
            new_chats = _extract_modified_chats(dirty, cached_state)

            for cid in dirty.deleted_cids:
                _delete_cid_rows(cur, cid, fts_enabled)

            inserted = 0
            for cid in dirty.modified_cids:
                _delete_cid_rows(cur, cid, fts_enabled)
                chat = new_chats.get(cid)
                if chat is None:
                    continue
                insert_chat(cur, chat, fts_enabled)
                formatted = format_chat_for_frontend(chat)
                messages = coalesce_consecutive_messages_by_role(
                    formatted.get("messages", [])
                )
                _upsert_composer_state(cur, chat, formatted, messages)
                inserted += 1

            project_only_workspaces = 0
            project_only_composers = 0
            for ws_id in dirty.workspace_project_dirty:
                updated = _project_only_refresh(cur, ws_id, workspace_dbs.get(ws_id))
                if updated > 0:
                    project_only_workspaces += 1
                    project_only_composers += updated

            _apply_tool_call_parent_updates(cur, dirty.tool_call_parent_updates)
            _sync_source_row(cur, dirty.source_row_snapshot)
            _update_meta(cur, source_fingerprint, sources)
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
    finally:
        con.isolation_level = prior_isolation

    # Counter layout matches the observability line described in
    # todo 8 of the incremental-refresh plan: message-level dirtiness
    # (``modified`` / ``inserted``), link-driven dirtiness
    # (``subagent-propagated``), removals (``deleted``), cheap
    # workspace-scoped UPDATEs (``project-only``), and persisted-map
    # churn (``tool_call_parent updates``) are each tracked
    # separately so a spike in any single axis is diagnosable from
    # the log alone.
    logger.info(
        "Incremental chat-index refresh: "
        "%s modified (inserted %s, %s subagent-propagated), "
        "%s deleted, "
        "%s project-only composers across %s workspaces, "
        "%s tool_call_parent updates",
        len(dirty.modified_cids),
        inserted,
        len(dirty.subagent_propagated_cids),
        len(dirty.deleted_cids),
        project_only_composers,
        project_only_workspaces,
        len(dirty.tool_call_parent_updates),
    )


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
    :func:`apply_delta` in the steady-state path.
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
