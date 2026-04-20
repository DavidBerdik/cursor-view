"""Behavioral tests for the incremental chat-index refresh path.

Covers the four scenarios called out in todo 9 of
``.cursor/plans/incremental_chat_cache_refresh_765d5b84.plan.md``:

1. A single ``bubbleId:*`` row mutation rewrites only that composer's
   messages; every other composer's rows keep their SQLite ``rowid``
   values (the witness we use for "not rewritten").
2. A ``workbench.explorer.treeViewState`` bump re-fires workspace
   project inference without touching any ``chat_message`` rows.
3. Adding a tool-call bubble to a parent composer promotes its
   ``task-<toolCallId>`` subagent child into the parent's workspace
   via the cached ``tool_call_parent`` map.
4. Adding a ``workbench.panel.aichat.view.<cid>`` pane-view key
   promotes the targeted cid into the workspace without touching
   the rows of other chats that already lived there.

Each test builds a synthetic Cursor root on disk (global ``state.vscdb``
plus one workspace ``state.vscdb``), runs one full rebuild to seed
the cache, mutates exactly one source row, and drives the delta path
directly via ``ChatIndex._compute_source_diff`` +
``ChatIndex._apply_delta``. Running under the real ``ensure_current``
worker is avoided so we don't have to synchronize with the background
thread; the apply contract is the same regardless of caller.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sqlite3
import tempfile
import unittest
from typing import Any
from unittest.mock import patch


def _create_source_schema(db_path: pathlib.Path, include_disk_kv: bool = True) -> None:
    """Create a minimal Cursor-shaped ``state.vscdb`` file with the tables we populate."""
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        if include_disk_kv:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS cursorDiskKV (key TEXT PRIMARY KEY, value BLOB)"
            )
        con.commit()
    finally:
        con.close()


def _encode(value: Any) -> Any:
    """Mirror Cursor's on-disk convention: JSON-encode dicts/lists, pass strings through."""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def _put_item(db_path: pathlib.Path, key: str, value: Any) -> None:
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO ItemTable(key, value) VALUES(?, ?)",
            (key, _encode(value)),
        )
        con.commit()
    finally:
        con.close()


def _put_kv(db_path: pathlib.Path, key: str, value: Any) -> None:
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO cursorDiskKV(key, value) VALUES(?, ?)",
            (key, _encode(value)),
        )
        con.commit()
    finally:
        con.close()


def _bubble(text: str, role_type: int = 1, tool_call_id: str | None = None) -> dict:
    """Build a bubble value. ``role_type`` is ``1`` for user, ``2`` for assistant."""
    v: dict = {"type": role_type, "text": text}
    if tool_call_id is not None:
        v["toolFormerData"] = {"toolCallId": tool_call_id, "name": "task_v2"}
    return v


def _composer(
    name: str,
    *,
    created_at: int = 1_700_000_000_000,
    updated_at: int = 1_700_000_001_000,
    workspace_id: str | None = None,
    headers: list[tuple[str, int]] | None = None,
) -> dict:
    """Build a composerData value; leaves ``subagentInfo`` null to mirror ``task_v2`` spawns.

    ``headers`` populates ``fullConversationHeadersOnly`` as a list of
    ``{"bubbleId": <bid>, "type": <role_type>}`` entries. Tests that
    care about the bubble-ordering fix pass it explicitly; tests that
    do not care leave it unset and the composer has no headers array,
    which is also the legacy shape.
    """
    v: dict = {
        "name": name,
        "createdAt": created_at,
        "lastUpdatedAt": updated_at,
        "subagentInfo": None,
    }
    if workspace_id is not None:
        v["workspaceIdentifier"] = {
            "id": workspace_id,
            "uri": {"external": f"file:///tmp/{workspace_id}"},
        }
    if headers is not None:
        v["fullConversationHeadersOnly"] = [
            {"bubbleId": bid, "type": role_type} for bid, role_type in headers
        ]
    return v


