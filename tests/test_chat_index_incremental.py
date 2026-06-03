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

from cursor_view.chat_index import INDEX_SCHEMA_VERSION


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


def _bubble(
    text: str,
    role_type: int = 1,
    tool_call_id: str | None = None,
    tool_name: str = "task_v2",
    tool_params: dict | None = None,
) -> dict:
    """Build a bubble value. ``role_type`` is ``1`` for user, ``2`` for assistant.

    When ``tool_params`` is given it is JSON-encoded onto
    ``toolFormerData.params`` exactly as Cursor stores tool-call args, so a
    test can exercise the working-directory project signal (``cwd`` /
    ``targetDirectory``) mined by
    ``cursor_view.sources.bubbles._tool_call_folder_uris``.
    """
    v: dict = {"type": role_type, "text": text}
    if tool_call_id is not None or tool_params is not None:
        tf: dict = {"name": tool_name}
        if tool_call_id is not None:
            tf["toolCallId"] = tool_call_id
        if tool_params is not None:
            tf["params"] = json.dumps(tool_params)
        v["toolFormerData"] = tf
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
            patch(
                "cursor_view.chat_index.fingerprint.cursor_root",
                return_value=self.cursor_root,
            ),
            patch(
                "cursor_view.extraction.core.cursor_root",
                return_value=self.cursor_root,
            ),
            patch(
                "cursor_view.cache.delta.project_only.cursor_root",
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
        # Child was pulled into the dirty set by the apply-time
        # propagation gate's edge-churn arm: the new tool-call bubble
        # stages ``tool_call_parent_updates[tcid] = parent_cid`` with
        # no prior cached entry, so ``_compute_propagation_triggers``
        # adds ``task-<tcid>`` to its ``direct_cids`` bucket and the
        # walk in ``cursor_view/cache/delta/propagation.py`` folds the
        # child into ``modified_cids`` and ``subagent_propagated_cids``
        # (the observability bucket the refresh log reads). Reading
        # the dirty set after ``_refresh`` returns is what lets the
        # test see that post-apply state -- the diff itself leaves
        # ``subagent_propagated_cids`` empty under the new gating.
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

    # ---------------------------------------------------------------
    # Regression: orphan bubbles (absent from fullConversationHeadersOnly)
    # ---------------------------------------------------------------
    def _tool_call_parent_ids(self) -> set[str]:
        con = sqlite3.connect(self.cache_path)
        try:
            cur = con.cursor()
            cur.execute("SELECT tool_call_id FROM tool_call_parent")
            return {row[0] for row in cur.fetchall()}
        finally:
            con.close()

    def test_orphan_bubble_filtered_full_rebuild(self) -> None:
        """Bubbles absent from the headers array are dropped on full rebuild.

        Cursor prunes bubbles out of ``fullConversationHeadersOnly``
        (summarization checkpoints, conversation restarts) without
        deleting the corresponding ``bubbleId:*`` rows. When the
        headers array exists and is non-empty, any bubble whose id is
        not in it is stale state Cursor itself does not show, so
        extraction must skip it entirely rather than sort it to the
        end of the transcript.
        """
        cid = "bbbbbbbb-1111-1111-1111-111111111111"
        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("Orphan Full", headers=[("b1", 1), ("b2", 2)]),
        )
        _put_kv(self.global_db, f"bubbleId:{cid}:b1", _bubble("b1 text"))
        _put_kv(self.global_db, f"bubbleId:{cid}:b2", _bubble("b2 text", role_type=2))
        _put_kv(self.global_db, f"bubbleId:{cid}:b_orphan", _bubble("orphan text", role_type=2))

        self._build_index()

        rows = self._messages_with_rowid(cid)
        self.assertEqual(
            [(r[2], r[3]) for r in rows],
            [("user", "b1 text"), ("assistant", "b2 text")],
            "Orphan bubble must be dropped on full rebuild, not appended at the end",
        )
        for _rowid, _pos, _role, content in rows:
            self.assertNotIn("orphan", content.lower())

    def test_orphan_bubble_filtered_incremental(self) -> None:
        """Orphan filter also holds through the incremental refresh path."""
        cid = "bbbbbbbb-2222-2222-2222-222222222222"
        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("Orphan Inc", headers=[("b1", 1), ("b2", 2)]),
        )
        _put_kv(self.global_db, f"bubbleId:{cid}:b1", _bubble("b1 text"))
        _put_kv(self.global_db, f"bubbleId:{cid}:b2", _bubble("b2 text", role_type=2))
        _put_kv(self.global_db, f"bubbleId:{cid}:b_orphan", _bubble("orphan text", role_type=2))

        ci = self._build_index()

        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b2",
            _bubble("b2 text EDITED", role_type=2),
        )

        dirty = self._refresh(ci)
        self.assertEqual(dirty.modified_cids, {cid})

        rows = self._messages_with_rowid(cid)
        self.assertEqual(
            [(r[2], r[3]) for r in rows],
            [("user", "b1 text"), ("assistant", "b2 text EDITED")],
            "Incremental refresh must keep the orphan dropped and reflect the edit",
        )

    def test_orphan_bubble_still_records_tool_call_parent(self) -> None:
        """Orphan bubbles' ``toolFormerData.toolCallId`` MUST populate ``tool_call_parent``.

        ``tool_call_parent`` is a structural edge keyed by an
        upstream-model-unique ``toolCallId``, not display content.
        Cursor prunes parent bubbles out of
        ``fullConversationHeadersOnly`` (summarization checkpoints,
        conversation restarts) but the spawned ``task-<toolCallId>``
        subagent composer outlives those rewrites in ``cursorDiskKV``.
        Suppressing the edge for orphan bubbles surfaces the subagent
        as ``(unknown)`` / ``(global)`` even when its real parent is
        alive (Cause 1 in the project-resolution diagnostic in
        :mod:`cursor_view.extraction.diagnostics`).

        The orphan's display side effects (its text / role) MUST
        still be filtered; only the edge survives. This test pins
        both halves of that invariant in one body so a future regression
        can't relax just one side without reopening the other.
        """
        parent_cid = "bbbbbbbb-3333-3333-3333-333333333333"
        orphan_tcid = "toolu_orphan"
        _put_kv(
            self.global_db,
            f"composerData:{parent_cid}",
            _composer("Orphan ToolCall", headers=[("b1", 1)]),
        )
        _put_kv(self.global_db, f"bubbleId:{parent_cid}:b1", _bubble("parent ask"))
        _put_kv(
            self.global_db,
            f"bubbleId:{parent_cid}:b_orphan",
            _bubble("orphan tool call", role_type=2, tool_call_id=orphan_tcid),
        )

        self._build_index()

        self.assertIn(
            orphan_tcid,
            self._tool_call_parent_ids(),
            "Orphan bubble's toolCallId must be written to tool_call_parent so "
            "the spawned task-<toolCallId> subagent can still resolve its parent",
        )
        rows = self._messages_with_rowid(parent_cid)
        self.assertEqual(
            [(r[2], r[3]) for r in rows],
            [("user", "parent ask")],
            "Orphan bubble's display payload must NOT surface in chat_message",
        )

    def test_orphan_bubble_subagent_inherits_parent_workspace(self) -> None:
        """Cause 1 regression: subagent inherits parent's ws even when parent's tool-call bubble is orphaned.

        Reproduces the exact failure mode the diagnostic surfaced for
        ``task-toolu_01XvF39QpU8SG7TECB7EWnWg``: parent fires a
        ``task_v2`` tool call, Cursor later prunes that bubble out of
        the parent's ``fullConversationHeadersOnly`` array (the
        bubble row stays on disk), and the spawned subagent's
        composer is still in ``cursorDiskKV``. Before the fix, Pass
        2's orphan filter dropped the ``tool_call_parent`` upsert and
        Pass 5 had no edge to follow, so the subagent landed on
        ``(global)`` / ``(unknown)``. After the fix the edge is
        recorded and Pass 6 inherits the parent's workspace.
        """
        parent_cid = "bbbbbbbb-4444-4444-4444-444444444444"
        tcid = "toolu_orphaned_parent_call"
        child_cid = f"task-{tcid}"
        # Parent has a non-empty headers array that EXCLUDES the
        # tool-call bubble id ("b_orphan_call"), so the parent's
        # tool-call bubble is an orphan from extraction's point of
        # view but still lives on disk. Pane-view key promotes the
        # parent into a real workspace so the subagent has a
        # non-``(global)`` ws_id to inherit.
        _put_kv(
            self.global_db,
            f"composerData:{parent_cid}",
            _composer("Parent (orphan tool call)", headers=[("b_intro", 1)]),
        )
        _put_item(
            self.ws_db,
            f"workbench.panel.aichat.view.{parent_cid}",
            {"paneId": "p1"},
        )
        _put_kv(self.global_db, f"bubbleId:{parent_cid}:b_intro", _bubble("parent ask"))
        _put_kv(
            self.global_db,
            f"bubbleId:{parent_cid}:b_orphan_call",
            _bubble("calling tool", role_type=2, tool_call_id=tcid),
        )

        # Subagent composer is independent: its ``task-<tcid>`` cid
        # carries the canonical link back to the parent via the tool
        # call id, not via any field on its own composerData.
        _put_kv(self.global_db, f"composerData:{child_cid}", _composer("Child"))
        _put_kv(self.global_db, f"bubbleId:{child_cid}:b1", _bubble("child work"))
        _put_kv(
            self.global_db,
            f"bubbleId:{child_cid}:b2",
            _bubble("child done", role_type=2),
        )

        self._build_index()

        self.assertIn(
            tcid,
            self._tool_call_parent_ids(),
            "Orphan-filter relaxation must persist the tool_call_parent edge",
        )
        child_summary = self._summary(child_cid)
        self.assertIsNotNone(child_summary)
        self.assertEqual(
            child_summary[2],
            self.ws_id,
            "Subagent must inherit the parent's workspace via the cached "
            "tool_call_parent edge even when the parent's tool-call bubble "
            "is orphan-filtered out of the canonical transcript",
        )

    # ---------------------------------------------------------------
    # Tool-call working-directory project inference
    # ---------------------------------------------------------------
    def test_tool_call_cwd_infers_project(self) -> None:
        """A workspace-less global chat is categorized by its tool-call cwd.

        Reproduces the remote-PR-review case (composer 581811a1 on the
        authoring install): no ``workspaceIdentifier``, no attached-file
        URIs, but a ``run_terminal_command_v2`` tool call whose ``cwd`` is
        the local checkout the chat worked against. Before the fix the
        chat fell through to ``(unknown)``; now the working directory is
        mined as a folder URI and resolves a real local project root.
        """
        cid = "cccccccc-7777-7777-7777-777777777777"
        _put_kv(self.global_db, f"composerData:{cid}", _composer("Remote PR review"))
        _put_kv(self.global_db, f"bubbleId:{cid}:b1", _bubble("review the PR"))
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b2",
            _bubble(
                "running git log",
                role_type=2,
                tool_call_id="toolu_cwd_signal",
                tool_name="run_terminal_command_v2",
                tool_params={"cwd": "c:/repos/myrepo", "command": "git log"},
            ),
        )

        self._build_index()

        summary = self._summary(cid)
        self.assertIsNotNone(summary)
        self.assertEqual(
            summary[0],
            "myrepo",
            "Project name should come from the tool-call working directory",
        )
        self.assertEqual(
            summary[1],
            "/c:/repos/myrepo",
            "Project root should be the tool-call working directory",
        )
        # The chat itself is still workspace-less; only its project was inferred.
        self.assertEqual(summary[2], "(global)")

    def test_tool_call_cursor_dir_stays_unknown(self) -> None:
        """A tool-call dir under ``.cursor/`` must not manufacture a bogus project.

        Cursor-internal scratch directories (``~/.cursor/projects/<mangled>``)
        show up in tool-call args alongside the real checkout; on their own
        they are never a project root. Filtering them out is what keeps the
        real-checkout common-prefix from collapsing, so a chat whose ONLY
        tool dir is a ``.cursor`` path must stay ``(unknown)`` rather than be
        categorized under ``.cursor`` / a drive letter.
        """
        cid = "dddddddd-7777-7777-7777-777777777777"
        _put_kv(self.global_db, f"composerData:{cid}", _composer("Cursor-internal only"))
        _put_kv(self.global_db, f"bubbleId:{cid}:b1", _bubble("do something"))
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b2",
            _bubble(
                "globbing transcripts",
                role_type=2,
                tool_call_id="toolu_cursor_dir",
                tool_name="glob_file_search",
                tool_params={"targetDirectory": "c:/Users/me/.cursor/projects/c-repos-myrepo"},
            ),
        )

        self._build_index()

        summary = self._summary(cid)
        self.assertIsNotNone(summary)
        self.assertEqual(
            summary[0],
            "(unknown)",
            "A .cursor-only tool dir must not be promoted to a project",
        )
        self.assertEqual(summary[2], "(global)")

    def test_subagent_uses_own_tool_call_cwd_over_parent(self) -> None:
        """A subagent that touched the filesystem keeps its own inferred project.

        Mirrors the live case where an ``explore`` subagent searched a
        sibling repo while its parent reviewed a different one: the
        subagent resolves from its own tool-call cwd via Pass 4 and is
        NOT overwritten by Pass 6 parent inheritance.
        """
        parent_cid = "eeeeeeee-7777-7777-7777-777777777777"
        child_cid = "ffffffff-7777-7777-7777-777777777777"
        _put_kv(self.global_db, f"composerData:{parent_cid}", _composer("Parent review"))
        _put_kv(self.global_db, f"bubbleId:{parent_cid}:b1", _bubble("review"))
        _put_kv(
            self.global_db,
            f"bubbleId:{parent_cid}:b2",
            _bubble(
                "in connect repo",
                role_type=2,
                tool_call_id="toolu_parent_cwd",
                tool_name="run_terminal_command_v2",
                tool_params={"cwd": "c:/repos/connectrepo"},
            ),
        )
        # Child carries an authentic subagentInfo.parentComposerId link.
        child = _composer("Explore child")
        child["subagentInfo"] = {"parentComposerId": parent_cid}
        _put_kv(self.global_db, f"composerData:{child_cid}", child)
        _put_kv(self.global_db, f"bubbleId:{child_cid}:b1", _bubble("searching"))
        _put_kv(
            self.global_db,
            f"bubbleId:{child_cid}:b2",
            _bubble(
                "in sibling repo",
                role_type=2,
                tool_call_id="toolu_child_cwd",
                tool_name="glob_file_search",
                tool_params={"targetDirectory": "c:/repos/siblingrepo"},
            ),
        )

        self._build_index()

        self.assertEqual(self._summary(parent_cid)[0], "connectrepo")
        self.assertEqual(
            self._summary(child_cid)[0],
            "siblingrepo",
            "Subagent must keep the project inferred from its own tool-call "
            "dirs rather than inherit the parent's",
        )

    # ---------------------------------------------------------------
    # Regression: ensure_current schema-drift routing
    # ---------------------------------------------------------------
    def _seed_trivial_chat(self) -> str:
        """Populate the synthetic source DB with one small chat and return its cid."""
        cid = "cccccccc-0000-0000-0000-000000000001"
        _put_kv(self.global_db, f"composerData:{cid}", _composer("Schema Drift"))
        _put_kv(self.global_db, f"bubbleId:{cid}:b1", _bubble("hi"))
        _put_kv(self.global_db, f"bubbleId:{cid}:b2", _bubble("yo", role_type=2))
        return cid

    def test_schema_version_bump_forces_synchronous_rebuild(self) -> None:
        """Schema drift on a readable cache must go through the synchronous rebuild path.

        Serving rows built under the previous schema to callers that
        expect the new shape is a correctness bug, not a freshness
        issue; ``ChatIndex.ensure_current`` routes schema-version
        mismatches through ``_rebuild`` under the build lock instead
        of the stale-while-revalidate branch used for pure
        fingerprint misses. We simulate drift by editing the cache's
        ``schema_version`` meta row directly so the test does not
        have to monkey-patch ``INDEX_SCHEMA_VERSION`` (which is also
        folded into the source fingerprint and would confuse the
        assertion).
        """
        self._seed_trivial_chat()
        ci = self._build_index()

        con = sqlite3.connect(self.cache_path)
        try:
            con.execute(
                "UPDATE meta SET value=? WHERE key='schema_version'",
                (str(INDEX_SCHEMA_VERSION - 1),),
            )
            con.commit()
        finally:
            con.close()

        original_rebuild = ci._rebuild
        with patch.object(
            ci, "_schedule_background_refresh"
        ) as bg, patch.object(ci, "_rebuild", wraps=original_rebuild) as rebuild:
            ci.ensure_current()

        bg.assert_not_called()
        rebuild.assert_called_once()
        self.assertEqual(
            ci._read_meta_value("schema_version"),
            str(INDEX_SCHEMA_VERSION),
            "Synchronous rebuild should leave the cache stamped with the current schema version",
        )

    def test_source_fingerprint_bump_uses_background_refresh(self) -> None:
        """Pure fingerprint drift (row shapes still current) stays on the SWR path.

        Complements the schema-drift test: if a future regression
        accidentally routes fingerprint-only misses through the
        synchronous branch this assertion will fail loudly. We bump
        only the ``source_fingerprint`` meta row and leave
        ``schema_version`` untouched so the router hits the final
        ``_schedule_background_refresh`` arm.
        """
        self._seed_trivial_chat()
        ci = self._build_index()

        con = sqlite3.connect(self.cache_path)
        try:
            con.execute(
                "UPDATE meta SET value=? WHERE key='source_fingerprint'",
                ("deadbeef" * 8,),
            )
            con.commit()
        finally:
            con.close()

        original_rebuild = ci._rebuild
        with patch.object(
            ci, "_schedule_background_refresh"
        ) as bg, patch.object(ci, "_rebuild", wraps=original_rebuild) as rebuild:
            ci.ensure_current()

        bg.assert_called_once()
        rebuild.assert_not_called()

    def test_force_refresh_uses_delta_path(self) -> None:
        """``force=True`` must drive the incremental delta apply, not a full rebuild.

        Pins the contract the home page Refresh button relies on:
        when the cache exists, is readable, and stamped with the
        current ``INDEX_SCHEMA_VERSION``, a manual refresh runs
        through ``ChatIndex._run_synchronous_delta_or_rebuild`` and
        applies a per-composer delta. ``_rebuild`` is reserved as
        a correctness fallback. Wraps both methods with
        ``unittest.mock.patch.object(..., wraps=...)`` so the test
        observes call counts without changing behavior, mirroring
        the patching style of
        ``test_schema_version_bump_forces_synchronous_rebuild`` /
        ``test_source_fingerprint_bump_uses_background_refresh``.
        """
        cid = self._seed_trivial_chat()
        ci = self._build_index()
        before = self._messages_with_rowid(cid)
        self.assertEqual(len(before), 2)

        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b2",
            _bubble("yo EDITED", role_type=2),
        )

        original_rebuild = ci._rebuild
        original_apply = ci._apply_delta
        with patch.object(
            ci, "_rebuild", wraps=original_rebuild
        ) as rebuild, patch.object(
            ci, "_apply_delta", wraps=original_apply
        ) as apply_delta:
            ci.ensure_current(force=True)

        rebuild.assert_not_called()
        apply_delta.assert_called_once()

        after = self._messages_with_rowid(cid)
        self.assertTrue(
            any("EDITED" in row[3] for row in after),
            "Manual refresh must surface the mutated bubble through the delta path",
        )

    def test_force_refresh_recovers_from_corrupt_meta(self) -> None:
        """A corrupt cache on the manual-refresh path must not surface as a 500.

        ``ensure_current``'s force-arm fingerprint pre-check reads
        the cache's ``meta`` table, so a corrupt or missing ``meta``
        raises ``sqlite3.DatabaseError`` before the build lock is
        even acquired. The pre-check swallows that error and lets
        ``_run_synchronous_delta_or_rebuild`` run, which detects
        the same unreadability under the lock and falls back to a
        full rebuild. The follow-up ``list_summaries`` call is the
        proof-of-life witness that the rebuild really produced a
        usable cache.
        """
        cid = self._seed_trivial_chat()
        ci = self._build_index()

        con = sqlite3.connect(self.cache_path)
        try:
            con.execute("DROP TABLE meta")
            con.commit()
        finally:
            con.close()

        original_rebuild = ci._rebuild
        with patch.object(ci, "_rebuild", wraps=original_rebuild) as rebuild:
            ci.ensure_current(force=True)

        rebuild.assert_called_once()

        contents = {row[3] for row in self._messages_with_rowid(cid)}
        self.assertIn(
            "yo",
            contents,
            "Rebuild fallback after corrupt-meta recovery must repopulate "
            "the cache from the source DBs",
        )

    def test_force_refresh_falls_back_to_rebuild_on_apply_error(self) -> None:
        """A delta apply that raises ``DatabaseError`` must escalate to a full rebuild.

        Simulates the corruption-style failure
        ``_run_synchronous_delta_or_rebuild`` is meant to recover
        from: ``apply_delta`` raises ``sqlite3.DatabaseError`` mid
        single-tx write, the helper logs the failure and falls
        through to ``_rebuild`` so the cache is never left in a
        half-applied state. The follow-up ``list_summaries`` call
        is the proof-of-life witness that the rebuild really
        produced a usable cache (and surfaced the post-mutation
        content), not just that ``_rebuild`` was invoked.
        """
        cid = self._seed_trivial_chat()
        ci = self._build_index()

        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b2",
            _bubble("yo POST-FALLBACK", role_type=2),
        )

        original_rebuild = ci._rebuild
        with patch.object(
            ci, "_rebuild", wraps=original_rebuild
        ) as rebuild, patch.object(
            ci,
            "_apply_delta",
            side_effect=sqlite3.DatabaseError("simulated apply failure"),
        ):
            ci.ensure_current(force=True)

        rebuild.assert_called_once()

        payload = ci.list_summaries()
        contents = {row[3] for row in self._messages_with_rowid(cid)}
        self.assertIn(
            "yo POST-FALLBACK",
            contents,
            "Rebuild fallback must materialize the post-mutation source rows",
        )
        self.assertGreaterEqual(
            payload["total"],
            1,
            "list_summaries must succeed against the post-fallback cache",
        )

    def test_legacy_composer_still_includes_all_bubbles(self) -> None:
        """No headers array => legacy encounter-order fallback keeps every bubble.

        Supplements ``test_bubble_order_falls_back_to_encounter_order_without_headers``
        by explicitly naming the "extra bubble that would have been an
        orphan if headers existed" case, so future readers see the two
        branches of ``_collect_global_bubbles`` side-by-side.
        """
        cid = "bbbbbbbb-4444-4444-4444-444444444444"
        _put_kv(self.global_db, f"composerData:{cid}", _composer("Legacy No Headers"))
        # Alternating roles keep every bubble as its own chat_message
        # row; same-role neighbors would otherwise be coalesced and
        # hide the count we actually care about here.
        _put_kv(self.global_db, f"bubbleId:{cid}:b1", _bubble("first"))
        _put_kv(self.global_db, f"bubbleId:{cid}:b2", _bubble("second", role_type=2))
        _put_kv(self.global_db, f"bubbleId:{cid}:b_extra", _bubble("extra"))

        self._build_index()

        rows = self._messages_with_rowid(cid)
        contents = {r[3] for r in rows}
        self.assertEqual(
            contents,
            {"first", "second", "extra"},
            "Without a headers array, every bubble falls through the legacy path",
        )


if __name__ == "__main__":
    unittest.main()
