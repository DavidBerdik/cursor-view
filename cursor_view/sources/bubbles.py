"""Read ``bubbleId:*`` rows from ``cursorDiskKV`` into structured tuples."""

from __future__ import annotations

import json
import logging
import pathlib
import sqlite3
from contextlib import closing
from typing import Iterable

from cursor_view.sources.sqlite_util import _connect_cursor_disk_kv

logger = logging.getLogger(__name__)


def _uri_from_bubble_context_entry(entry) -> str | None:
    """Extract a URI string from a ``bubble.context.fileSelections`` entry.

    These entries look like ``{"uri": {"_formatted": "file:///...",
    "_fsPath": "c:\\...", "path": "/c:/...", "scheme": "file", ...}, ...}``.
    Returns the first usable URI string, preferring URL-encoded forms so
    downstream URI parsing sees the exact same format as other sources.
    """
    if not isinstance(entry, dict):
        return None
    u = entry.get("uri")
    if isinstance(u, str):
        return u
    if isinstance(u, dict):
        for k in ("_formatted", "external", "path", "_fsPath", "fsPath"):
            v = u.get(k)
            if isinstance(v, str) and v:
                return v
    return None


def _extract_uris_from_bubble(b: dict) -> tuple[list[str], list[str]]:
    """Collect (file_uris, folder_uris) from a bubble dict for project inference.

    Folder URIs (``workspaceUris``, ``attachedFoldersNew``, ``attachedFolders``)
    point at directories that are candidate project roots as-is. File URIs
    (``relevantFiles``) must have their trailing filename stripped before
    common-prefix logic runs. The two are kept separate so callers can handle
    each correctly.

    Also mines the bubble's own ``context.fileSelections`` /
    ``context.folderSelections`` lists (newer Cursor versions), whose entries
    carry structured URI objects rather than the legacy flat strings.
    """
    file_uris: list[str] = []
    folder_uris: list[str] = []

    def _collect(field: str, bucket: list[str], dict_keys: tuple[str, ...]):
        v = b.get(field)
        if not isinstance(v, list):
            return
        for item in v:
            if isinstance(item, str):
                bucket.append(item)
            elif isinstance(item, dict):
                for k in dict_keys:
                    val = item.get(k)
                    if isinstance(val, str):
                        bucket.append(val)
                        break

    _collect("relevantFiles", file_uris, ("uri", "external", "path", "fsPath"))
    _collect("workspaceUris", folder_uris, ("uri", "external", "path", "fsPath"))
    _collect("attachedFoldersNew", folder_uris, ("folderPath", "uri", "external", "path", "fsPath"))
    _collect("attachedFolders", folder_uris, ("folderPath", "uri", "external", "path", "fsPath"))

    ctx = b.get("context")
    if isinstance(ctx, dict):
        for entry in ctx.get("fileSelections") or []:
            u = _uri_from_bubble_context_entry(entry)
            if u:
                file_uris.append(u)
        for entry in ctx.get("folderSelections") or []:
            u = _uri_from_bubble_context_entry(entry)
            if u:
                folder_uris.append(u)

    return file_uris, folder_uris


def _tool_call_from_bubble(b: dict) -> tuple[str, str] | None:
    """Return ``(toolCallId, tool_name)`` for bubbles that recorded a tool invocation.

    Subagent / task composers persist with id ``task-<toolCallId>`` but do
    not record their own parent (``subagentInfo`` is ``None`` on
    ``task_v2``-spawned composers, and parents' ``subagentComposerIds`` /
    ``subComposerIds`` arrays are empty on current Cursor builds). The
    only durable link back to the parent is the parent's bubble that
    fired the tool with ``toolCallId == <toolu_id>``. We surface every
    tool call (not just subagent spawners) and let the caller filter on
    the child composer's id prefix.
    """
    tf = b.get("toolFormerData")
    if not isinstance(tf, dict):
        return None
    tcid = tf.get("toolCallId")
    if not isinstance(tcid, str) or not tcid:
        return None
    name_val = tf.get("name")
    name = name_val if isinstance(name_val, str) else ""
    return tcid, name


