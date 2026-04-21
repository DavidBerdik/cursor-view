"""Pass 7: scrape legacy ``workbench.panel.aichat.view.aichat.chatdata`` tabs."""

from __future__ import annotations

import logging
import pathlib
import sqlite3
from typing import Any, Dict

from cursor_view.sources.sqlite_util import j

logger = logging.getLogger(__name__)


def _collect_global_item_table_chats(
    global_db: pathlib.Path,
    sessions: Dict[str, Dict[str, Any]],
    comp_meta: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    cids: set[str] | None = None,
) -> None:
    """Pass 7: scrape legacy ``workbench.panel.aichat.view.aichat.chatdata`` tabs.

    This is an older chat storage format that predates the
    ``cursorDiskKV``/``composerData`` split; wrapped in a broad
    ``try/except`` so a schema mismatch in this legacy path never takes
    down the rest of the extraction.

    When ``cids`` is given, the blob is still fully parsed (the legacy
    value is stored as a single JSON row so there's no SQL-level way to
    narrow it) but messages are only written for tab ids in the dirty
    set.
    """
    try:
        con = sqlite3.connect(f"file:{global_db}?mode=ro", uri=True)
        chat_data = j(con.cursor(), "ItemTable", "workbench.panel.aichat.view.aichat.chatdata")
        if chat_data:
            msg_count = 0
            for tab in chat_data.get("tabs", []):
                tab_id = tab.get("tabId")
                if cids is not None and tab_id not in cids:
                    continue
                if tab_id and tab_id not in comp_meta:
                    comp_meta[tab_id] = {
                        "title": f"Global Chat {tab_id[:8]}",
                        "createdAt": None,
                        "lastUpdatedAt": None,
                    }
                    comp2ws[tab_id] = "(global)"

                for bubble in tab.get("bubbles", []):
                    content = ""
                    if "text" in bubble:
                        content = bubble["text"]
                    elif "content" in bubble:
                        content = bubble["content"]

                    if content and isinstance(content, str):
                        role = "user" if bubble.get("type") == "user" else "assistant"
                        sessions[tab_id]["messages"].append({"role": role, "content": content})
                        msg_count += 1
            logger.debug("  - Extracted %s messages from global chat data", msg_count)
        con.close()
    except Exception as e:
        logger.debug("Error processing global ItemTable: %s", e)
