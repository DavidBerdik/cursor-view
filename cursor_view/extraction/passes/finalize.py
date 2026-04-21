"""Pass 8: drop empty sessions, resolve each session's project, sort by recency."""

from __future__ import annotations

import logging
from typing import Any, Dict

from cursor_view.timestamps import session_sort_key_ms

logger = logging.getLogger(__name__)


def _finalize_sessions(
    sessions: Dict[str, Dict[str, Any]],
    ws_proj: Dict[str, Dict[str, Any]],
    comp2ws: Dict[str, str],
    comp_meta: Dict[str, Dict[str, Any]],
    cids: set[str] | None = None,
) -> list[Dict[str, Any]]:
    """Pass 8: drop empty sessions, resolve each one's project, sort by recency.

    Project resolution preference:

    1. The workspace's own project, if named.
    2. A project inferred from URIs / composer files.
    3. The workspace project as-is (which may be ``(unknown)``), or the
       sentinel ``{"name": "(unknown)", ...}`` as a last resort.

    Reaching branch 3 means every upstream pass has failed for this
    composer: no workspaceIdentifier, no pane-view-key link (Pass 1),
    no bubble URIs (Pass 4), no ``subagentInfo`` parent and no
    ``task-<toolCallId>`` reconstruction (Passes 5 + 6). A steady
    trickle of these is expected (e.g. ephemeral global-only chats),
    but a sudden spike in ``(unknown)`` counts is an operational
    signal that Cursor's on-disk schema has shifted again and the
    pipeline likely needs another heuristic rather than a tweak to
    an existing pass.

    When ``cids`` is given, only sessions for those composers are
    emitted; ancestor composers whose state lived in the scratch dicts
    purely to support Pass 6's walk are dropped here so the output
    matches the dirty set the caller asked about.
    """
    out = []
    for cid, data in sessions.items():
        if cids is not None and cid not in cids:
            continue
        if not data["messages"]:
            continue
        ws_id = comp2ws.get(cid, "(unknown)")
        ws_project = ws_proj.get(ws_id)
        inferred_project = data.get("_inferred_project")
        if ws_project and ws_project.get("name") not in (None, "(unknown)"):
            project = ws_project
        elif inferred_project:
            project = inferred_project
        else:
            project = ws_project or {"name": "(unknown)", "rootPath": "(unknown)"}
        meta = comp_meta.get(cid, {"title": "(untitled)", "createdAt": None, "lastUpdatedAt": None})

        chat_data = {
            "project": project,
            "session": {"composerId": cid, **meta},
            "messages": data["messages"],
            "workspace_id": ws_id,
        }

        if "db_path" in data:
            chat_data["db_path"] = data["db_path"]

        out.append(chat_data)

    # Sort by recency (parsed ms) so ordering matches timestamp semantics.
    out.sort(key=lambda s: session_sort_key_ms(s.get("session", {})), reverse=True)
    logger.debug("Total chat sessions extracted: %s", len(out))
    return out
