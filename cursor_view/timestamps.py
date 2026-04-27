"""Parse Cursor session timestamps for sorting and UI."""

import datetime
import re
from typing import Any


def parse_cursor_timestamp_to_ms(value: Any) -> int | None:
    """Parse Cursor's stored time (ms epoch, s epoch, or ISO string) to Unix ms."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        if n != n:  # NaN
            return None
        # Heuristic: ms since epoch is ~1.7e12; seconds ~1.7e9
        if abs(n) > 1e11:
            return int(n)
        return int(n * 1000)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if re.match(r"^-?\d+(\.\d+)?$", s):
            try:
                return parse_cursor_timestamp_to_ms(float(s))
            except (ValueError, OverflowError):
                return None
        return _parse_iso_timestamp_to_ms(s)
    return None


def _parse_iso_timestamp_to_ms(s: str) -> int | None:
    """Parse an ISO-8601 datetime string to Unix milliseconds (UTC if naive)."""
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() * 1000)


def session_sort_key_ms(session: dict) -> int:
    """Recency sort: createdAt, then lastUpdatedAt (same priority as the displayed date).

    Sharing the priority order with :func:`session_display_date_seconds`
    keeps each project's card grid in the order the user actually sees
    on the cards. Cursor bumps ``composerData.lastUpdatedAt`` for
    navigation-only writes (see :file:`.cursor/rules/sqlite-cursor-db.mdc`
    "Invalidation: hash rows, don't stat files"), so a ``lastUpdatedAt``-
    first sort would re-order the list every time the user idly clicks
    through a chat without editing it -- and the displayed
    ``createdAt`` on the card would then disagree with the chat's
    position in the grid.
    """
    if not isinstance(session, dict):
        return 0
    cr = parse_cursor_timestamp_to_ms(session.get("createdAt"))
    if cr is not None:
        return cr
    lu = parse_cursor_timestamp_to_ms(session.get("lastUpdatedAt"))
    return lu if lu is not None else 0


def session_display_date_seconds(session: dict) -> int | None:
    """Unix seconds for UI: prefer createdAt, then lastUpdatedAt.

    The priority order is intentionally identical to
    :func:`session_sort_key_ms` so the date shown on a chat card and
    the chat's position in the per-project grid are derived from the
    same Cursor field.
    """
    if not isinstance(session, dict):
        return None
    for key in ("createdAt", "lastUpdatedAt"):
        ms = parse_cursor_timestamp_to_ms(session.get(key))
        if ms is not None:
            return ms // 1000
    return None
