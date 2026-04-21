"""Row-shaping helpers shared by the full rebuild and incremental apply paths."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from cursor_view.chat_format import (
    coalesce_consecutive_messages_by_role,
    format_chat_for_frontend,
)
from cursor_view.timestamps import session_sort_key_ms


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


def _insert_chat(cur: sqlite3.Cursor, chat: dict[str, Any], fts_enabled: bool) -> None:
    """Write one chat into the content tables of the cache.

    Used by both the full rebuild and the incremental apply path.
    The caller is responsible for having already cleared any prior
    rows for ``session_id`` from the content tables (the full
    rebuild runs against a fresh temp DB; the incremental apply
    runs :func:`cursor_view.cache.apply_delta._delete_cid_rows`
    first). This method therefore always re-numbers ``position``
    from ``0`` using :func:`enumerate` on the coalesced messages
    list; ``position`` is a per-refresh local index, NOT a globally
    stable identifier. Callers that need a stable per-message id
    should use ``(session_id, position)`` pairs read back after
    the most recent refresh.

    ``_insert_chat`` relies on ``formatted["messages"]`` already
    being in the correct chronological order produced by
    :func:`cursor_view.extraction.extract_chats`; it does no
    sorting of its own and trusts the upstream pipeline, so the
    bubble-order fix lives there rather than here.
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
    cur.execute(
        "INSERT INTO chat_search_text(session_id, content) VALUES(?, ?)",
        (session_id, search_blob),
    )
    if fts_enabled:
        cur.execute(
            "INSERT INTO chat_search_fts(session_id, content) VALUES(?, ?)",
            (session_id, search_blob),
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
