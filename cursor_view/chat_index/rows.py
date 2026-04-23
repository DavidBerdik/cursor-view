"""Row-shaping helpers shared by the full rebuild and incremental apply paths."""

from __future__ import annotations

import base64
import logging
import re
import sqlite3
from typing import Any

from cursor_view.chat_format import (
    coalesce_consecutive_messages_by_role,
    format_chat_for_frontend,
)
from cursor_view.images import image_ref_from_transport_dict, load_image_bytes
from cursor_view.timestamps import session_sort_key_ms

logger = logging.getLogger(__name__)


def _trim_preview(text: str, limit: int = 240) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _preview_from_messages(messages: list[dict[str, Any]]) -> str:
    first_user = None
    first_any = None
    for msg in messages:
        content = msg.get("content", "") if isinstance(msg, dict) else ""
        if not isinstance(content, str) or not content.strip():
            continue
        if first_any is None:
            first_any = content
        if msg.get("role") == "user":
            first_user = content
            break
    return _trim_preview(first_user or first_any or "Content unavailable")


def _search_blob(project: dict[str, Any], messages: list[dict[str, Any]], preview: str) -> str:
    fields = [
        project.get("name", ""),
        project.get("rootPath", ""),
        preview,
    ]
    fields.extend(
        msg.get("content", "")
        for msg in messages
        if isinstance(msg, dict) and isinstance(msg.get("content"), str)
    )
    return "\n".join(part for part in fields if isinstance(part, str) and part)


def _fts_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", query.lower())
    return " AND ".join(f'"{token}"*' for token in tokens)


def _insert_chat(
    cur: sqlite3.Cursor, chat: dict[str, Any], fts_enabled: bool
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Write one chat into the content tables and return ``(formatted, messages)``.

    Used by both the full rebuild and the incremental apply path.
    The caller is responsible for having already cleared any prior
    rows for ``session_id`` from the content tables (the full
    rebuild runs against a fresh temp DB; the incremental apply
    runs :func:`cursor_view.cache.delta.composer_rows._delete_cid_rows`
    first). This method therefore always re-numbers ``position``
    from ``0`` using :func:`enumerate` on the coalesced messages
    list; ``position`` is a per-refresh local index, NOT a globally
    stable identifier. Callers that need a stable per-message id
    should use ``(session_id, position)`` pairs read back after
    the most recent refresh.

    The return value hands the same ``formatted`` dict and
    ``coalesced_messages`` list produced here back to the caller
    so the incremental apply path and the full-rebuild backfill
    can feed them straight into
    :func:`cursor_view.cache.delta.composer_rows._upsert_composer_state`
    without re-running :func:`format_chat_for_frontend` +
    :func:`coalesce_consecutive_messages_by_role` on every refreshed
    composer. Those are the dominant per-chat costs on the write
    path; paying them twice per composer wasted roughly half the
    incremental-refresh wall-time budget.

    ``_insert_chat`` relies on ``formatted["messages"]`` already
    being in the correct chronological order produced by
    :func:`cursor_view.extraction.extract_chats`; it does no
    sorting of its own and trusts the upstream pipeline, so the
    bubble-order fix lives there rather than here.

    Image BLOBs are materialized here via
    :func:`_insert_chat_images` so the chat-index is the single
    cache of record -- Cursor's original on-disk files may be
    deleted without data loss once a composer has been indexed.
    """
    formatted = format_chat_for_frontend(chat)
    messages = coalesce_consecutive_messages_by_role(formatted.get("messages", []))
    session_id = formatted["session_id"]
    project = formatted.get("project") or {}
    preview = _preview_from_messages(messages)
    search_blob = _search_blob(project, messages, preview)
    sort_key_ms = session_sort_key_ms(chat.get("session", {}))
    cur.execute(
        """
        INSERT INTO chat_summary(
            session_id,
            project_name,
            project_root_path,
            date,
            workspace_id,
            db_path,
            message_count,
            preview,
            sort_key_ms
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            project.get("name") or "Unknown Project",
            project.get("rootPath") or "Unknown",
            formatted.get("date"),
            formatted.get("workspace_id") or "unknown",
            formatted.get("db_path") or "Unknown database path",
            len(messages),
            preview,
            sort_key_ms,
        ),
    )
    cur.executemany(
        """
        INSERT INTO chat_message(session_id, position, role, content)
        VALUES(?, ?, ?, ?)
        """,
        (
            (session_id, index, msg.get("role", "assistant"), msg.get("content", ""))
            for index, msg in enumerate(messages)
        ),
    )
    _insert_chat_images(cur, session_id, messages)
    cur.execute(
        "INSERT INTO chat_search_text(session_id, content) VALUES(?, ?)",
        (session_id, search_blob),
    )
    if fts_enabled:
        cur.execute(
            "INSERT INTO chat_search_fts(session_id, content) VALUES(?, ?)",
            (session_id, search_blob),
        )
    return formatted, messages


