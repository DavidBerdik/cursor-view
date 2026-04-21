"""Diff passes for per-workspace ``state.vscdb`` files and their JSON sidecar."""

from __future__ import annotations

import logging
import pathlib
import sqlite3
from typing import Any

from cursor_view.cache.diff.hashing import (
    _LEGACY_CHATDATA_KEY,
    _PANE_CONTAINER_PREFIX,
    _PANE_VIEW_PREFIX,
    _cid_from_pane_view_key,
    _cids_from_pane_container_value,
    _hash_value,
    _legacy_tab_ids,
)
from cursor_view.cache.diff.types import (
    TN_ITEM_TABLE,
    TN_WORKSPACE_JSON,
    DirtySet,
    SourceKey,
    _record,
)

logger = logging.getLogger(__name__)

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
        # Container rows enumerate cids via their JSON body's sub-keys.
        # Newly-listed cids land in ``modified_cids`` directly. Removals
        # are invisible at this layer (we hashed the value but don't
        # keep the prior cid list), so conservatively fold every cid
        # currently tagged as resident in this workspace into the dirty
        # set. The only cost is re-extracting workspace-resident
        # composers when a pane is moved or closed -- a rare event
        # relative to bubble appends, and still bounded by
        # ``O(|workspace composers|)`` rather than the full corpus.
        new_cids = _cids_from_pane_container_value(value)
        for cid in new_cids:
            dirty.modified_cids.add(cid)
            ws_promoted.add(cid)
        for cid in known_cids:
            if cid in new_cids:
                continue
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