class IncrementalRefreshTest(unittest.TestCase):
    """End-to-end tests for the incremental refresh behaviors."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="cursor-view-incremental-")
        self.tmp_path = pathlib.Path(self.tmp)

        self.cursor_root = self.tmp_path / "cursor_root"
        self.cache_path = self.tmp_path / "cache" / "chat-index.sqlite3"
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        self.global_db = self.cursor_root / "User" / "globalStorage" / "state.vscdb"
        self.global_db.parent.mkdir(parents=True, exist_ok=True)
        _create_source_schema(self.global_db, include_disk_kv=True)

        self.ws_id = "aaaaaaaabbbbbbbbccccccccdddddddd"
        self.ws_folder = self.cursor_root / "User" / "workspaceStorage" / self.ws_id
        self.ws_folder.mkdir(parents=True, exist_ok=True)
        self.ws_db = self.ws_folder / "state.vscdb"
        _create_source_schema(self.ws_db, include_disk_kv=False)
        # workspace.json nails the project root to a stable value so the
        # tests don't depend on the extraction pipeline's URI-fallback
        # chain for project inference.
        (self.ws_folder / "workspace.json").write_text(
            json.dumps({"folder": "file:///tmp/testproj"}), encoding="utf-8"
        )

        # cursor_root() is imported at module load in several places;
        # patch each binding rather than the definition so every caller
        # resolves to the synthetic root we built above.
        self._patches = [
            patch("cursor_view.chat_index.cursor_root", return_value=self.cursor_root),
            patch(
                "cursor_view.extraction.core.cursor_root",
                return_value=self.cursor_root,
            ),
            patch(
                "cursor_view.cache.apply_delta.cursor_root",
                return_value=self.cursor_root,
            ),
            patch("cursor_view.projects.git.cursor_root", return_value=self.cursor_root),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build_index(self):
        """Create a ``ChatIndex`` pointed at the temp cache and run one full rebuild."""
        from cursor_view.chat_index import ChatIndex

        ci = ChatIndex(db_path=self.cache_path)
        ci.ensure_current(force=True)
        return ci

    def _refresh(self, ci):
        """Drive one incremental refresh cycle synchronously; return the ``DirtySet``."""
        fp, sources = ci._current_source_fingerprint()
        dirty = ci._compute_source_diff(sources)
        ci._apply_delta(dirty, fp, sources)
        return dirty

    def _messages_with_rowid(self, session_id: str) -> list[tuple[int, int, str, str]]:
        """Return ``[(rowid, position, role, content), ...]`` for one session."""
        con = sqlite3.connect(self.cache_path)
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT rowid, position, role, content FROM chat_message "
                "WHERE session_id=? ORDER BY position",
                (session_id,),
            )
            return list(cur.fetchall())
        finally:
            con.close()

    def _summary(self, session_id: str) -> tuple[str, str, str, int] | None:
        """Return ``(project_name, project_root, workspace_id, message_count)`` or ``None``."""
        con = sqlite3.connect(self.cache_path)
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT project_name, project_root_path, workspace_id, message_count "
                "FROM chat_summary WHERE session_id=?",
                (session_id,),
            )
            row = cur.fetchone()
            return tuple(row) if row else None
        finally:
            con.close()

    # ---------------------------------------------------------------
    # Test 1: single bubbleId mutation
    # ---------------------------------------------------------------
    def test_single_bubble_mutation_rewrites_only_that_composer(self) -> None:
        cid_a = "11111111-1111-1111-1111-111111111111"
        cid_b = "22222222-2222-2222-2222-222222222222"
        _put_kv(self.global_db, f"composerData:{cid_a}", _composer("Chat A"))
        _put_kv(self.global_db, f"composerData:{cid_b}", _composer("Chat B"))
        _put_kv(self.global_db, f"bubbleId:{cid_a}:b1", _bubble("hello a"))
        _put_kv(self.global_db, f"bubbleId:{cid_a}:b2", _bubble("reply a", role_type=2))
        _put_kv(self.global_db, f"bubbleId:{cid_b}:b1", _bubble("hello b"))
        _put_kv(self.global_db, f"bubbleId:{cid_b}:b2", _bubble("reply b", role_type=2))

        ci = self._build_index()
        before_a = self._messages_with_rowid(cid_a)
        before_b = self._messages_with_rowid(cid_b)
        self.assertEqual(len(before_a), 2)
        self.assertEqual(len(before_b), 2)

        _put_kv(
            self.global_db,
            f"bubbleId:{cid_a}:b2",
            _bubble("reply a EDITED", role_type=2),
        )

        dirty = self._refresh(ci)
        self.assertIn(cid_a, dirty.modified_cids)
        self.assertNotIn(cid_b, dirty.modified_cids)

        after_a = self._messages_with_rowid(cid_a)
        after_b = self._messages_with_rowid(cid_b)

        # cid_a was DELETE+INSERTed, so its rowids advanced past the
        # original ones; a strict "disjoint" check is the cleanest
        # witness for "these rows were rewritten" that doesn't rely on
        # SQLite's rowid allocation policy staying monotonic.
        self.assertTrue(
            {row[0] for row in before_a}.isdisjoint({row[0] for row in after_a}),
            "cid_a chat_message rows should have been rewritten",
        )
        self.assertTrue(
            any("EDITED" in row[3] for row in after_a),
            "Mutated bubble text should be visible in the refreshed cache",
        )
        # cid_b must be row-for-row identical: same rowids, positions,
        # roles, and contents.
        self.assertEqual(before_b, after_b, "cid_b rows should be untouched")

    # ---------------------------------------------------------------
    # Test 2: workspace-only project signal changed
    # ---------------------------------------------------------------
    def test_tree_view_state_only_bump_preserves_messages(self) -> None:
        cid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        _put_kv(self.global_db, f"composerData:{cid}", _composer("WS Chat"))
        _put_kv(self.global_db, f"bubbleId:{cid}:b1", _bubble("hi"))
        _put_kv(self.global_db, f"bubbleId:{cid}:b2", _bubble("yo", role_type=2))
        # Pane-view key promotes the composer into the workspace without
        # requiring a workspaceIdentifier round-trip; keeps the workspace
        # mapping deterministic across Cursor versions.
        _put_item(self.ws_db, f"workbench.panel.aichat.view.{cid}", {"paneId": "p1"})
        _put_item(
            self.ws_db,
            "workbench.explorer.treeViewState",
            {"focus": ["file:///tmp/testproj/a.py"]},
        )

        ci = self._build_index()
        before = self._messages_with_rowid(cid)
        self.assertEqual(len(before), 2)
        self.assertEqual(self._summary(cid)[2], self.ws_id)

        _put_item(
            self.ws_db,
            "workbench.explorer.treeViewState",
            {"focus": ["file:///tmp/testproj/b.py"]},
        )

        dirty = self._refresh(ci)
        self.assertIn(self.ws_id, dirty.workspace_project_dirty)
        self.assertNotIn(cid, dirty.modified_cids)

        after = self._messages_with_rowid(cid)
        self.assertEqual(
            before,
            after,
            "treeViewState churn must not rewrite any chat_message rows",
        )

    # ---------------------------------------------------------------
    # Test 3: tool-call bubble appended -> subagent re-resolves
    # ---------------------------------------------------------------
    def test_tool_call_bubble_reresolves_task_subagent(self) -> None:
        parent_cid = "55555555-5555-5555-5555-555555555555"
        tcid = "toolu_abc123"
        child_cid = f"task-{tcid}"
        # Parent is workspace-resident via pane-view key so its workspace
        # is what the subagent should eventually inherit.
        _put_kv(self.global_db, f"composerData:{parent_cid}", _composer("Parent"))
        _put_item(self.ws_db, f"workbench.panel.aichat.view.{parent_cid}", {"paneId": "p1"})
        _put_kv(self.global_db, f"bubbleId:{parent_cid}:b1", _bubble("parent ask"))

        _put_kv(self.global_db, f"composerData:{child_cid}", _composer("Child"))
        _put_kv(self.global_db, f"bubbleId:{child_cid}:b1", _bubble("child work"))
        _put_kv(self.global_db, f"bubbleId:{child_cid}:b2", _bubble("child done", role_type=2))

        ci = self._build_index()
        child_before = self._summary(child_cid)
        self.assertIsNotNone(child_before)
        self.assertEqual(
            child_before[2],
            "(global)",
            "Without a tool-call bubble, the subagent has no parent link yet",
        )

        # Appending the tool-call bubble is the source event Pass 5
        # uses to reconstruct the subagent parent link.
        _put_kv(
            self.global_db,
            f"bubbleId:{parent_cid}:b2",
            _bubble("calling tool", role_type=2, tool_call_id=tcid),
        )

        dirty = self._refresh(ci)
        self.assertIn(parent_cid, dirty.modified_cids)
        # Child was pulled into the dirty set via subagent propagation,
        # not via its own row-hash diff; the observability bucket from
        # todo 8 tracks exactly this.
        self.assertIn(child_cid, dirty.modified_cids)
        self.assertIn(child_cid, dirty.subagent_propagated_cids)

        child_after = self._summary(child_cid)
        self.assertEqual(
            child_after[2],
            self.ws_id,
            "Subagent child should now inherit the parent's workspace",
        )

    # ---------------------------------------------------------------
    # Test 4: pane-view key promotes one cid, leaves others alone
    # ---------------------------------------------------------------
    def test_pane_view_key_promotes_only_targeted_cid(self) -> None:
        promoted_cid = "77777777-7777-7777-7777-777777777777"
        untouched_cid = "88888888-8888-8888-8888-888888888888"

        # Pre-existing workspace-resident chat so we can prove it's left
        # alone even though it shares a workspace with the promoted one.
        _put_kv(self.global_db, f"composerData:{untouched_cid}", _composer("Already Here"))
        _put_item(
            self.ws_db,
            f"workbench.panel.aichat.view.{untouched_cid}",
            {"paneId": "p1"},
        )
        _put_kv(self.global_db, f"bubbleId:{untouched_cid}:b1", _bubble("ws hi"))
        _put_kv(
            self.global_db,
            f"bubbleId:{untouched_cid}:b2",
            _bubble("ws reply", role_type=2),
        )

        _put_kv(self.global_db, f"composerData:{promoted_cid}", _composer("Promoted"))
        _put_kv(self.global_db, f"bubbleId:{promoted_cid}:b1", _bubble("global hi"))
        _put_kv(
            self.global_db,
            f"bubbleId:{promoted_cid}:b2",
            _bubble("global reply", role_type=2),
        )

        ci = self._build_index()
        self.assertEqual(self._summary(promoted_cid)[2], "(global)")
        self.assertEqual(self._summary(untouched_cid)[2], self.ws_id)
        before_untouched = self._messages_with_rowid(untouched_cid)

        _put_item(
            self.ws_db,
            f"workbench.panel.aichat.view.{promoted_cid}",
            {"paneId": "p2"},
        )

        dirty = self._refresh(ci)
        self.assertIn(promoted_cid, dirty.modified_cids)
        self.assertNotIn(untouched_cid, dirty.modified_cids)
        self.assertIn(promoted_cid, dirty.workspace_comp2ws_dirty.get(self.ws_id, set()))

        self.assertEqual(
            self._summary(promoted_cid)[2],
            self.ws_id,
            "Targeted cid should have been promoted into the workspace",
        )
        self.assertEqual(self._summary(untouched_cid)[2], self.ws_id)
        after_untouched = self._messages_with_rowid(untouched_cid)
        self.assertEqual(
            before_untouched,
            after_untouched,
            "Other chats in the same workspace must not be rewritten",
        )


    # ---------------------------------------------------------------
    # Regression: container pane-view row removing a cid demotes it
    # ---------------------------------------------------------------
    def test_container_pane_view_removal_demotes_workspace_residency(self) -> None:
        """A ``composerChatViewPane.<paneId>`` container losing a cid demotes it to global.

        Caught during the review of this plan: when a cid's only
        workspace link is a container-nested pane-view entry (no
        stand-alone ``workbench.panel.aichat.view.<cid>`` key) and
        Cursor rewrites the container to drop the cid, the diff used
        to see the container's hash change but extract no cids from
        the new (empty) value, leaving the cid pinned to the stale
        workspace. Conservative widening in ``_classify_workspace_row``
        now folds every workspace-resident cid into ``modified_cids``
        when a container row changes so removals are honored.
        """
        cid = "66666666-6666-6666-6666-666666666666"
        _put_kv(self.global_db, f"composerData:{cid}", _composer("Nested"))
        _put_kv(self.global_db, f"bubbleId:{cid}:b1", _bubble("nested hi"))
        _put_item(
            self.ws_db,
            "workbench.panel.composerChatViewPane.pane1",
            {f"workbench.panel.aichat.view.{cid}": {"x": 1}},
        )

        ci = self._build_index()
        self.assertEqual(
            self._summary(cid)[2],
            self.ws_id,
            "After full build the container entry should place cid in the workspace",
        )

        _put_item(self.ws_db, "workbench.panel.composerChatViewPane.pane1", {})

        dirty = self._refresh(ci)
        self.assertIn(cid, dirty.modified_cids)

        self.assertEqual(
            self._summary(cid)[2],
            "(global)",
            "Removing the cid from the only container that held it must demote to (global)",
        )


    # ---------------------------------------------------------------
    # Regression: bubble order follows composerData.fullConversationHeadersOnly
    # ---------------------------------------------------------------
    def test_bubble_order_uses_headers_array(self) -> None:
        """Messages land in ``fullConversationHeadersOnly`` order, not bubbleId order.

        Reproduces the scrambled-messages bug fixed by the
        ``fix_bubble_ordering`` step: Cursor writes bubbles into
        ``cursorDiskKV`` keyed by ``bubbleId:<cid>:<bid>`` where
        ``<bid>`` is a UUIDv4, so SQLite's PK scan returns rows in
        alphabetical (i.e. effectively random) order. The canonical
        chronological order lives on ``composerData.fullConversationHeadersOnly``.
        Bubble ids are chosen here so their alphabetical order
        (``b_aaa < b_mmm < b_zzz``) is the EXACT REVERSE of the order
        the headers array records (``b_zzz``, ``b_mmm``, ``b_aaa``) --
        a PK-order extraction would land in the wrong order and the
        alternating role sequence would tell us which order actually
        took effect.
        """
        cid = "99999999-9999-9999-9999-999999999999"
        # Types: 1 == user, 2 == assistant. Alternating roles so the
        # coalescer does not merge adjacent entries and every bubble
        # becomes its own chat_message row we can assert on.
        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer(
                "Order Test",
                headers=[("b_zzz", 1), ("b_mmm", 2), ("b_aaa", 1)],
            ),
        )
        _put_kv(self.global_db, f"bubbleId:{cid}:b_aaa", _bubble("third user msg"))
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b_mmm",
            _bubble("second assistant msg", role_type=2),
        )
        _put_kv(self.global_db, f"bubbleId:{cid}:b_zzz", _bubble("first user msg"))

        ci = self._build_index()

        rows = self._messages_with_rowid(cid)
        self.assertEqual(
            [(r[2], r[3]) for r in rows],
            [
                ("user", "first user msg"),
                ("assistant", "second assistant msg"),
                ("user", "third user msg"),
            ],
            "Full rebuild should order messages by fullConversationHeadersOnly, "
            "not by the alphabetical bubbleId order cursorDiskKV returns",
        )

        # Incremental refresh must preserve the order after a bubble
        # edit on the middle turn; the delta path uses the same Pass 2
        # that the full rebuild does, so breaking this means the
        # scoped iterator or the apply step dropped the ordering map.
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b_mmm",
            _bubble("second assistant msg EDITED", role_type=2),
        )
        dirty = self._refresh(ci)
        self.assertIn(cid, dirty.modified_cids)

        rows_after = self._messages_with_rowid(cid)
        self.assertEqual(
            [(r[2], r[3]) for r in rows_after],
            [
                ("user", "first user msg"),
                ("assistant", "second assistant msg EDITED"),
                ("user", "third user msg"),
            ],
            "Incremental refresh should preserve headers-array order and reflect the bubble edit",
        )

    # ---------------------------------------------------------------
    # Regression: legacy composers without the headers array still work
    # ---------------------------------------------------------------
    def test_bubble_order_falls_back_to_encounter_order_without_headers(self) -> None:
        """Composers with no ``fullConversationHeadersOnly`` keep legacy behavior.

        Old Cursor builds predate the headers array, so the ordering
        fix must not make their case worse. Bubbles fall through to
        "append in encountered order" (PK order). This test just
        asserts the chat still surfaces with the expected message
        count -- we don't assert on the specific ordering because
        legacy behavior against UUIDv4 bubbleIds is, by design, not
        chronologically meaningful.
        """
        cid = "aaaaaaaa-0000-0000-0000-000000000001"
        _put_kv(self.global_db, f"composerData:{cid}", _composer("Legacy"))
        _put_kv(self.global_db, f"bubbleId:{cid}:b1", _bubble("hello"))
        _put_kv(self.global_db, f"bubbleId:{cid}:b2", _bubble("world", role_type=2))

        ci = self._build_index()
        summary = self._summary(cid)
        self.assertIsNotNone(summary)
        rows = self._messages_with_rowid(cid)
        self.assertEqual(len(rows), 2, "Legacy composer should still produce both messages")


if __name__ == "__main__":
    unittest.main()
