"""Row-hash + JSON-peek helpers used by every diff pass."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_COMPOSER_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

_PANE_VIEW_PREFIX = "workbench.panel.aichat.view."
_PANE_CONTAINER_PREFIX = "workbench.panel.composerChatViewPane."
# The legacy-chatdata key shares ``_PANE_VIEW_PREFIX`` so it must be
# checked before the pane-view classification branch runs.
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


def _cid_from_pane_view_key(key: str) -> str:
    """Return the UUID ``<cid>`` in ``workbench.panel.aichat.view.<cid>`` or ``""``.

    The UUID filter mirrors
    :func:`cursor_view.projects.pane_view.composer_ids_from_pane_view_state`
    so we don't pollute the dirty set with pane-instance ids that were
    never composer ids.
    """
    if key == _LEGACY_CHATDATA_KEY or not key.startswith(_PANE_VIEW_PREFIX):
        return ""
    seg = key[len(_PANE_VIEW_PREFIX):]
    return seg if _COMPOSER_UUID_RE.match(seg) else ""


def _cids_from_pane_container_value(raw: Any) -> list[str]:
    """Decode a ``composerChatViewPane.<paneId>`` value to its nested cid sub-keys."""
    try:
        data = json.loads(raw) if raw else None
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    for sk in data.keys():
        if not isinstance(sk, str):
            continue
        cid = _cid_from_pane_view_key(sk)
        if cid:
            out.append(cid)
    return out


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
