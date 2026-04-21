"""Read chat-like rows out of Cursor's ``ItemTable`` (workspace and global)."""

from __future__ import annotations

import json
import logging
import pathlib
import sqlite3
from contextlib import closing
from typing import Iterable

from cursor_view.sources.sqlite_util import j

logger = logging.getLogger(__name__)


def iter_chat_from_item_table(db: pathlib.Path) -> Iterable[tuple[str, str, str, str]]:
    """Yield ``(composerId, role, text, db_path)`` from a workspace ``ItemTable``.

    Three shapes the workspace DB can carry:

    - ``workbench.panel.aichat.view.aichat.chatdata`` — the legacy
      per-tab chat storage that predates ``cursorDiskKV``.
    - ``composer.composerData`` — ``allComposers[*].messages`` on the
      rare builds that persisted messages inline.
    - ``aiService.prompts`` / ``aiService.generations`` — prompt /
      generation records; yielded as single-message "chats" keyed by
      the record id.
    """
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.DatabaseError as e:
        logger.debug("Database error in ItemTable with %s: %s", db, e)
        return
    with closing(con):
        cur = con.cursor()
        try:
            chat_data = j(cur, "ItemTable", "workbench.panel.aichat.view.aichat.chatdata")
            if chat_data and "tabs" in chat_data:
                for tab in chat_data.get("tabs", []):
                    tab_id = tab.get("tabId", "unknown")
                    for bubble in tab.get("bubbles", []):
                        bubble_type = bubble.get("type")
                        if not bubble_type:
                            continue
                        text = ""
                        if "text" in bubble:
                            text = bubble["text"]
                        elif "content" in bubble:
                            text = bubble["content"]
                        if text and isinstance(text, str):
                            role = "user" if bubble_type == "user" else "assistant"
                            yield tab_id, role, text, str(db)

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

            for key_prefix in ["aiService.prompts", "aiService.generations"]:
                try:
                    cur.execute(
                        "SELECT key, value FROM ItemTable WHERE key LIKE ?",
                        (f"{key_prefix}%",),
                    )
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
