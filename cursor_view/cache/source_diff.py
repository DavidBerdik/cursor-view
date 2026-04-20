"""Row-hash-based source diff for the chat-index incremental refresh.

:func:`compute_source_diff` walks the Cursor source databases the
extraction pipeline consumes, compares each row's content hash against
the ``source_row`` snapshot persisted in the chat-index cache, and
returns a :class:`DirtySet` that drives the apply step in
:mod:`cursor_view.chat_index`. The output is deliberately minimal: only
cids whose underlying data actually moved are surfaced, with two
exceptions documented on each branch below (``composer.composerData``
and ``aiService.*`` in a workspace DB conservatively widen to every
cid currently cached for that workspace, because their values
enumerate per-composer state we can't cheaply de-alias without a JSON
decode).
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Mirrors _MAX_PARENT_DEPTH in cursor_view/extraction/core.py so dirty-set
# propagation stops where ``_apply_subagent_inheritance`` would.
_MAX_PARENT_DEPTH = 8

# Discriminator for ``source_row.table_name``. Cursor's own table names
# are reused verbatim for cursorDiskKV / ItemTable; workspace.json uses
# a synthetic name so the sidecar file shares the same
# ``(db_path, table_name, key)`` PK space as SQLite rows.
TN_CURSOR_DISK_KV = "cursorDiskKV"
TN_ITEM_TABLE = "ItemTable"
TN_WORKSPACE_JSON = "workspace.json"

_COMPOSER_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

_PANE_VIEW_PREFIX = "workbench.panel.aichat.view."
_PANE_CONTAINER_PREFIX = "workbench.panel.composerChatViewPane."
# The legacy-chatdata key shares ``_PANE_VIEW_PREFIX`` so it must be
# checked before the pane-view classification branch runs.
_LEGACY_CHATDATA_KEY = "workbench.panel.aichat.view.aichat.chatdata"

# ItemTable keys whose change signals that the workspace's project
# resolution may have shifted. Matches the read sites in
# ``cursor_view/projects/inference.py::workspace_info``.
_WS_PROJECT_KEYS = frozenset({
    "workbench.explorer.treeViewState",
    "history.entries",
    "debug.selectedroot",
})
# ``composer.composerData`` is handled separately because, in addition
# to project inference, its value enumerates every workspace composer's
# title and timestamps.
_WS_COMPMETA_KEY = "composer.composerData"

_GLOBAL_SOURCE_ID = "(global)"


@dataclass(frozen=True)
class SourceKey:
    """Immutable primary key of the ``source_row`` table; usable as a dict key."""

    db_path: str
    table_name: str
    key: str


@dataclass
class SourceRowRecord:
    """One row destined for ``source_row`` when the apply step runs."""

    db_path: str
    table_name: str
    key: str
    row_hash: str
    composer_id: str


@dataclass
class DirtySet:
    """Everything the incremental refresh path needs to apply a diff.

    Produced by :func:`compute_source_diff` and consumed by the apply
    step in :mod:`cursor_view.chat_index`. Each collection holds the
    minimum work required; callers may fold additional cids into
    :attr:`modified_cids` when extra safety is warranted.
    """

    modified_cids: set[str] = field(default_factory=set)
    deleted_cids: set[str] = field(default_factory=set)
    # Workspace ids whose project dict may have changed without any
    # composer's messages changing. One UPDATE per workspace at apply.
    workspace_project_dirty: set[str] = field(default_factory=set)
    # Per-workspace set of cids promoted into / removed from that
    # workspace via pane-view keys. Every cid here is also in
    # ``modified_cids``; kept separately for observability.
    workspace_comp2ws_dirty: dict[str, set[str]] = field(default_factory=dict)
    # toolCallId -> parent_composer_id on upsert, toolCallId -> None
    # for rows to delete. Applied after Pass 5/6 run so the next
    # refresh sees the new map.
    tool_call_parent_updates: dict[str, str | None] = field(default_factory=dict)
    # Full new ``source_row`` snapshot. Apply step writes this wholesale
    # (INSERT OR REPLACE + DELETE rows not present here).
    source_row_snapshot: dict[SourceKey, SourceRowRecord] = field(default_factory=dict)
    # Subset of ``modified_cids`` that entered the set via subagent
    # parent-chain propagation (``task-<toolCallId>`` descendants of a
    # dirty parent). Tracked for observability so the refresh log can
    # distinguish content-driven dirtiness from link-driven dirtiness;
    # apply behavior is identical for propagated and direct cids.
    subagent_propagated_cids: set[str] = field(default_factory=set)

    def has_changes(self) -> bool:
        """True iff the apply step has any work to do."""
        return bool(
            self.modified_cids
            or self.deleted_cids
            or self.workspace_project_dirty
            or self.tool_call_parent_updates
        )


def _hash_value(value: Any) -> str:
    """Truncated SHA-256 of a SQLite value; returns ``""`` for ``NULL``.

    128-bit prefix is plenty for the per-install row counts we track
    (typical is < 1M rows); storing the full 256-bit digest would
    inflate ``source_row`` without a collision-safety benefit.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        buf = value
    elif isinstance(value, str):
        buf = value.encode("utf-8")
    else:
        buf = str(value).encode("utf-8")
    return hashlib.sha256(buf).hexdigest()[:32]


