"""Pane-view key parsing: the single home for ``aichat.view.<cid>`` logic.

Cursor persists per-chat UI state under two related key prefixes:

- ``workbench.panel.aichat.view.<composerId>`` directly under the
  ``ItemTable`` row set.
- ``workbench.panel.composerChatViewPane.<paneInstanceId>`` whose JSON
  value contains sub-keys of the first form.

Both forms carry the composer UUID we care about; the pane-instance UUID
(the ``<paneInstanceId>`` in the second prefix) is NOT a composer id and
must never be treated as one. The helpers below are the one authoritative
place that enforces the "only trust ``aichat.view.<UUID>`` matches"
invariant, so both the extraction pipeline (via
:func:`composer_ids_from_pane_view_state`) and the cache's source-diff
hashing share identical semantics.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

COMPOSER_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
AICHAT_VIEW_PREFIX = "workbench.panel.aichat.view."
PANE_CONTAINER_PREFIX = "workbench.panel.composerChatViewPane."
# The legacy ``workbench.panel.aichat.view.aichat.chatdata`` row shares
# :data:`AICHAT_VIEW_PREFIX`; callers filtering by prefix must exclude it
# explicitly so its suffix is never fed through the UUID test.
_LEGACY_CHATDATA_KEY = "workbench.panel.aichat.view.aichat.chatdata"


def cid_from_pane_view_key(key: str) -> str:
    """Return the composer id embedded in an ``aichat.view.<cid>`` key, or ``""``.

    Pane-instance rows under :data:`PANE_CONTAINER_PREFIX` are ignored here;
    their UUIDs are pane-instance ids, not composer ids. The legacy
    ``aichat.chatdata`` sibling row is also filtered out.
    """
    if key == _LEGACY_CHATDATA_KEY or not key.startswith(AICHAT_VIEW_PREFIX):
        return ""
    seg = key[len(AICHAT_VIEW_PREFIX):]
    return seg if COMPOSER_UUID_RE.match(seg) else ""


def cids_from_pane_container_value(raw: Any) -> list[str]:
    """Extract composer ids from a ``composerChatViewPane.<paneId>`` JSON value.

    The container value is a JSON object whose keys are sub-keys of the
    ``aichat.view.<cid>`` form. Only sub-keys that match the composer UUID
    regex contribute a cid; everything else is ignored.
    """
    try:
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    for sk in data.keys():
        if not isinstance(sk, str):
            continue
        cid = cid_from_pane_view_key(sk)
        if cid:
            out.append(cid)
    return out


def composer_ids_from_pane_view_state(cur: sqlite3.Cursor) -> list[str]:
    """Return composer ids linked to this workspace via UI pane view keys.

    Cursor persists per-chat UI state as ``workbench.panel.aichat.view.<cid>``
    keys, either directly in ``ItemTable`` or as sub-keys inside
    ``workbench.panel.composerChatViewPane.<paneId>`` values. The pane key's
    own UUID is a pane-instance id, NOT a composer id, so we only trust the
    ``aichat.view.<cid>`` form. Research-only chats (no file ops) leave no
    other workspace signal, so this key is often their only link back to a
    real workspace.

    The ``aichat.view.<UUID>``-only filter is empirically justified: on the
    install this fix was developed against, 0 of 541 outer
    ``composerChatViewPane.<UUID>`` UUIDs matched any known composer id in
    ``cursorDiskKV``, while 671 of 421 distinct sub-key UUIDs did. A future
    maintainer tempted to simplify by also trusting the outer UUID should
    re-run that audit before doing so; relaxing the filter would pollute
    ``comp2ws`` with pane-instance ids that never correspond to a chat.
    """
    cids: set[str] = set()
    cur.execute(
        "SELECT key FROM ItemTable WHERE key LIKE ?",
        (AICHAT_VIEW_PREFIX + "%",),
    )
    for (k,) in cur.fetchall():
        cid = cid_from_pane_view_key(k)
        if cid:
            cids.add(cid)
    cur.execute(
        "SELECT value FROM ItemTable WHERE key LIKE ?",
        (PANE_CONTAINER_PREFIX + "%",),
    )
    for (v,) in cur.fetchall():
        cids.update(cids_from_pane_container_value(v))
    return sorted(cids)
