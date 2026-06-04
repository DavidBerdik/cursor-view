"""Regression coverage for the retired known-bug fixes.

The bugs the original fix-pass retired (and the contracts these tests pin):

- ``cursor_view/chat_format.py::format_chat_for_frontend`` no longer
  swallows formatting exceptions and returns a stub with a fresh
  ``uuid.uuid4()`` session id. Errors propagate, and the per-chat
  insert loops in ``cursor_view/chat_index/rebuild.py`` and
  ``cursor_view/cache/delta/engine.py`` are the new skip-with-log
  boundary. Tests one and two below pin both halves: a malformed chat
  must produce **zero** ``chat_summary`` rows (no synthetic-UUID ghost)
  on full rebuild and on incremental apply, and the surviving chats
  must land normally.
- ``cursor_view/sources/item_table.py::iter_global_legacy_chatdata``
  no longer leaks the SQLite connection on the error path. Test three
  drives the iterator against a DB with no ``ItemTable`` (so ``j()``
  raises ``sqlite3.OperationalError``, a ``DatabaseError`` subclass,
  and the inner ``except`` triggers) and asserts the connection captured
  during the call is closed by the time the iterator returns.

The ``terminal.py`` import-time-side-effects fix is the fourth bug
in the pass; verifying it would require asserting that
``cleanup_orphan_temp_files`` and ``create_app`` are NOT called
during ``import cursor_view.terminal``. That is awkward to test in
isolation (any prior import of the module under another test would
already have paid the cost) and the structural change -- moving both
calls inside ``run_server`` -- is verifiable by reading the module.
Skipping a dedicated test for that one is consistent with how
``cursor_view/desktop/__init__.py`` tests the same pattern (it
doesn't).

A fourth test, ``ExtractProjectFromGitReposClosesConnectionTest``, was
added by the Improvement 20 project-wide bug sweep for a sibling
connection leak in ``cursor_view/projects/git.py`` (same shape as the
``iter_global_legacy_chatdata`` leak: connect inside ``try``, broad
``except`` returning without ``close()``), fixed in place with the
``con = None`` + ``finally`` cleanup pattern.
"""

from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import cursor_view.chat_index.rows as rows_module
from cursor_view.chat_format import format_chat_for_frontend as _real_format
from cursor_view.projects.git import extract_project_from_git_repos
from cursor_view.sources.item_table import iter_global_legacy_chatdata

from tests._image_test_helpers import (
    BaseChatIndexImageTest,
    _composer,
    _put_kv,
)


def _bubble(text: str, role_type: int = 1) -> dict:
    """Minimal user / assistant bubble matching the helper in ``test_chat_index_titles``."""
    return {"type": role_type, "text": text}