def _composer_id_from_kv_key(key: str) -> str:
    """Extract ``<cid>`` from ``bubbleId:<cid>:<bid>`` or ``composerData:<cid>``."""
    parts = key.split(":", 2)
    return parts[1] if len(parts) >= 2 else ""


def _cid_from_pane_view_key(key: str) -> str:
    """Return the UUID ``<cid>`` in ``workbench.panel.aichat.view.<cid>`` or ``""``.

    The UUID filter mirrors
    :func:`cursor_view.projects.inference._composer_ids_from_pane_view_state`
    so we don't pollute the dirty set with pane-instance ids that were
    never composer ids.
    """
    if key == _LEGACY_CHATDATA_KEY or not key.startswith(_PANE_VIEW_PREFIX):
        return ""
    seg = key[len(_PANE_VIEW_PREFIX):]
    return seg if _COMPOSER_UUID_RE.match(seg) else ""


def _cids_from_pane_container_value(raw: Any) -> list[str]:
    """Decode a ``composerChatViewPane.<paneId>`` value to its nested cid sub-keys."""
    try:
        data = json.loads(raw) if raw else None
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    for sk in data.keys():
        if not isinstance(sk, str):
            continue
        cid = _cid_from_pane_view_key(sk)
        if cid:
            out.append(cid)
    return out


def _tool_call_id_from_bubble(raw: Any) -> str | None:
    """Parse a bubble value's ``toolFormerData.toolCallId`` or return ``None``.

    Only invoked for bubble rows whose hash actually changed, so the
    JSON decode cost stays proportional to the diff size rather than
    the full bubble corpus.
    """
    try:
        data = json.loads(raw) if raw else None
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    tf = data.get("toolFormerData")
    if not isinstance(tf, dict):
        return None
    tcid = tf.get("toolCallId")
    return tcid if isinstance(tcid, str) and tcid else None


def _legacy_tab_ids(raw: Any) -> list[str]:
    """Return the ``tabId`` strings from a legacy-chatdata blob."""
    try:
        data = json.loads(raw) if raw else None
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    for tab in data.get("tabs", []) or []:
        tid = tab.get("tabId") if isinstance(tab, dict) else None
        if isinstance(tid, str) and tid:
            out.append(tid)
    return out


def _load_cached_source_rows(cur: sqlite3.Cursor) -> dict[SourceKey, tuple[str, str]]:
    """Snapshot ``source_row`` as ``SourceKey -> (row_hash, composer_id)``."""
    cur.execute("SELECT db_path, table_name, key, row_hash, composer_id FROM source_row")
    return {
        SourceKey(r[0], r[1], r[2]): (r[3], r[4])
        for r in cur.fetchall()
    }