def _parse_bubble_row(
    key: str,
    value,
    db_path_str: str,
) -> tuple[str, str, str, str, str, list[str], list[str], tuple[str, str] | None] | None:
    """Parse one ``bubbleId:*`` row into the public iterator tuple.

    Returns ``None`` for rows whose JSON body failed to parse or whose
    bubble contains no user-visible signal (no text, no URIs, no tool
    call) so the two callers can skip without repeating the filter.
    """
    if value is None:
        return None
    try:
        b = json.loads(value)
    except Exception as e:
        logger.debug("Failed to parse bubble JSON for key %s: %s", key, e)
        return None
    if isinstance(b, dict):
        file_uris, folder_uris = _extract_uris_from_bubble(b)
        tool_call = _tool_call_from_bubble(b)
    else:
        file_uris, folder_uris = [], []
        tool_call = None
    txt = (b.get("text") or b.get("richText") or "").strip()
    # Preserve bubbles that carry workspaceUris/relevantFiles or a tool
    # call even if they have no text, so project inference and
    # subagent-parent reconstruction can still see them.
    if not txt and not file_uris and not folder_uris and tool_call is None:
        return None
    role = "user" if b.get("type") == 1 else "assistant"
    # Key layout is ``bubbleId:<composerId>:<bubbleId>``; we need both
    # halves downstream (composerId for session routing, bubbleId for
    # the chronological-ordering lookup against
    # ``composerData.fullConversationHeadersOnly``).
    parts = key.split(":", 2)
    composer_id = parts[1] if len(parts) >= 2 else ""
    bubble_id = parts[2] if len(parts) >= 3 else ""
    return composer_id, bubble_id, role, txt, db_path_str, file_uris, folder_uris, tool_call


def iter_bubbles_from_disk_kv(
    db: pathlib.Path,
) -> Iterable[tuple[str, str, str, str, str, list[str], list[str], tuple[str, str] | None]]:
    """Yield (composerId, bubbleId, role, text, db_path, file_uris, folder_uris, tool_call).

    ``bubbleId`` is the ``<bid>`` segment of the row's ``bubbleId:<cid>:<bid>``
    primary key; callers pair it with
    :func:`cursor_view.sources.composer_data.build_bubble_order_map` to
    reorder the stream into Cursor's canonical per-composer turn order
    (``cursorDiskKV`` otherwise returns rows sorted alphabetically by
    bubbleId, which is effectively random for UUIDv4 bubble ids and
    scrambles messages downstream).

    ``file_uris`` and ``folder_uris`` are kept separate so project inference
    can trim filenames from files while treating folders as candidate roots.
    ``tool_call`` is ``(toolCallId, tool_name)`` when the bubble recorded a
    tool invocation (``toolFormerData``) and ``None`` otherwise; callers
    use this to reconstruct subagent parent links that Cursor no longer
    stores on the subagent composer itself.
    """
    con = _connect_cursor_disk_kv(db)
    if con is None:
        return
    with closing(con):
        cur = con.cursor()
        try:
            cur.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'")
        except sqlite3.DatabaseError as e:
            logger.debug("Database error reading bubbles in %s: %s", db, e)
            return
        db_path_str = str(db)
        for k, v in cur:
            parsed = _parse_bubble_row(k, v, db_path_str)
            if parsed is not None:
                yield parsed


def iter_bubbles_for_cids(
    db: pathlib.Path,
    cids: Iterable[str],
) -> Iterable[tuple[str, str, str, str, str, list[str], list[str], tuple[str, str] | None]]:
    """Cid-scoped form of :func:`iter_bubbles_from_disk_kv`.

    Emits the same 8-tuple ``(composerId, bubbleId, role, text, db_path,
    file_uris, folder_uris, tool_call)`` but only for bubbles whose
    ``composerId`` is in ``cids``. The per-cid query is a range scan of
    the ``bubbleId:<cid>:`` PK prefix -- ``key > 'bubbleId:<cid>:'`` with
    a ``key < 'bubbleId:<cid>;'`` upper bound (``;`` is the byte directly
    after ``:``) -- which runs on the implicit primary-key index in
    O(bubbles_per_cid) time without a LIKE escape for composer ids that
    contain underscores (``task-<toolCallId>`` commonly do).

    Cids with no matching rows are skipped silently so callers can pass
    a noisy dirty set without pre-filtering.
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
        for cid in cids_list:
            lower = f"bubbleId:{cid}:"
            upper = f"bubbleId:{cid};"
            try:
                cur.execute(
                    "SELECT key, value FROM cursorDiskKV WHERE key > ? AND key < ?",
                    (lower, upper),
                )
                rows = cur.fetchall()
            except sqlite3.DatabaseError as e:
                logger.debug("Database error reading bubbles for %s in %s: %s", cid, db, e)
                continue
            for k, v in rows:
                parsed = _parse_bubble_row(k, v, db_path_str)
                if parsed is not None:
                    yield parsed