_INSERT_CHAT_IMAGE_SQL = (
    "INSERT INTO chat_image("
    "session_id, position, image_index, uuid, mime_type, width, height, data"
    ") VALUES(?, ?, ?, ?, ?, ?, ?, ?)"
)


def _insert_chat_images(
    cur: sqlite3.Cursor,
    session_id: str,
    messages: list[dict[str, Any]],
) -> None:
    """Materialize ``messages`` image attachments into ``chat_image``.

    ``position`` shares the :func:`enumerate` index with the owning
    ``chat_message`` row, joining images to messages without a
    separate ordinal. Malformed sources are logged and skipped by
    :func:`cursor_view.images.load_image_bytes` so one broken
    attachment never drops a whole message.
    """
    for position, msg in enumerate(messages):
        for image_index, image_dict in enumerate(msg.get("images") or []):
            if not isinstance(image_dict, dict):
                continue
            ref = image_ref_from_transport_dict(image_dict)
            if ref is None:
                logger.debug(
                    "Skipping malformed image transport dict at %s/%s: %r",
                    session_id, position, image_dict,
                )
                continue
            loaded = load_image_bytes(ref)
            if loaded is None:
                continue
            data, mime = loaded
            cur.execute(
                _INSERT_CHAT_IMAGE_SQL,
                (session_id, position, image_index, ref.uuid,
                 mime, ref.width, ref.height, data),
            )


_FETCH_IMAGES_WITH_BYTES_SQL = (
    "SELECT position, image_index, uuid, mime_type, width, height, data "
    "FROM chat_image WHERE session_id = ? "
    "ORDER BY position ASC, image_index ASC"
)
_FETCH_IMAGES_METADATA_SQL = (
    "SELECT position, image_index, uuid, mime_type, width, height "
    "FROM chat_image WHERE session_id = ? "
    "ORDER BY position ASC, image_index ASC"
)


def _fetch_images_for_session(
    con: sqlite3.Connection,
    session_id: str,
    *,
    include_bytes: bool,
) -> list[dict[str, Any]]:
    """Return image metadata (and optionally bytes) for ``session_id``.

    Rows are ordered by ``(position, image_index)`` so callers can
    bucket them per message without a secondary sort. ``include_bytes``
    is opt-in: chat-detail JSON stays metadata-only by default;
    exports flip it on to inline ``data:<mime>;base64,...`` URIs. The
    two SQL constants stay distinct so a typo cannot silently inherit
    the other's column list.
    """
    cur = con.cursor()
    cur.execute(
        _FETCH_IMAGES_WITH_BYTES_SQL if include_bytes else _FETCH_IMAGES_METADATA_SQL,
        (session_id,),
    )
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        entry: dict[str, Any] = {
            "position": row["position"],
            "image_index": row["image_index"],
            "uuid": row["uuid"],
            "mime_type": row["mime_type"],
            "width": row["width"],
            "height": row["height"],
        }
        if include_bytes:
            encoded = base64.b64encode(bytes(row["data"])).decode("ascii")
            entry["data_uri"] = f"data:{row['mime_type']};base64,{encoded}"
        out.append(entry)
    return out


def _attach_images_to_messages(
    con: sqlite3.Connection,
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    include_bytes: bool,
) -> None:
    """Bucket ``chat_image`` rows into each message's ``images`` list.

    Pops storage-only ``position`` / ``image_index`` keys (both
    served their ordering job upstream) and logs-and-drops any
    out-of-range position so the caller sees the remaining images,
    not a crash. The warning makes the silent-data-loss path (manual
    DB edits, partial delta applies, future regressions) observable
    rather than invisible.
    """
    image_rows = _fetch_images_for_session(
        con, session_id, include_bytes=include_bytes
    )
    for image in image_rows:
        position = image.pop("position")
        image_index = image.pop("image_index", None)
        if 0 <= position < len(messages):
            messages[position]["images"].append(image)
        else:
            logger.warning(
                "Dropping out-of-range chat_image row for %s: "
                "position=%s, image_index=%s, uuid=%s, message_count=%s",
                session_id, position, image_index,
                image.get("uuid"), len(messages),
            )


