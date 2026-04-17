"""Persistent cached chat index used by the API."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from cursor_view.chat_format import (
    coalesce_consecutive_messages_by_role,
    format_chat_for_frontend,
)
from cursor_view.extraction import extract_chats
from cursor_view.paths import (
    cursor_root,
    cursor_view_cache_dir,
    global_storage_path,
    workspaces,
)
from cursor_view.timestamps import session_sort_key_ms

logger = logging.getLogger(__name__)

INDEX_SCHEMA_VERSION = 1

_INDEX_SINGLETON: "ChatIndex | None" = None
_INDEX_SINGLETON_LOCK = threading.Lock()


def get_chat_index() -> "ChatIndex":
    """Return the shared process-wide chat index instance."""
    global _INDEX_SINGLETON
    if _INDEX_SINGLETON is None:
        with _INDEX_SINGLETON_LOCK:
            if _INDEX_SINGLETON is None:
                _INDEX_SINGLETON = ChatIndex()
    return _INDEX_SINGLETON


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


class ChatIndex:
    """Persistent SQLite-backed cache of summaries, detail rows, and search."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (cursor_view_cache_dir() / "chat-index.sqlite3")
        # Serialize rebuild attempts (sync force, first build, corrupt recovery, background worker).
        self._rebuild_build_lock = threading.Lock()
        # Single-flight background rebuild after stale-while-revalidate scheduling.
        self._bg_schedule_lock = threading.Lock()
        self._bg_rebuild_thread: threading.Thread | None = None
        # Coordinate swap (replace) vs readers of self.db_path (Windows cannot replace an open file).
        self._swap_cv = threading.Condition(threading.Lock())
        self._active_readers = 0
        self._swap_pending = False

    def list_summaries(
        self,
        query: str = "",
        limit: int | None = None,
        offset: int = 0,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return summary rows plus pagination metadata."""
        self.ensure_current(force=force_refresh)
        normalized_query = (query or "").strip()
        with self._connect(read_only=True) as con:
            con.row_factory = sqlite3.Row
            total = self._count_summaries(con, normalized_query)
            items = self._fetch_summaries(con, normalized_query, limit, offset)
        return {
            "items": [self._summary_row_to_api(row) for row in items],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": limit is not None and (offset + len(items)) < total,
            "query": normalized_query,
        }

    def get_chat(self, session_id: str, force_refresh: bool = False) -> dict[str, Any] | None:
        """Return a full chat detail object for one session id."""
        self.ensure_current(force=force_refresh)
        with self._connect(read_only=True) as con:
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            cur.execute("SELECT * FROM chat_summary WHERE session_id=?", (session_id,))
            summary = cur.fetchone()
            if not summary:
                return None
            cur.execute(
                """
                SELECT role, content
                FROM chat_message
                WHERE session_id=?
                ORDER BY position ASC
                """,
                (session_id,),
            )
            messages = [
                {"role": row["role"], "content": row["content"]}
                for row in cur.fetchall()
            ]
        detail = self._summary_row_to_api(summary)
        detail["messages"] = messages
        return detail

    def ensure_current(self, force: bool = False) -> None:
        """Rebuild the index if source DBs changed or refresh was requested."""
        source_fingerprint, sources = self._current_source_fingerprint()

        if not force and self.db_path.exists():
            try:
                if self._cached_index_up_to_date(source_fingerprint):
                    return
            except sqlite3.DatabaseError:
                logger.warning("Existing chat index is unreadable; rebuilding")
                with self._rebuild_build_lock:
                    if self.db_path.exists():
                        try:
                            if self._cached_index_up_to_date(source_fingerprint):
                                return
                        except sqlite3.DatabaseError:
                            pass
                    self._rebuild(source_fingerprint, sources)
                return

        if force:
            with self._rebuild_build_lock:
                self._rebuild(source_fingerprint, sources)
            return

        if not self.db_path.exists():
            with self._rebuild_build_lock:
                if self.db_path.exists():
                    try:
                        if self._cached_index_up_to_date(source_fingerprint):
                            return
                    except sqlite3.DatabaseError:
                        pass
                self._rebuild(source_fingerprint, sources)
            return

        # Stale but readable index: serve current snapshot; refresh in background.
        self._schedule_background_rebuild()
        return

    def _schedule_background_rebuild(self) -> None:
        """Start at most one daemon thread to rebuild the index (stale-while-revalidate)."""
        with self._bg_schedule_lock:
            if self._bg_rebuild_thread is not None and self._bg_rebuild_thread.is_alive():
                return
            logger.info("Scheduling background chat index rebuild")
            self._bg_rebuild_thread = threading.Thread(
                target=self._background_rebuild_worker,
                name="chat-index-rebuild",
                daemon=True,
            )
            self._bg_rebuild_thread.start()

    def _background_rebuild_worker(self) -> None:
        try:
            with self._rebuild_build_lock:
                fp, sources = self._current_source_fingerprint()
                if self._cached_index_up_to_date(fp):
                    return
                self._rebuild(fp, sources)
        except Exception:
            logger.exception("Background chat index rebuild failed")
        finally:
            with self._bg_schedule_lock:
                self._bg_rebuild_thread = None

    def _cached_index_up_to_date(self, source_fingerprint: str) -> bool:
        if not self.db_path.exists():
            return False
        cached_fingerprint = self._read_meta_value("source_fingerprint")
        cached_version = self._read_meta_value("schema_version")
        return (
            cached_fingerprint == source_fingerprint
            and cached_version == str(INDEX_SCHEMA_VERSION)
        )

    @contextmanager
    def _cache_read_guard(self) -> Iterator[None]:
        with self._swap_cv:
            while self._swap_pending:
                self._swap_cv.wait()
            self._active_readers += 1
        try:
            yield
        finally:
            with self._swap_cv:
                self._active_readers -= 1
                self._swap_cv.notify_all()

    @contextmanager
    def _connect(self, read_only: bool = False) -> Iterator[sqlite3.Connection]:
        if read_only:
            with self._cache_read_guard():
                con = sqlite3.connect(
                    f"file:{self.db_path}?mode=ro",
                    uri=True,
                    check_same_thread=False,
                )
                try:
                    yield con
                finally:
                    con.close()
        else:
            con = sqlite3.connect(self.db_path, check_same_thread=False)
            self._configure_connection(con)
            try:
                yield con
            finally:
                con.close()

    def _configure_connection(self, con: sqlite3.Connection) -> None:
        cur = con.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.close()

    def _read_meta_value(self, key: str) -> str | None:
        with self._connect(read_only=True) as con:
            cur = con.cursor()
            cur.execute("SELECT value FROM meta WHERE key=?", (key,))
            row = cur.fetchone()
        return row[0] if row else None

    def _current_source_fingerprint(self) -> tuple[str, list[dict[str, Any]]]:
        root = cursor_root()
        sources: list[dict[str, Any]] = []
        global_db = global_storage_path(root)
        if global_db and global_db.exists():
            sources.append(self._source_entry("(global)", global_db))
        for ws_id, db in workspaces(root) or []:
            if db.exists():
                sources.append(self._source_entry(ws_id, db))
        sources.sort(key=lambda item: item["workspace_id"])
        raw = json.dumps(
            {
                "schema_version": INDEX_SCHEMA_VERSION,
                "sources": sources,
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest(), sources

    def _source_entry(self, workspace_id: str, path: Path) -> dict[str, Any]:
        stat = path.stat()
        entry: dict[str, Any] = {
            "workspace_id": workspace_id,
            "path": str(path),
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
        }
        # SQLite WAL holds recent commits before the main file is checkpointed; include it
        # in the fingerprint so the index invalidates when only the WAL changes.
        wal_path = path.with_name(path.name + "-wal")
        if wal_path.exists():
            wst = wal_path.stat()
            entry["wal_mtime_ns"] = wst.st_mtime_ns
            entry["wal_size"] = wst.st_size
        return entry

    def _rebuild(self, source_fingerprint: str, sources: list[dict[str, Any]]) -> None:
        logger.info("Rebuilding chat index at %s", self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.db_path.parent / f"{self.db_path.stem}.{uuid.uuid4().hex}.tmp"
        try:
            self._build_index_to_temp(temp_path, source_fingerprint, sources)
            self._swap_temp_into_place(temp_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

    def _build_index_to_temp(
        self,
        temp_path: Path,
        source_fingerprint: str,
        sources: list[dict[str, Any]],
    ) -> None:
        """Phase A: populate a new index file; does not touch self.db_path."""
        if temp_path.exists():
            temp_path.unlink()
        con = sqlite3.connect(temp_path, check_same_thread=False)
        try:
            self._configure_connection(con)
            self._create_schema(con)
            cur = con.cursor()
            fts_enabled = self._create_fts_table(cur)
            chats = extract_chats()
            for chat in chats:
                self._insert_chat(cur, chat, fts_enabled)
            now = str(int(time.time()))
            meta_rows = [
                ("schema_version", str(INDEX_SCHEMA_VERSION)),
                ("source_fingerprint", source_fingerprint),
                ("source_manifest", json.dumps(sources, sort_keys=True)),
                ("built_at", now),
                ("chat_count", str(len(chats))),
            ]
            cur.executemany("INSERT INTO meta(key, value) VALUES(?, ?)", meta_rows)
            con.commit()
        except Exception:
            con.close()
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise
        else:
            con.close()

    def _swap_temp_into_place(self, temp_path: Path) -> None:
        """Phase B: atomically replace the live index; waits for readers to release the file."""
        with self._swap_cv:
            self._swap_pending = True
            while self._active_readers > 0:
                self._swap_cv.wait()
            try:
                temp_path.replace(self.db_path)
            finally:
                self._swap_pending = False
                self._swap_cv.notify_all()

    def _create_schema(self, con: sqlite3.Connection) -> None:
        cur = con.cursor()
        cur.executescript(
            """
            CREATE TABLE meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE chat_summary (
                session_id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                project_root_path TEXT NOT NULL,
                date INTEGER,
                workspace_id TEXT NOT NULL,
                db_path TEXT NOT NULL,
                message_count INTEGER NOT NULL,
                preview TEXT NOT NULL,
                sort_key_ms INTEGER NOT NULL
            );

            CREATE TABLE chat_message (
                session_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                PRIMARY KEY (session_id, position)
            );

            CREATE TABLE chat_search_text (
                session_id TEXT PRIMARY KEY,
                content TEXT NOT NULL
            );

            CREATE INDEX idx_chat_summary_sort
            ON chat_summary(sort_key_ms DESC, session_id);

            CREATE INDEX idx_chat_message_session
            ON chat_message(session_id, position);
            """
        )
        cur.close()

    def _create_fts_table(self, cur: sqlite3.Cursor) -> bool:
        try:
            cur.execute(
                """
                CREATE VIRTUAL TABLE chat_search_fts
                USING fts5(session_id UNINDEXED, content)
                """
            )
            return True
        except sqlite3.DatabaseError as exc:
            logger.warning("FTS5 unavailable, falling back to LIKE search: %s", exc)
            return False

    def _insert_chat(self, cur: sqlite3.Cursor, chat: dict[str, Any], fts_enabled: bool) -> None:
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

    def _count_summaries(self, con: sqlite3.Connection, query: str) -> int:
        cur = con.cursor()
        if not query:
            cur.execute("SELECT COUNT(*) FROM chat_summary")
            row = cur.fetchone()
            return int(row[0] if row else 0)
        fts_query = _fts_query(query)
        if fts_query and self._database_has_fts(con):
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
        self,
        con: sqlite3.Connection,
        query: str,
        limit: int | None,
        offset: int,
    ) -> list[sqlite3.Row]:
        cur = con.cursor()
        params: list[Any] = []
        if not query:
            sql = "SELECT * FROM chat_summary ORDER BY sort_key_ms DESC, session_id ASC"
        else:
            fts_query = _fts_query(query)
            if fts_query and self._database_has_fts(con):
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

    def _database_has_fts(self, con: sqlite3.Connection) -> bool:
        cur = con.cursor()
        cur.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type='table' AND name='chat_search_fts'
            """
        )
        return cur.fetchone() is not None

    def _summary_row_to_api(self, row: sqlite3.Row) -> dict[str, Any]:
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
