"""Row-hash + JSON-peek helpers used by every diff pass.

Pane-view parsing (``aichat.view.<cid>`` key extraction and the pane
container value decode) lives in :mod:`cursor_view.projects.pane_view`;
this module re-exports those helpers under the underscore-prefixed
names the sibling diff passes already use so the diff subpackage
continues to speak in private-helper terms while sharing one
authoritative implementation with the workspace-scan pass.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from cursor_view.projects.pane_view import (
    AICHAT_VIEW_PREFIX as _PANE_VIEW_PREFIX,
    PANE_CONTAINER_PREFIX as _PANE_CONTAINER_PREFIX,
    cid_from_pane_view_key as _cid_from_pane_view_key,
    cids_from_pane_container_value as _cids_from_pane_container_value,
)

# The legacy ``workbench.panel.aichat.view.aichat.chatdata`` row shares
# :data:`_PANE_VIEW_PREFIX`; :mod:`cursor_view.cache.diff.global_db` reads it
# as an ordinary ItemTable key, and :mod:`cursor_view.cache.diff.workspace_db`
# excludes it from the pane-view classification branch. The constant is
# kept here (rather than imported from :mod:`cursor_view.projects.pane_view`
# where it is a private exclusion-list member) so the diff subpackage does
# not reach across a package boundary for a plain string literal.
_LEGACY_CHATDATA_KEY = "workbench.panel.aichat.view.aichat.chatdata"


def _hash_value(value: Any) -> str:
    """Truncated SHA-256 of a SQLite value; returns ``""`` for ``NULL``.

    128-bit prefix is plenty for the per-install row counts we track
    (typical is < 1M rows); storing the full 256-bit digest would
    inflate ``source_row`` without a collision-safety benefit.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        buf = value
    elif isinstance(value, str):
        buf = value.encode("utf-8")
    else:
        buf = str(value).encode("utf-8")
    return hashlib.sha256(buf).hexdigest()[:32]


def _composer_id_from_kv_key(key: str) -> str:
    """Extract ``<cid>`` from ``bubbleId:<cid>:<bid>`` or ``composerData:<cid>``."""
    parts = key.split(":", 2)
    return parts[1] if len(parts) >= 2 else ""


def _tool_call_id_from_bubble(raw: Any) -> str | None:
    """Parse a bubble value's ``toolFormerData.toolCallId`` or return ``None``.

    Only invoked for bubble rows whose hash actually changed, so the
    JSON decode cost stays proportional to the diff size rather than
    the full bubble corpus.
    """
    try:
        data = json.loads(raw) if raw else None
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    tf = data.get("toolFormerData")
    if not isinstance(tf, dict):
        return None
    tcid = tf.get("toolCallId")
    return tcid if isinstance(tcid, str) and tcid else None


def _legacy_tab_ids(raw: Any) -> list[str]:
    """Return the ``tabId`` strings from a legacy-chatdata blob."""
    try:
        data = json.loads(raw) if raw else None
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    for tab in data.get("tabs", []) or []:
        tid = tab.get("tabId") if isinstance(tab, dict) else None
        if isinstance(tid, str) and tid:
            out.append(tid)
    return out


# Re-exports for sibling diff passes. Keeping these as module-level names
# (rather than requiring every importer to reach into
# :mod:`cursor_view.projects.pane_view`) preserves the ``from .hashing
# import _cid_from_pane_view_key`` call sites in ``global_db`` / ``workspace_db``.
__all__ = [
    "_PANE_CONTAINER_PREFIX",
    "_PANE_VIEW_PREFIX",
    "_LEGACY_CHATDATA_KEY",
    "_cid_from_pane_view_key",
    "_cids_from_pane_container_value",
    "_composer_id_from_kv_key",
    "_hash_value",
    "_legacy_tab_ids",
    "_tool_call_id_from_bubble",
]