def _load_cached_tool_call_parent(cur: sqlite3.Cursor) -> dict[str, str]:
    """Snapshot ``tool_call_parent`` as ``tool_call_id -> parent_composer_id``."""
    cur.execute("SELECT tool_call_id, parent_composer_id FROM tool_call_parent")
    return {r[0]: r[1] for r in cur.fetchall()}


def _known_cids_by_workspace(cur: sqlite3.Cursor) -> dict[str, set[str]]:
    """Group every cached composer by its ``composer_state.workspace_id``."""
    cur.execute("SELECT workspace_id, session_id FROM composer_state")
    out: dict[str, set[str]] = {}
    for ws_id, cid in cur.fetchall():
        out.setdefault(ws_id, set()).add(cid)
    return out


def _record(
    snapshot: dict[SourceKey, SourceRowRecord],
    db_path: str,
    table_name: str,
    key: str,
    row_hash: str,
    composer_id: str,
) -> None:
    """Write a new ``SourceRowRecord`` into the in-progress snapshot."""
    sk = SourceKey(db_path, table_name, key)
    snapshot[sk] = SourceRowRecord(
        db_path=db_path,
        table_name=table_name,
        key=key,
        row_hash=row_hash,
        composer_id=composer_id,
    )


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


def _fetch_workspace_item_rows(db: pathlib.Path) -> list[tuple[str, Any]]:
    """Fetch every ``ItemTable`` row the extraction pipeline consumes from one workspace DB."""
    con = None
    try:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            cur = con.cursor()
            cur.execute(
                """
                SELECT key, value FROM ItemTable WHERE
                    key IN (?, ?, ?, ?, ?)
                    OR key LIKE 'aiService.prompts%'
                    OR key LIKE 'aiService.generations%'
                    OR key LIKE ?
                    OR key LIKE ?
                """,
                (
                    "workbench.explorer.treeViewState",
                    "history.entries",
                    "debug.selectedroot",
                    _WS_COMPMETA_KEY,
                    _LEGACY_CHATDATA_KEY,
                    _PANE_VIEW_PREFIX + "%",
                    _PANE_CONTAINER_PREFIX + "%",
                ),
            )
            return list(cur.fetchall())
        except sqlite3.DatabaseError as e:
            logger.debug("Error scanning workspace ItemTable %s: %s", db, e)
            return []
    finally:
        if con is not None:
            con.close()


def _classify_workspace_row(
    workspace_id: str,
    key: str,
    value: Any,
    cid_for_key: str,
    known_cids: set[str],
    dirty: DirtySet,
    ws_promoted: set[str],
) -> None:
    """Apply the per-key classification rules for a changed workspace ItemTable row."""
    if key in _WS_PROJECT_KEYS:
        dirty.workspace_project_dirty.add(workspace_id)
        return
    if key == _WS_COMPMETA_KEY:
        # composer.composerData enumerates every workspace composer's
        # meta; a change there may shift title / timestamps for any of
        # them, and also carries project-inference value (composers' own
        # workspaceIdentifier fields).
        dirty.workspace_project_dirty.add(workspace_id)
        dirty.modified_cids.update(known_cids)
        ws_promoted.update(known_cids)
        return
    if key == _LEGACY_CHATDATA_KEY:
        for tid in _legacy_tab_ids(value):
            dirty.modified_cids.add(tid)
            ws_promoted.add(tid)
        return
    if key.startswith(_PANE_VIEW_PREFIX):
        if cid_for_key:
            dirty.modified_cids.add(cid_for_key)
            ws_promoted.add(cid_for_key)
        return
    if key.startswith(_PANE_CONTAINER_PREFIX):
        for cid in _cids_from_pane_container_value(value):
            dirty.modified_cids.add(cid)
            ws_promoted.add(cid)
        return
    if key.startswith("aiService.prompts") or key.startswith("aiService.generations"):
        # These values enumerate prompt / generation records whose ids
        # extraction uses as composer ids. Mapping a value to a cid set
        # cheaply isn't possible, so conservatively re-extract every cid
        # already cached for this workspace.
        dirty.modified_cids.update(known_cids)
        ws_promoted.update(known_cids)
        return


