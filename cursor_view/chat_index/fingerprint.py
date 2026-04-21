"""Source-DB fingerprint used as the coarse cache-validity gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from cursor_view.chat_index.schema import INDEX_SCHEMA_VERSION
from cursor_view.paths import cursor_root, global_storage_path, workspaces


def _current_source_fingerprint() -> tuple[str, list[dict[str, Any]]]:
    """Build a stable fingerprint of the source DBs, plus the list they were derived from.

    The fingerprint is a SHA-256 over ``(schema_version, [source_entries])``.
    Returning the source list alongside the fingerprint avoids scanning
    the directory twice when we go on to rebuild.
    """
    root = cursor_root()
    sources: list[dict[str, Any]] = []
    global_db = global_storage_path(root)
    if global_db and global_db.exists():
        sources.append(_source_entry("(global)", global_db))
    for ws_id, db in workspaces(root) or []:
        if db.exists():
            sources.append(_source_entry(ws_id, db))
    sources.sort(key=lambda item: item["workspace_id"])
    raw = json.dumps(
        {
            "schema_version": INDEX_SCHEMA_VERSION,
            "sources": sources,
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), sources


def _source_entry(workspace_id: str, path: Path) -> dict[str, Any]:
    """Build a single source-DB fingerprint entry (path + mtime + size + WAL metadata)."""
    stat = path.stat()
    entry: dict[str, Any] = {
        "workspace_id": workspace_id,
        "path": str(path),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }
    # SQLite WAL holds recent commits before the main file is checkpointed; include it
    # in the fingerprint so the index invalidates when only the WAL changes.
    wal_path = path.with_name(path.name + "-wal")
    if wal_path.exists():
        wst = wal_path.stat()
        entry["wal_mtime_ns"] = wst.st_mtime_ns
        entry["wal_size"] = wst.st_size
    return entry