class MalformedChatSkippedTest(BaseChatIndexImageTest):
    """A chat whose formatting raises must be skipped, not stubbed."""

    BAD_CID = "11111111-1111-1111-1111-111111111111"
    GOOD_CID = "22222222-2222-2222-2222-222222222222"

    def _seed_two_chats(self) -> None:
        for cid, bubble_text in (
            (self.BAD_CID, "this chat will fail to format"),
            (self.GOOD_CID, "this chat will succeed"),
        ):
            _put_kv(
                self.global_db,
                f"composerData:{cid}",
                _composer("name-" + cid[:4], headers=[("b1", 1)]),
            )
            _put_kv(
                self.global_db,
                f"bubbleId:{cid}:b1",
                _bubble(bubble_text),
            )

    def _format_with_bad_cid_raising(self, chat):
        """Stand-in for ``format_chat_for_frontend`` that raises only for ``BAD_CID``.

        The rebuild and apply paths reach this through the rebound
        symbol in ``cursor_view.chat_index.rows``; routing the raise
        through this side_effect mirrors a real-world malformed-chat
        ValueError without engineering a malformed source row.
        """
        cid = (chat.get("session") or {}).get("composerId")
        if cid == self.BAD_CID:
            raise ValueError("synthetic format failure for regression test")
        return _real_format(chat)

    def _summary_session_ids(self) -> set[str]:
        con = sqlite3.connect(self.cache_path)
        try:
            cur = con.cursor()
            cur.execute("SELECT session_id FROM chat_summary")
            return {row[0] for row in cur.fetchall()}
        finally:
            con.close()

    def test_rebuild_skips_malformed_chat(self) -> None:
        """Full rebuild logs and skips the bad chat; the good chat lands normally.

        Pins the post-fix invariant: the cache must contain zero rows
        for ``BAD_CID`` (no synthetic-UUID ghost row, no ``Error`` /
        ``error`` workspace stub) and a normal row for ``GOOD_CID``.
        """
        self._seed_two_chats()

        with patch.object(
            rows_module,
            "format_chat_for_frontend",
            side_effect=self._format_with_bad_cid_raising,
        ):
            with self.assertLogs("cursor_view.chat_index.rebuild", level="ERROR") as logs:
                self._build_index()

        ids = self._summary_session_ids()
        self.assertNotIn(self.BAD_CID, ids, "malformed chat must not appear in chat_summary")
        self.assertIn(self.GOOD_CID, ids, "well-formed sibling chat must still land")

        self.assertTrue(
            any(self.BAD_CID in record.getMessage() for record in logs.records),
            "the skip-with-log boundary must name the offending cid",
        )

        # Defensive check: no synthetic-UUID ghost rows. Every
        # session_id in chat_summary must correspond to a cid the
        # extraction pipeline actually produced.
        for sid in ids:
            self.assertNotEqual(sid, self.BAD_CID)

    def test_incremental_apply_skips_malformed_chat(self) -> None:
        """The same skip-with-log discipline holds on the incremental apply path.

        Builds the cache without the patch (so both chats land
        cleanly), then dirties both via a name rename and refreshes
        with the patch active. ``BAD_CID`` must drop out of the
        cache because ``_delete_cid_rows`` already cleared its prior
        row before the failing insert; ``GOOD_CID`` must keep
        round-tripping.
        """
        self._seed_two_chats()
        ci = self._build_index()
        self.assertEqual(self._summary_session_ids(), {self.BAD_CID, self.GOOD_CID})

        for cid in (self.BAD_CID, self.GOOD_CID):
            _put_kv(
                self.global_db,
                f"composerData:{cid}",
                _composer("renamed-" + cid[:4], headers=[("b1", 1)]),
            )

        with patch.object(
            rows_module,
            "format_chat_for_frontend",
            side_effect=self._format_with_bad_cid_raising,
        ):
            # The skip-with-log boundary lives in
            # ``cursor_view/cache/delta/composer_rows.py::_apply_chat_writes``
            # (shared by the primary and secondary apply phases), so the
            # log line fires under that module's logger after the
            # apply-time-propagation-gate split lifted the helper out of
            # ``cache/delta/engine.py``.
            with self.assertLogs(
                "cursor_view.cache.delta.composer_rows", level="ERROR"
            ) as logs:
                self._refresh(ci)

        ids = self._summary_session_ids()
        self.assertNotIn(
            self.BAD_CID, ids,
            "incremental apply must drop the cid whose re-format raised; the prior row "
            "was already deleted before the failing insert, so leaving nothing is "
            "the correct (and consistent) outcome",
        )
        self.assertIn(self.GOOD_CID, ids)

        self.assertTrue(
            any(self.BAD_CID in record.getMessage() for record in logs.records),
            "the apply-loop skip log must name the offending cid",
        )