def _count_summaries(con: sqlite3.Connection, query: str) -> int:
    """Count chat summaries matching ``query`` (or all rows if ``query`` is empty).

    Branches based on whether SQLite was compiled with FTS5:

    - When ``chat_search_fts`` is available and the tokenized query is
      non-empty, run a MATCH against the FTS virtual table.
    - Otherwise (older / minimal sqlite builds, or a query that
      tokenized to nothing), fall back to a case-insensitive ``LIKE
      '%query%'`` against the plain ``chat_search_text`` table.

    Both branches join back to ``chat_summary`` to scope the count to
    real sessions.
    """
    cur = con.cursor()
    if not query:
        cur.execute("SELECT COUNT(*) FROM chat_summary")
        row = cur.fetchone()
        return int(row[0] if row else 0)
    fts_query = _fts_query(query)
    if fts_query and _database_has_fts(con):
        cur.execute(
            """
            SELECT COUNT(*)
            FROM chat_summary AS summary
            JOIN chat_search_fts
              ON chat_search_fts.session_id = summary.session_id
            WHERE chat_search_fts MATCH ?
            """,
            (fts_query,),
        )
        row = cur.fetchone()
        return int(row[0] if row else 0)
    like = f"%{query.lower()}%"
    cur.execute(
        """
        SELECT COUNT(*)
        FROM chat_summary AS summary
        JOIN chat_search_text AS search
          ON search.session_id = summary.session_id
        WHERE lower(search.content) LIKE ?
        """,
        (like,),
    )
    row = cur.fetchone()
    return int(row[0] if row else 0)


def _fetch_summaries(
    con: sqlite3.Connection,
    query: str,
    limit: int | None,
    offset: int,
) -> list[sqlite3.Row]:
    """Fetch chat summary rows, optionally filtered, sorted, and paginated.

    Sort order:

    - Empty query: most recent first (``sort_key_ms DESC``), ties
      broken by ``session_id ASC``.
    - FTS match: ``bm25(chat_search_fts)`` relevance first, then
      recency, then session id.
    - LIKE fallback: recency, then session id.

    Pagination: ``LIMIT/OFFSET`` when ``limit`` is provided, and
    ``LIMIT -1 OFFSET ?`` (SQLite's idiom for offsetting without a
    cap) when only an offset is provided. Mirrors the branching in
    :func:`_count_summaries` so total counts and result rows agree.
    """
    cur = con.cursor()
    params: list[Any] = []
    if not query:
        sql = "SELECT * FROM chat_summary ORDER BY sort_key_ms DESC, session_id ASC"
    else:
        fts_query = _fts_query(query)
        if fts_query and _database_has_fts(con):
            sql = """
                SELECT summary.*
                FROM chat_summary AS summary
                JOIN chat_search_fts
                  ON chat_search_fts.session_id = summary.session_id
                WHERE chat_search_fts MATCH ?
                ORDER BY bm25(chat_search_fts), summary.sort_key_ms DESC, summary.session_id ASC
            """
            params.append(fts_query)
        else:
            sql = """
                SELECT summary.*
                FROM chat_summary AS summary
                JOIN chat_search_text AS search
                  ON search.session_id = summary.session_id
                WHERE lower(search.content) LIKE ?
                ORDER BY summary.sort_key_ms DESC, summary.session_id ASC
            """
            params.append(f"%{query.lower()}%")
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    elif offset:
        sql += " LIMIT -1 OFFSET ?"
        params.append(offset)
    cur.execute(sql, tuple(params))
    return cur.fetchall()


def _database_has_fts(con: sqlite3.Connection) -> bool:
    """True iff the index DB contains the ``chat_search_fts`` virtual table.

    We only create the table when FTS5 is available at build time (see
    :func:`cursor_view.chat_index.schema._create_fts_table`), so this
    check is per-index rather than per-sqlite-installation: an index
    built on an older sqlite is still LIKE-only even after the user
    upgrades.
    """
    cur = con.cursor()
    cur.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type='table' AND name='chat_search_fts'
        """
    )
    return cur.fetchone() is not None


def _summary_row_to_api(row: sqlite3.Row) -> dict[str, Any]:
    """Project a ``chat_summary`` row into the JSON shape the frontend expects."""
    return {
        "project": {
            "name": row["project_name"],
            "rootPath": row["project_root_path"],
        },
        "date": row["date"],
        "session_id": row["session_id"],
        "workspace_id": row["workspace_id"],
        "db_path": row["db_path"],
        "message_count": row["message_count"],
        "preview": row["preview"],
    }