def _diff_workspace_db(
    workspace_id: str,
    db: pathlib.Path,
    cached: dict[SourceKey, tuple[str, str]],
    known_cids: set[str],
    dirty: DirtySet,
) -> None:
    """Hash every tracked ItemTable row in one per-workspace ``state.vscdb``."""
    db_path_str = str(db)
    ws_promoted = dirty.workspace_comp2ws_dirty.setdefault(workspace_id, set())
    rows = _fetch_workspace_item_rows(db)

    for key, value in rows:
        row_hash = _hash_value(value)
        cid_for_key = _cid_from_pane_view_key(key)
        _record(dirty.source_row_snapshot, db_path_str, TN_ITEM_TABLE, key, row_hash, cid_for_key)
        old_hash = cached.get(SourceKey(db_path_str, TN_ITEM_TABLE, key), (None, None))[0]
        if old_hash == row_hash:
            continue
        _classify_workspace_row(
            workspace_id, key, value, cid_for_key, known_cids, dirty, ws_promoted,
        )


def _diff_workspace_json(
    ws_folder: pathlib.Path,
    workspace_id: str,
    cached: dict[SourceKey, tuple[str, str]],
    dirty: DirtySet,
) -> None:
    """Hash the ``workspace.json`` sidecar file (not SQLite).

    Unchanged on most runs, and only ever affects project resolution,
    so any change simply adds the workspace to
    ``workspace_project_dirty``.
    """
    ws_json = ws_folder / "workspace.json"
    if not ws_json.exists():
        return
    try:
        blob = ws_json.read_bytes()
    except OSError as e:
        logger.debug("Error reading %s: %s", ws_json, e)
        return
    row_hash = _hash_value(blob)
    _record(dirty.source_row_snapshot, str(ws_json), TN_WORKSPACE_JSON, "", row_hash, "")
    old_hash = cached.get(SourceKey(str(ws_json), TN_WORKSPACE_JSON, ""), (None, None))[0]
    if old_hash != row_hash:
        dirty.workspace_project_dirty.add(workspace_id)


def _process_deletions(
    cached: dict[SourceKey, tuple[str, str]],
    dirty: DirtySet,
) -> None:
    """Split cached rows that vanished from the new snapshot into modified vs deleted.

    A composer whose cached source rows are all missing from the new
    snapshot lands in ``deleted_cids``; one with some rows still present
    lands in ``modified_cids`` so scoped re-extraction runs and
    ``_finalize_sessions`` decides whether to drop it.
    """
    cids_with_new_rows: set[str] = {
        rec.composer_id
        for rec in dirty.source_row_snapshot.values()
        if rec.composer_id
    }
    cids_missing: set[str] = set()
    for sk, (_hash, composer_id) in cached.items():
        if sk in dirty.source_row_snapshot:
            continue
        if composer_id:
            cids_missing.add(composer_id)
    for cid in cids_missing:
        if cid in cids_with_new_rows:
            dirty.modified_cids.add(cid)
        else:
            dirty.deleted_cids.add(cid)