class IterGlobalLegacyChatdataClosesConnectionTest(unittest.TestCase):
    """``iter_global_legacy_chatdata`` must release the SQLite connection on every exit.

    Pre-fix, ``con = sqlite3.connect(...)`` lived inside the ``try`` block
    and the broad ``except Exception`` skipped ``con.close()``, so any
    error after open leaked the file handle. Post-fix the body runs
    inside ``with closing(con)``, so even a ``DatabaseError`` from
    ``j()`` releases the connection. This test drives the error path
    by pointing the iterator at a DB that has the file shape but
    lacks the ``ItemTable`` -- ``j()``'s
    ``SELECT value FROM ItemTable`` raises ``sqlite3.OperationalError``,
    and we assert the captured connection is closed afterward.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cursor-view-itemtable-")
        self.db_path = pathlib.Path(self._tmp) / "state.vscdb"
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("CREATE TABLE someothertable (key TEXT, value TEXT)")
            con.commit()
        finally:
            con.close()

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_connection_closed_on_missing_itemtable(self) -> None:
        captured: list[sqlite3.Connection] = []

        real_connect = sqlite3.connect

        def tracking_connect(*args, **kwargs):
            con = real_connect(*args, **kwargs)
            captured.append(con)
            return con

        with patch("cursor_view.sources.item_table.sqlite3.connect", side_effect=tracking_connect):
            list(iter_global_legacy_chatdata(self.db_path))

        self.assertEqual(
            len(captured), 1,
            "iter_global_legacy_chatdata should open exactly one connection",
        )
        with self.assertRaises(sqlite3.ProgrammingError):
            captured[0].execute("SELECT 1")


class ExtractProjectFromGitReposClosesConnectionTest(unittest.TestCase):
    """``extract_project_from_git_repos`` must release the SQLite connection on the error path.

    Found by the Improvement 20 project-wide bug sweep. Pre-fix,
    ``con = sqlite3.connect(...)`` was opened inside the ``try`` and the
    broad ``except Exception`` returned ``None`` without closing it, so any
    failure after open leaked the read-only handle -- the same shape as the
    retired ``iter_global_legacy_chatdata`` leak. This test drives the error
    path by pointing the function at a workspace DB that has the file shape
    but no ``ItemTable``, so ``j()``'s ``SELECT value FROM ItemTable`` raises
    ``sqlite3.OperationalError`` (a ``DatabaseError`` subclass) inside the
    ``try``; the captured connection must be closed by the time the function
    returns ``None``. Post-fix the connection is initialized to ``None`` and
    closed in a ``finally`` (the ``projects/inference.py`` cleanup pattern).
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cursor-view-gitrepos-")
        self._base = pathlib.Path(self._tmp)
        self.workspace_id = "ws-conn-leak-test"
        ws_dir = self._base / "User" / "workspaceStorage" / self.workspace_id
        ws_dir.mkdir(parents=True)
        db_path = ws_dir / "state.vscdb"
        con = sqlite3.connect(db_path)
        try:
            con.execute("CREATE TABLE someothertable (key TEXT, value TEXT)")
            con.commit()
        finally:
            con.close()
        # The function is lru_cached; clear so a prior run's result for this
        # workspace id cannot short-circuit the connect-and-fail path.
        extract_project_from_git_repos.cache_clear()

    def tearDown(self) -> None:
        import shutil

        extract_project_from_git_repos.cache_clear()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_connection_closed_on_missing_itemtable(self) -> None:
        captured: list[sqlite3.Connection] = []

        real_connect = sqlite3.connect

        def tracking_connect(*args, **kwargs):
            con = real_connect(*args, **kwargs)
            captured.append(con)
            return con

        with patch(
            "cursor_view.projects.git.cursor_root", return_value=self._base
        ), patch(
            "cursor_view.projects.git.sqlite3.connect", side_effect=tracking_connect
        ):
            result = extract_project_from_git_repos(self.workspace_id)

        self.assertIsNone(result)
        self.assertEqual(
            len(captured), 1,
            "extract_project_from_git_repos should open exactly one connection",
        )
        with self.assertRaises(sqlite3.ProgrammingError):
            captured[0].execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
