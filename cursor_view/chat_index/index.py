"""``ChatIndex`` orchestrator: refresh routing, connection lifecycle, public API."""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from cursor_view.cache import (
    DirtySet,
    apply_delta,
    compute_source_diff,
)
from cursor_view.chat_index.fingerprint import _current_source_fingerprint
from cursor_view.chat_index.rebuild import _rebuild
from cursor_view.chat_index.rows import (
    _count_summaries,
    _database_has_fts,
    _fetch_images_for_session,
    _fetch_summaries,
    _insert_chat,
    _summary_row_to_api,
)
from cursor_view.chat_index.schema import INDEX_SCHEMA_VERSION
from cursor_view.paths import cursor_view_cache_dir

logger = logging.getLogger(__name__)

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


class ChatIndex:
    """Persistent SQLite-backed cache of summaries, detail rows, and search."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (cursor_view_cache_dir() / "chat-index.sqlite3")
        # Serialize write attempts (sync force, first build, corrupt recovery,
        # background delta refresh, background fallback rebuild).
        self._rebuild_build_lock = threading.Lock()
        # Single-flight background refresh after stale-while-revalidate scheduling.
        self._bg_schedule_lock = threading.Lock()
        self._bg_refresh_thread: threading.Thread | None = None
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
            total = _count_summaries(con, normalized_query)
            items = _fetch_summaries(con, normalized_query, limit, offset)
        return {
            "items": [_summary_row_to_api(row) for row in items],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": limit is not None and (offset + len(items)) < total,
            "query": normalized_query,
        }

    def get_chat(
        self,
        session_id: str,
        force_refresh: bool = False,
        include_image_bytes: bool = False,
    ) -> dict[str, Any] | None:
        """Return a full chat detail object for one session id.

        ``include_image_bytes`` defaults False (bytes flow through
        ``/api/chat/<id>/image/<uuid>``); exports flip it True so
        renderers can inline base64 data URIs.
        """
        self.ensure_current(force=force_refresh)
        with self._connect(read_only=True) as con:
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            cur.execute("SELECT * FROM chat_summary WHERE session_id=?", (session_id,))
            summary = cur.fetchone()
            if not summary:
                return None
            cur.execute(
                "SELECT role, content FROM chat_message "
                "WHERE session_id=? ORDER BY position ASC",
                (session_id,),
            )
            messages = [
                {"role": row["role"], "content": row["content"], "images": []}
                for row in cur.fetchall()
            ]
            image_rows = _fetch_images_for_session(
                con, session_id, include_bytes=include_image_bytes
            )
        # Bucket each image into its owning message by ``position``;
        # ``image_index`` served its ordering job upstream, so both
        # storage-layer keys come off before hitting the wire.
        for image in image_rows:
            position = image.pop("position")
            image.pop("image_index", None)
            if 0 <= position < len(messages):
                messages[position]["images"].append(image)
        detail = _summary_row_to_api(summary)
        detail["messages"] = messages
        return detail

    def get_image(
        self, session_id: str, image_uuid: str
    ) -> tuple[bytes, str] | None:
        """Return ``(raw_bytes, mime_type)`` for one attached image.

        Bypasses the chat-detail payload so ``GET /api/chat/<id>``
        stays small for chats with megabytes of images. ``LIMIT 1``
        is intentional: a uuid can appear on multiple turns with
        identical bytes (see ``chat_image`` DDL comment).
        """
        self.ensure_current(force=False)
        with self._connect(read_only=True) as con:
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            cur.execute(
                "SELECT mime_type, data FROM chat_image "
                "WHERE session_id = ? AND uuid = ? LIMIT 1",
                (session_id, image_uuid),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return bytes(row["data"]), row["mime_type"]

    def ensure_current(self, force: bool = False) -> None:
        """Refresh the index if source DBs changed or a rebuild was requested.

        Routing matches section 3.1 of the incremental-refresh plan:

        - ``force=True`` always triggers a synchronous full rebuild;
          there is no delta equivalent because the UI uses this entry
          point to reset suspected-bad cache state.
        - A missing cache file is a first-build and likewise rebuilds
          synchronously; the delta path needs a populated
          ``source_row`` / ``composer_state`` baseline to be useful.
        - A readable cache whose ``meta`` answers the fast
          fingerprint check is a pure cache hit; no work scheduled.
        - A cache that raises :class:`sqlite3.DatabaseError` while
          we're reading its meta is corrupt and rebuilt synchronously
          under the lock.
        - Anything else (schema drift, fingerprint mismatch) is a
          stale-but-readable cache; the current snapshot is served
          immediately while
          :meth:`_schedule_background_refresh` dispatches the
          incremental apply (or a full rebuild when the schema
          differs) off the request path.
        """
        source_fingerprint, sources = self._current_source_fingerprint()

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

        self._schedule_background_refresh()

    def _schedule_background_refresh(self) -> None:
        """Start at most one daemon thread to refresh the index (stale-while-revalidate).

        The worker thread decides between the incremental delta path
        and the full-rebuild fallback based on the cache's schema
        version; this scheduling helper only arbitrates single-flight
        dispatch so a burst of stale reads doesn't spawn N workers.
        """
        with self._bg_schedule_lock:
            if self._bg_refresh_thread is not None and self._bg_refresh_thread.is_alive():
                return
            logger.info("Scheduling background chat index refresh")
            self._bg_refresh_thread = threading.Thread(
                target=self._background_refresh_worker,
                name="chat-index-refresh",
                daemon=True,
            )
            self._bg_refresh_thread.start()

    def _background_refresh_worker(self) -> None:
        """Run a stale-while-revalidate refresh, releasing the schedule slot on exit.

        Acquires ``_rebuild_build_lock`` so delta applies and fallback
        rebuilds don't race against a synchronous force-refresh or
        first-build. Under the lock:

        1. Re-fingerprint the sources; another thread may have
           completed the refresh while we were waiting, turning this
           worker into a no-op.
        2. Read the cache's ``schema_version``. Anything that throws
           :class:`sqlite3.DatabaseError` or that doesn't match the
           current :data:`INDEX_SCHEMA_VERSION` falls through to a
           full rebuild; the delta path requires the v2 tables to be
           present and consistent.
        3. Otherwise run the row-hash diff and apply it. If the
           apply transaction fails with a SQLite error (corruption,
           schema surprise, etc.), log and fall back to a full
           rebuild so the cache is never left in a broken state.
        """
        try:
            with self._rebuild_build_lock:
                fp, sources = self._current_source_fingerprint()
                try:
                    if self._cached_index_up_to_date(fp):
                        return
                    cached_schema = self._read_meta_value("schema_version")
                except sqlite3.DatabaseError:
                    logger.warning(
                        "Existing chat index is unreadable during background refresh; rebuilding"
                    )
                    self._rebuild(fp, sources)
                    return
                if cached_schema != str(INDEX_SCHEMA_VERSION):
                    logger.info(
                        "Chat index schema drift (%s -> %s); falling back to full rebuild",
                        cached_schema,
                        INDEX_SCHEMA_VERSION,
                    )
                    self._rebuild(fp, sources)
                    return
                try:
                    dirty = self._compute_source_diff(sources)
                    self._apply_delta(dirty, fp, sources)
                except sqlite3.DatabaseError:
                    logger.warning(
                        "Incremental chat-index refresh failed; falling back to full rebuild",
                        exc_info=True,
                    )
                    self._rebuild(fp, sources)
        except Exception:
            logger.exception("Background chat index refresh failed")
        finally:
            with self._bg_schedule_lock:
                self._bg_refresh_thread = None

    def _cached_index_up_to_date(self, source_fingerprint: str) -> bool:
        """True iff the on-disk index matches the current source fingerprint and schema version."""
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
        """Apply the connection-level PRAGMAs we want on writable connections."""
        cur = con.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.close()

    def _read_meta_value(self, key: str) -> str | None:
        """Return the ``value`` column for a row in the ``meta`` table, or None."""
        with self._connect(read_only=True) as con:
            cur = con.cursor()
            cur.execute("SELECT value FROM meta WHERE key=?", (key,))
            row = cur.fetchone()
        return row[0] if row else None

    def _current_source_fingerprint(self) -> tuple[str, list[dict[str, Any]]]:
        """Thin wrapper over the module-level fingerprint helper (kept as a method for tests)."""
        return _current_source_fingerprint()

    def _rebuild(self, source_fingerprint: str, sources: list[dict[str, Any]]) -> None:
        """Dispatch the full rebuild path (build to temp, then atomic swap)."""
        _rebuild(self, source_fingerprint, sources)

    def _insert_chat(
        self, cur: sqlite3.Cursor, chat: dict[str, Any], fts_enabled: bool
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Forward to :func:`cursor_view.chat_index.rows._insert_chat`.

        Retained as a method so the apply-delta hook protocol
        (``insert_chat=self._insert_chat``) stays intact; the returned
        ``(formatted_chat, coalesced_messages)`` pair lets the apply
        path reuse the formatted result instead of re-running
        ``format_chat_for_frontend`` + ``coalesce_consecutive_messages_by_role``.
        """
        return _insert_chat(cur, chat, fts_enabled)

    def _database_has_fts(self, con: sqlite3.Connection) -> bool:
        """Forward to :func:`cursor_view.chat_index.rows._database_has_fts`."""
        return _database_has_fts(con)

    def _apply_delta(
        self,
        dirty: DirtySet,
        source_fingerprint: str,
        sources: list[dict[str, Any]],
    ) -> None:
        """Apply an incremental :class:`DirtySet` to the live cache.

        Thin adapter over :func:`cursor_view.cache.apply_delta` that
        owns the writable connection (so the caller does not have to
        reach into private ``_connect`` internals) and forwards the
        cache's ``_insert_chat`` / ``_database_has_fts`` hooks so the
        apply step reuses the exact row-shaping logic the full rebuild
        uses. Concurrency is the caller's responsibility:
        ``ensure_current`` wraps every invocation of this method in
        ``_rebuild_build_lock`` to keep the apply path single-writer
        just like ``_rebuild``.
        """
        with self._connect(read_only=False) as con:
            apply_delta(
                con,
                dirty,
                source_fingerprint,
                sources,
                insert_chat=self._insert_chat,
                database_has_fts=self._database_has_fts,
            )

    def _compute_source_diff(self, sources: list[dict[str, Any]]) -> DirtySet:
        """Produce the :class:`DirtySet` :meth:`_apply_delta` consumes.

        Delegates to :func:`cursor_view.cache.compute_source_diff`
        using a short-lived read-only connection to the live cache.
        Kept as a method (rather than inlined at the single call site
        :meth:`ensure_current` will grow) so tests can stub it out
        without monkey-patching a free function on the cache package.
        """
        with self._connect(read_only=True) as con:
            return compute_source_diff(sources, con)
