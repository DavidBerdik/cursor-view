"""Pass 7: scrape legacy ``workbench.panel.aichat.view.aichat.chatdata`` tabs."""

from __future__ import annotations

import logging
import pathlib
from typing import Any, Dict

from cursor_view.sources.item_table import iter_global_legacy_chatdata

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
    ``cursorDiskKV``/``composerData`` split. The SQL-level read lives
    in :func:`cursor_view.sources.item_table.iter_global_legacy_chatdata`
    so extraction consumes sources rather than opening SQLite directly.

    When ``cids`` is given, the underlying blob is still fully parsed
    (the legacy value is stored as a single JSON row so there's no
    SQL-level way to narrow it) but messages are only written for tab
    ids in the dirty set.
    """
    msg_count = 0
    for tab_id, role, content in iter_global_legacy_chatdata(global_db):
        if cids is not None and tab_id not in cids:
            continue
        if tab_id not in comp_meta:
            comp_meta[tab_id] = {
                "title": f"Global Chat {tab_id[:8]}",
                "createdAt": None,
                "lastUpdatedAt": None,
            }
            comp2ws[tab_id] = "(global)"
        sessions[tab_id]["messages"].append({"role": role, "content": content})
        msg_count += 1
    if msg_count:
        logger.debug("  - Extracted %s messages from global chat data", msg_count)
