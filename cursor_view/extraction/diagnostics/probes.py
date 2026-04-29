"""Source-DB and chat-index-cache probes for resolution traces.

Each probe is a one-shot read against a single sqlite file. They all
return ``None`` (or zero, or an empty dict) on missing rows / DB
errors rather than raising, because every probe outcome is a valid
signal for :func:`cursor_view.extraction.diagnostics.trace.trace_project_resolution`
to fold into its trace dict. Callers that want to distinguish "probe
failed" from "row not present" inspect the surrounding context (e.g.
whether the DB file existed at all) rather than relying on
exceptions.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from contextlib import closing
from typing import Any


def probe_composer_row(global_db: pathlib.Path, cid: str) -> dict[str, Any] | None:
    """Read ``composerData:<cid>`` and surface the fields Passes 3 and 5 read.

    ``None`` means the row is missing entirely, which on its own is a
    Cause 4 indicator (subagent persisted as bubbles only with no
    ``composerData`` body).
    """
    try:
        con = sqlite3.connect(f"file:{global_db}?mode=ro", uri=True)
    except sqlite3.DatabaseError:
        return None
    with closing(con):
        cur = con.cursor()
        try:
            cur.execute(
                "SELECT value FROM cursorDiskKV WHERE key=?",
                (f"composerData:{cid}",),
            )
            row = cur.fetchone()
        except sqlite3.DatabaseError:
            return None
        if not row or row[0] is None:
            return None
        try:
            data = json.loads(row[0])
        except Exception:
            return _empty_composer_probe()
    if not isinstance(data, dict):
        return _empty_composer_probe()
    headers = data.get("fullConversationHeadersOnly")
    return {
        "name": data.get("name"),
        "subagent_info": data.get("subagentInfo"),
        "headers_count": len(headers) if isinstance(headers, list) else 0,
        "has_workspace_identifier": bool(data.get("workspaceIdentifier")),
    }


def _empty_composer_probe() -> dict[str, Any]:
    return {
        "name": None,
        "subagent_info": None,
        "headers_count": 0,
        "has_workspace_identifier": False,
    }


def count_bubbles_for_cid(global_db: pathlib.Path, cid: str) -> int:
    """PK-range scan of ``bubbleId:<cid>:*`` rows.

    Mirrors the upper-bound trick in
    :func:`cursor_view.sources.bubbles.iter_bubbles_for_cids` (``;`` is
    the byte directly after ``:``) so the count runs on the implicit
    primary-key index without a LIKE escape.
    """
    lower = f"bubbleId:{cid}:"
    upper = f"bubbleId:{cid};"
    try:
        con = sqlite3.connect(f"file:{global_db}?mode=ro", uri=True)
    except sqlite3.DatabaseError:
        return 0
    with closing(con):
        cur = con.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM cursorDiskKV WHERE key > ? AND key < ?",
                (lower, upper),
            )
            row = cur.fetchone()
        except sqlite3.DatabaseError:
            return 0
    return int(row[0]) if row else 0


def find_bubble_with_tool_call_id(
    global_db: pathlib.Path, tcid: str
) -> dict[str, Any] | None:
    """Locate any bubble whose ``toolFormerData.toolCallId`` matches ``tcid``.

    A hit here when ``tool_call_parent`` has no cache row for the same
    ``tcid`` is the smoking gun for Cause 1: the bubble is on disk but
    Pass 2's orphan filter dropped the ``tool_call_parent`` upsert
    because the bubble id is absent from the parent composer's
    ``fullConversationHeadersOnly`` array. The returned dict carries
    the parent ``cid``, the bubble id, and an ``in_parent_headers``
    flag so the classifier can distinguish Cause 1 from Cause 4 in
    one read.

    Implemented as a full ``bubbleId:%`` scan; acceptable for a
    one-shot diagnostic, never on a hot path.
    """
    if not tcid:
        return None
    try:
        con = sqlite3.connect(f"file:{global_db}?mode=ro", uri=True)
    except sqlite3.DatabaseError:
        return None
    found: dict[str, Any] | None = None
    with closing(con):
        cur = con.cursor()
        try:
            cur.execute(
                "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"
            )
            for key, value in cur:
                if value is None:
                    continue
                try:
                    bubble = json.loads(value)
                except Exception:
                    continue
                if not isinstance(bubble, dict):
                    continue
                tf = bubble.get("toolFormerData")
                if not isinstance(tf, dict) or tf.get("toolCallId") != tcid:
                    continue
                parts = key.split(":", 2)
                parent_cid = parts[1] if len(parts) >= 2 else ""
                bubble_id = parts[2] if len(parts) >= 3 else ""
                found = {
                    "parent_cid": parent_cid,
                    "bubble_id": bubble_id,
                    "tool_name": tf.get("name"),
                    "in_parent_headers": _bubble_in_parent_headers(
                        con, parent_cid, bubble_id
                    ),
                }
                break
        except sqlite3.DatabaseError:
            return None
    return found


def _bubble_in_parent_headers(
    con: sqlite3.Connection, parent_cid: str, bubble_id: str
) -> bool | None:
    """Return whether ``bubble_id`` is in the parent's headers array.

    ``None`` means the parent has no ``composerData`` row or the
    headers field is missing / not a list (legacy build); ``False``
    means the array is well-formed and the bubble id is NOT present,
    which is exactly the orphan-filter trigger condition Pass 2 acts
    on; ``True`` means the bubble is canonical and the orphan filter
    should not have fired.
    """
    cur = con.cursor()
    try:
        cur.execute(
            "SELECT value FROM cursorDiskKV WHERE key=?",
            (f"composerData:{parent_cid}",),
        )
        row = cur.fetchone()
    except sqlite3.DatabaseError:
        return None
    if not row or row[0] is None:
        return None
    try:
        data = json.loads(row[0])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    headers = data.get("fullConversationHeadersOnly")
    if not isinstance(headers, list) or not headers:
        return None
    for entry in headers:
        if isinstance(entry, dict) and entry.get("bubbleId") == bubble_id:
            return True
    return False


def lookup_tool_call_parent(cache_db: pathlib.Path, tcid: str) -> str | None:
    """Read the persisted ``tool_call_parent`` row for ``tcid``.

    A miss means Pass 2 never recorded the edge (Cause 1 / Cause 4)
    AND the cache has not since recovered it. A hit means Pass 5 had
    every signal it needed; a still-broken chain therefore implicates
    Pass 6 (Cause 2) or a workspace-less ancestor (Cause 3).
    """
    if not tcid:
        return None
    try:
        con = sqlite3.connect(f"file:{cache_db}?mode=ro", uri=True)
    except sqlite3.DatabaseError:
        return None
    with closing(con):
        cur = con.cursor()
        try:
            cur.execute(
                "SELECT parent_composer_id FROM tool_call_parent WHERE tool_call_id=?",
                (tcid,),
            )
            row = cur.fetchone()
        except sqlite3.DatabaseError:
            return None
    return row[0] if row else None


def lookup_chat_summary(cache_db: pathlib.Path, cid: str) -> dict[str, Any] | None:
    """Read ``chat_summary`` plus ``composer_state`` for ``cid``."""
    try:
        con = sqlite3.connect(f"file:{cache_db}?mode=ro", uri=True)
    except sqlite3.DatabaseError:
        return None
    with closing(con):
        cur = con.cursor()
        try:
            cur.execute(
                "SELECT workspace_id, project_name, project_root_path "
                "FROM chat_summary WHERE session_id=?",
                (cid,),
            )
            summary = cur.fetchone()
            cur.execute(
                "SELECT workspace_id FROM composer_state WHERE session_id=?",
                (cid,),
            )
            state = cur.fetchone()
        except sqlite3.DatabaseError:
            return None
    if not summary and not state:
        return None
    return {
        "workspace_id": summary[0] if summary else None,
        "project_name": summary[1] if summary else None,
        "project_root_path": summary[2] if summary else None,
        "composer_state_workspace_id": state[0] if state else None,
    }
