"""``ChatIndex`` orchestrator: refresh routing, connection lifecycle, public API.

Refresh-routing housekeeping (``_cached_schema_version``, the
synchronous-rebuild branch of :meth:`ChatIndex.ensure_current`, and
the shared :meth:`ChatIndex._run_synchronous_delta_or_rebuild` helper
that the manual-refresh and background-refresh paths both call into)
sets this module's mandatory floor above the 400-line soft limit:
those helpers read ``ChatIndex`` instance state (``_rebuild_build_lock``,
``db_path``, ``_bg_*``) and cannot be extracted to a sibling module
without pulling that state with them. See
:file:`.cursor/rules/chat-index-refresh.mdc`.
"""

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
    _attach_images_to_messages,
    _count_summaries,
    _database_has_fts,
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
            _attach_images_to_messages(
                con, session_id, messages, include_bytes=include_image_bytes
            )
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

        This method is the canonical refresh-routing switch that
        :file:`.cursor/rules/chat-index-refresh.mdc` codifies. There
        are three dispatch arms:

        - **Synchronous delta** (caller blocks while a delta is
          applied): ``force=True`` from the home page Refresh
          button. The work runs through
          :meth:`_run_synchronous_delta_or_rebuild` so the same
          code path that ``_background_refresh_worker`` takes also
          covers manual refreshes, with a full rebuild reserved as
          a correctness fallback.
        - **Synchronous rebuild** (caller blocks until the cache is
          rebuilt from scratch): missing cache file, corrupt
          ``meta`` (``sqlite3.DatabaseError``), or schema-version
          drift. Schema drift blocks instead of SWR-scheduling
          because serving old-shape rows under a new-shape reader
          is a correctness bug, not a freshness one.
        - **Stale-while-revalidate**: a pure source-fingerprint
          miss when the on-disk shapes are still current; handed
          off to :meth:`_schedule_background_refresh` so callers do
          not pay the refresh latency.
        """
        source_fingerprint, sources = self._current_source_fingerprint()

        if force:
            # Cheap fingerprint pre-check avoids the build-lock
            # acquisition for the common "user clicked Refresh but
            # nothing changed source-side" case. A corrupt cache
            # surfaces here as ``DatabaseError`` from the meta-row
            # read inside ``_cached_index_up_to_date``; swallow it
            # and let the helper's rebuild fallback run -- mirrors
            # the unreadable-cache handling on the SWR arm below.
            # The body of the lock re-fingerprints so a racing
            # background worker that finished while we were
            # waiting cannot trick us into writing under a stale
            # fingerprint.
            try:
                if self._cached_index_up_to_date(source_fingerprint):
                    return
            except sqlite3.DatabaseError:
                pass
            with self._rebuild_build_lock:
                fp, srcs = self._current_source_fingerprint()
                self._run_synchronous_delta_or_rebuild(
                    fp, srcs, log_context="on manual refresh"
                )
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
            cached_schema = self._cached_schema_version()
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

        if cached_schema != str(INDEX_SCHEMA_VERSION):
            # Old-shape rows under a new-shape reader are a correctness
            # bug, not a freshness issue, so this branch blocks instead
            # of scheduling SWR like a pure fingerprint miss would.
            logger.info(
                "Chat index schema drift (%s -> %s); rebuilding synchronously",
                cached_schema,
                INDEX_SCHEMA_VERSION,
            )
            with self._rebuild_build_lock:
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

        Holds ``_rebuild_build_lock`` so delta applies and fallback
        rebuilds don't race force-refresh or first-build. Under the
        lock, re-fingerprints the sources (another worker may have
        finished while we were waiting) then defers to
        :meth:`_run_synchronous_delta_or_rebuild` for the same
        delta-with-rebuild-fallback dispatch the manual-refresh
        path uses, so the two refresh entry points cannot drift on
        what counts as a recoverable apply-time failure.
        """
        try:
            with self._rebuild_build_lock:
                fp, sources = self._current_source_fingerprint()
                self._run_synchronous_delta_or_rebuild(
                    fp, sources, log_context="during background refresh"
                )
        except Exception:
            logger.exception("Background chat index refresh failed")
        finally:
            with self._bg_schedule_lock:
                self._bg_refresh_thread = None

    def _run_synchronous_delta_or_rebuild(
        self,
        source_fingerprint: str,
        sources: list[dict[str, Any]],
        *,
        log_context: str,
    ) -> None:
        """Apply a delta under the build lock; fall back to ``_rebuild`` on correctness or apply errors.

        Caller must already hold ``_rebuild_build_lock`` and own the
        decision to refresh (the up-to-date fast path lives on the
        caller side so this helper can be reused from contexts that
        intentionally re-run after waiting on the lock).

        The fallback path covers four signals, each of which rules
        out the delta path on its own:

        - the cache file vanished after the lock was taken (a user
          deleted ``chat-index.sqlite3`` mid-refresh);
        - the cache's ``meta`` table is unreadable
          (``sqlite3.DatabaseError``);
        - ``schema_version`` does not match
          ``INDEX_SCHEMA_VERSION`` (shape drift);
        - ``compute_source_diff`` or ``apply_delta`` raises a
          ``sqlite3.DatabaseError`` while running the diff or the
          single-transaction apply.

        ``log_context`` is interpolated into the unreadability
        warning so manual-refresh and background-refresh log lines
        stay distinguishable even though the routing logic is
        shared.
        """
        if not self.db_path.exists():
            # apply_delta needs an existing cache to write into;
            # treat a missing file like the dedicated missing-cache
            # branch in ``ensure_current`` does for the non-force
            # flow and rebuild from scratch.
            self._rebuild(source_fingerprint, sources)
            return
        # Both ``_cached_index_up_to_date`` and ``_read_meta_value``
        # open the cache to read the ``meta`` table, so a corrupt
        # cache surfaces as ``DatabaseError`` from either call. Wrap
        # them together so the rebuild fallback covers both, matching
        # the pre-refactor ``_background_refresh_worker`` contract
        # (the synchronous-rebuild routing in ``ensure_current``
        # owns the same defense for the non-force arms).
        try:
            if self._cached_index_up_to_date(source_fingerprint):
                return
            cached_schema = self._read_meta_value("schema_version")
        except sqlite3.DatabaseError:
            logger.warning(
                "Existing chat index is unreadable %s; rebuilding", log_context
            )
            self._rebuild(source_fingerprint, sources)
            return
        if cached_schema != str(INDEX_SCHEMA_VERSION):
            # Primary schema-drift handling for the non-force flow
            # already lives on the synchronous arm of
            # ``ensure_current``. This branch is the defense-in-depth
            # arm for the rare case where a background refresh was
            # already queued on a fingerprint miss and then raced a
            # schema bump landing before the worker took the lock,
            # plus the manual-refresh path's correctness gate.
            logger.info(
                "Chat index schema drift (%s -> %s); falling back to full rebuild",
                cached_schema,
                INDEX_SCHEMA_VERSION,
            )
            self._rebuild(source_fingerprint, sources)
            return
        try:
            dirty = self._compute_source_diff(sources)
            self._apply_delta(dirty, source_fingerprint, sources)
        except sqlite3.DatabaseError:
            logger.warning(
                "Incremental chat-index refresh failed; falling back to full rebuild",
                exc_info=True,
            )
            self._rebuild(source_fingerprint, sources)

    def _cached_index_up_to_date(self, source_fingerprint: str) -> bool:
        """True iff the on-disk index matches the current source fingerprint and schema version."""
        if not self.db_path.exists():
            return False
        cached_fingerprint = self._read_meta_value("source_fingerprint")
        cached_version = self._cached_schema_version()
        return (
            cached_fingerprint == source_fingerprint
            and cached_version == str(INDEX_SCHEMA_VERSION)
        )

    def _cached_schema_version(self) -> str | None:
        """Return the cache's ``schema_version`` meta row value, or None if absent.

        Split out from :meth:`_cached_index_up_to_date` so the refresh
        router can distinguish a schema bump (synchronous rebuild --
        serving old-shape rows to callers expecting the new shape is a
        data-correctness bug) from a pure source-fingerprint miss (safe
        to serve stale under stale-while-revalidate). Raises
        :class:`sqlite3.DatabaseError` on corrupt cache so the caller
        can unify corrupt-cache handling with schema-drift handling.
        """
        if not self.db_path.exists():
            return None
        return self._read_meta_value("schema_version")

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
