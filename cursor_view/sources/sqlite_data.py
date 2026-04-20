"""SQLite helpers and iterators over Cursor workspace / global databases."""

import json
import logging
import pathlib
import sqlite3
from typing import Iterable

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
        """Append URI strings from ``field`` list items into ``bucket``."""
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


def j(cur: sqlite3.Cursor, table: str, key: str):
    """Load a JSON value from ``table`` by string ``key``; return raw string if JSON decode fails."""
    cur.execute(f"SELECT value FROM {table} WHERE key=?", (key,))
    row = cur.fetchone()
    if not row:
        return None
    raw = row[0]
    try:
        return json.loads(raw)
    except Exception as e:
        logger.debug("Failed to parse JSON for %s: %s", key, e)
        # Some Cursor/VSCode keys (e.g. debug.selectedroot) store a raw string
        # without JSON quoting. Preserve it so downstream fallbacks can use it.
        if isinstance(raw, str) and raw:
            return raw
        return None


def iter_bubbles_from_disk_kv(
    db: pathlib.Path,
) -> Iterable[tuple[str, str, str, str, str, list[str], list[str], tuple[str, str] | None]]:
    """Yield (composerId, bubbleId, role, text, db_path, file_uris, folder_uris, tool_call).

    ``bubbleId`` is the ``<bid>`` segment of the row's ``bubbleId:<cid>:<bid>``
    primary key; callers pair it with :func:`build_bubble_order_map` to
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
    # Initialize con to None so the outer finally can close it regardless
    # of whether sqlite3.connect or a subsequent cur.execute is what fails.
    con = None
    try:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'")
            if not cur.fetchone():
                return
            cur.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'")
        except sqlite3.DatabaseError as e:
            logger.debug("Database error with %s: %s", db, e)
            return

        db_path_str = str(db)

        for k, v in cur:
            try:
                if v is None:
                    continue
                b = json.loads(v)
            except Exception as e:
                logger.debug("Failed to parse bubble JSON for key %s: %s", k, e)
                continue

            if isinstance(b, dict):
                file_uris, folder_uris = _extract_uris_from_bubble(b)
                tool_call = _tool_call_from_bubble(b)
            else:
                file_uris, folder_uris = [], []
                tool_call = None
            txt = (b.get("text") or b.get("richText") or "").strip()
            # Preserve bubbles that carry workspaceUris/relevantFiles or a
            # tool call even if they have no text, so project inference and
            # subagent-parent reconstruction can still see them.
            if not txt and not file_uris and not folder_uris and tool_call is None:
                continue
            role = "user" if b.get("type") == 1 else "assistant"
            # Key layout is ``bubbleId:<composerId>:<bubbleId>``; we need both
            # halves downstream (composerId for session routing, bubbleId for
            # the chronological-ordering lookup against
            # ``composerData.fullConversationHeadersOnly``).
            parts = k.split(":", 2)
            composerId = parts[1] if len(parts) >= 2 else ""
            bubbleId = parts[2] if len(parts) >= 3 else ""
            yield composerId, bubbleId, role, txt, db_path_str, file_uris, folder_uris, tool_call
    finally:
        if con is not None:
            con.close()


def iter_chat_from_item_table(db: pathlib.Path) -> Iterable[tuple[str, str, str, str]]:
    """Yield (composerId, role, text, db_path) from ItemTable."""
    # Initialize con to None up-front so the finally block can close it
    # regardless of where in the try the failure happens. Avoids the
    # fragile ``if "con" in locals()`` check this function used to have.
    con = None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = con.cursor()

        # Try to get chat data from workbench.panel.aichat.view.aichat.chatdata
        chat_data = j(cur, "ItemTable", "workbench.panel.aichat.view.aichat.chatdata")
        if chat_data and "tabs" in chat_data:
            for tab in chat_data.get("tabs", []):
                tab_id = tab.get("tabId", "unknown")
                for bubble in tab.get("bubbles", []):
                    bubble_type = bubble.get("type")
                    if not bubble_type:
                        continue

                    # Extract text from various possible fields
                    text = ""
                    if "text" in bubble:
                        text = bubble["text"]
                    elif "content" in bubble:
                        text = bubble["content"]

                    if text and isinstance(text, str):
                        role = "user" if bubble_type == "user" else "assistant"
                        yield tab_id, role, text, str(db)

        # Check for composer data
        composer_data = j(cur, "ItemTable", "composer.composerData")
        if composer_data:
            for comp in composer_data.get("allComposers", []):
                comp_id = comp.get("composerId", "unknown")
                messages = comp.get("messages", [])
                for msg in messages:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    if content:
                        yield comp_id, role, content, str(db)

        # Also check for aiService entries
        for key_prefix in ["aiService.prompts", "aiService.generations"]:
            try:
                cur.execute("SELECT key, value FROM ItemTable WHERE key LIKE ?", (f"{key_prefix}%",))
                for k, v in cur:
                    try:
                        data = json.loads(v)
                        if isinstance(data, list):
                            for item in data:
                                if "id" in item and "text" in item:
                                    role = "user" if "prompts" in key_prefix else "assistant"
                                    yield item.get("id", "unknown"), role, item.get("text", ""), str(db)
                    except json.JSONDecodeError:
                        continue
            except sqlite3.Error:
                continue

    except sqlite3.DatabaseError as e:
        logger.debug("Database error in ItemTable with %s: %s", db, e)
        return
    finally:
        if con is not None:
            con.close()


def iter_composer_data(db: pathlib.Path) -> Iterable[tuple[str, dict, str]]:
    """Yield (composerId, composerData, db_path) from cursorDiskKV table."""
    con = None
    try:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'")
            if not cur.fetchone():
                return
            cur.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")
        except sqlite3.DatabaseError as e:
            logger.debug("Database error with %s: %s", db, e)
            return

        db_path_str = str(db)

        for k, v in cur:
            try:
                if v is None:
                    continue
                composer_data = json.loads(v)
                composer_id = k.split(":")[1]
                yield composer_id, composer_data, db_path_str
            except Exception as e:
                logger.debug("Failed to parse composer data for key %s: %s", k, e)
                continue
    finally:
        if con is not None:
            con.close()


def _connect_cursor_disk_kv(db: pathlib.Path) -> sqlite3.Connection | None:
    """Open ``db`` read-only and confirm the ``cursorDiskKV`` table is present.

    Returns ``None`` (and logs at debug) for any error or for DBs that
    never grew the ``cursorDiskKV`` table; callers should iterate
    nothing in that case.
    """
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.DatabaseError as e:
        logger.debug("Database error opening %s: %s", db, e)
        return None
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'")
        if cur.fetchone() is None:
            con.close()
            return None
    except sqlite3.DatabaseError as e:
        logger.debug("Database error probing cursorDiskKV in %s: %s", db, e)
        con.close()
        return None
    return con


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
    try:
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
                try:
                    if v is None:
                        continue
                    b = json.loads(v)
                except Exception as e:
                    logger.debug("Failed to parse bubble JSON for key %s: %s", k, e)
                    continue
                if isinstance(b, dict):
                    file_uris, folder_uris = _extract_uris_from_bubble(b)
                    tool_call = _tool_call_from_bubble(b)
                else:
                    file_uris, folder_uris = [], []
                    tool_call = None
                txt = (b.get("text") or b.get("richText") or "").strip()
                if not txt and not file_uris and not folder_uris and tool_call is None:
                    continue
                role = "user" if b.get("type") == 1 else "assistant"
                # Re-split from the key rather than trusting the cid loop
                # variable, in case a malformed key slipped past the range
                # predicate (defensive; same parse as iter_bubbles_from_disk_kv).
                parts = k.split(":", 2)
                composerId = parts[1] if len(parts) >= 2 else ""
                bubbleId = parts[2] if len(parts) >= 3 else ""
                yield composerId, bubbleId, role, txt, db_path_str, file_uris, folder_uris, tool_call
    finally:
        con.close()


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
    try:
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
            chunk_size = 500
            for start in range(0, len(cids_list), chunk_size):
                chunk = cids_list[start:start + chunk_size]
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
    finally:
        con.close()
    return order


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
    try:
        cur = con.cursor()
        db_path_str = str(db)
        # Chunk to stay below SQLite's default SQLITE_MAX_VARIABLE_NUMBER.
        chunk_size = 500
        for start in range(0, len(cids_list), chunk_size):
            chunk = cids_list[start:start + chunk_size]
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
                try:
                    if v is None:
                        continue
                    composer_data = json.loads(v)
                    composer_id = k.split(":")[1]
                    yield composer_id, composer_data, db_path_str
                except Exception as e:
                    logger.debug("Failed to parse composer data for key %s: %s", k, e)
                    continue
    finally:
        con.close()