def _propagate_subagent_dirtiness(dirty: DirtySet, cached_tcp: dict[str, str]) -> None:
    """Fold every ``task-<toolCallId>`` descendant of a dirty parent into ``modified_cids``.

    Walks outward from each dirty parent via a reverse index built from
    the cached ``tool_call_parent`` map, bounded by
    :data:`_MAX_PARENT_DEPTH` so the propagation budget matches
    ``_apply_subagent_inheritance``. A ``visited`` set guards against
    cycles that malformed data could introduce. Propagated children
    are additionally recorded in :attr:`DirtySet.subagent_propagated_cids`
    so the apply step can log link-driven dirtiness separately from the
    content-driven set.
    """
    if not cached_tcp:
        return
    by_parent: dict[str, list[str]] = {}
    for tcid, parent in cached_tcp.items():
        by_parent.setdefault(parent, []).append(f"task-{tcid}")
    frontier = list(dirty.modified_cids | dirty.deleted_cids)
    visited: set[str] = set(frontier)
    depth = 0
    while frontier and depth < _MAX_PARENT_DEPTH:
        next_frontier: list[str] = []
        for parent in frontier:
            for child in by_parent.get(parent, ()):
                if child in visited:
                    continue
                visited.add(child)
                dirty.modified_cids.add(child)
                dirty.subagent_propagated_cids.add(child)
                next_frontier.append(child)
        frontier = next_frontier
        depth += 1


def _trim_comp2ws_observability(dirty: DirtySet) -> None:
    """Drop cids from ``workspace_comp2ws_dirty`` that didn't ultimately land in the dirty set."""
    for ws_id in list(dirty.workspace_comp2ws_dirty.keys()):
        dirty.workspace_comp2ws_dirty[ws_id] = {
            cid
            for cid in dirty.workspace_comp2ws_dirty[ws_id]
            if cid in dirty.modified_cids
        }
        if not dirty.workspace_comp2ws_dirty[ws_id]:
            del dirty.workspace_comp2ws_dirty[ws_id]


def compute_source_diff(
    sources: list[dict[str, Any]],
    cache_con: sqlite3.Connection,
) -> DirtySet:
    """Produce a :class:`DirtySet` describing what's changed since the last cache build.

    ``sources`` is the list produced by
    :meth:`cursor_view.chat_index.ChatIndex._current_source_fingerprint`;
    each entry carries ``workspace_id`` and ``path`` plus stat metadata.
    The diff intentionally ignores the stat fields and rehashes values,
    so an mtime flip without a content change produces an empty dirty
    set and no apply work is scheduled.

    ``cache_con`` must be a connection to the current chat-index cache
    (read-only is sufficient). The ``source_row``, ``tool_call_parent``,
    and ``composer_state`` tables are expected to exist; on a freshly
    created v2 cache they are empty, and the diff reports every current
    source row as modified so the apply step performs an initial
    populate.
    """
    cur = cache_con.cursor()
    cached_rows = _load_cached_source_rows(cur)
    cached_tcp = _load_cached_tool_call_parent(cur)
    known_cids_by_ws = _known_cids_by_workspace(cur)

    dirty = DirtySet()
    for entry in sources:
        ws_id = entry.get("workspace_id") or ""
        path_str = entry.get("path")
        if not path_str:
            continue
        db = pathlib.Path(path_str)
        if not db.exists():
            continue
        if ws_id == _GLOBAL_SOURCE_ID:
            _diff_global_db(db, cached_rows, dirty)
        else:
            known_cids = known_cids_by_ws.get(ws_id, set())
            _diff_workspace_db(ws_id, db, cached_rows, known_cids, dirty)
            _diff_workspace_json(db.parent, ws_id, cached_rows, dirty)

    _process_deletions(cached_rows, dirty)

    # Drop tool_call_parent rows whose parent is being deleted. Upserts
    # from the changed-bubble branch already won; the setdefault() call
    # here only runs for parents that are pure-delete with no matching
    # upsert.
    for tcid, parent in cached_tcp.items():
        if parent in dirty.deleted_cids:
            dirty.tool_call_parent_updates.setdefault(tcid, None)

    _propagate_subagent_dirtiness(dirty, cached_tcp)
    _trim_comp2ws_observability(dirty)

    return dirty
