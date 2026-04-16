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
        logger.debug(f"Failed to parse JSON for {key}: {e}")
        # Some Cursor/VSCode keys (e.g. debug.selectedroot) store a raw string
        # without JSON quoting. Preserve it so downstream fallbacks can use it.
        if isinstance(raw, str) and raw:
            return raw
        return None


def iter_bubbles_from_disk_kv(
    db: pathlib.Path,
) -> Iterable[tuple[str, str, str, str, list[str], list[str]]]:
    """Yield (composerId, role, text, db_path, file_uris, folder_uris).

    ``file_uris`` and ``folder_uris`` are kept separate so project inference
    can trim filenames from files while treating folders as candidate roots.
    """
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = con.cursor()
        # Check if table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'")
        if not cur.fetchone():
            con.close()
            return

        cur.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'")
    except sqlite3.DatabaseError as e:
        logger.debug(f"Database error with {db}: {e}")
        return

    db_path_str = str(db)

    for k, v in cur.fetchall():
        try:
            if v is None:
                continue

            b = json.loads(v)
        except Exception as e:
            logger.debug(f"Failed to parse bubble JSON for key {k}: {e}")
            continue

        if isinstance(b, dict):
            file_uris, folder_uris = _extract_uris_from_bubble(b)
        else:
            file_uris, folder_uris = [], []
        txt = (b.get("text") or b.get("richText") or "").strip()
        # Preserve bubbles that carry workspaceUris/relevantFiles etc. even if
        # they have no text, so project inference can see the URIs.
        if not txt and not file_uris and not folder_uris:
            continue
        role = "user" if b.get("type") == 1 else "assistant"
        composerId = k.split(":")[1]  # Format is bubbleId:composerId:bubbleId
        yield composerId, role, txt, db_path_str, file_uris, folder_uris

    con.close()


def iter_chat_from_item_table(db: pathlib.Path) -> Iterable[tuple[str, str, str, str]]:
    """Yield (composerId, role, text, db_path) from ItemTable."""
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
                for k, v in cur.fetchall():
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
        logger.debug(f"Database error in ItemTable with {db}: {e}")
        return
    finally:
        if "con" in locals():
            con.close()


def iter_composer_data(db: pathlib.Path) -> Iterable[tuple[str, dict, str]]:
    """Yield (composerId, composerData, db_path) from cursorDiskKV table."""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        cur = con.cursor()
        # Check if table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'")
        if not cur.fetchone():
            con.close()
            return

        cur.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")
    except sqlite3.DatabaseError as e:
        logger.debug(f"Database error with {db}: {e}")
        return

    db_path_str = str(db)

    for k, v in cur.fetchall():
        try:
            if v is None:
                continue

            composer_data = json.loads(v)
            composer_id = k.split(":")[1]
            yield composer_id, composer_data, db_path_str

        except Exception as e:
            logger.debug(f"Failed to parse composer data for key {k}: {e}")
            continue

    con.close()
