"""Behavioral tests for the apply-time gated subagent dirty-set propagation.

Pins the five invariants the propagation gate in
``cursor_view/cache/delta/propagation.py`` was introduced to enforce:

1. **Bubble append on a parent without project shift does NOT
   propagate.** A user adding a non-tool-call bubble to a long-running
   parent must not drag every ``task-<toolCallId>`` descendant
   through scoped extraction and ``_delete_cid_rows``. Witness: the
   subagent's ``chat_message`` row ids stay byte-for-byte identical
   across the refresh, and ``dirty.subagent_propagated_cids`` stays
   empty. This is the case the gate was specifically built to fix --
   the user-reported "23242 modified (inserted 505, 22737
   subagent-propagated)" log line had this shape on every refresh
   under the pre-gating code.

2. **Parent project promotion DOES propagate.** When a directly
   modified parent's post-extraction
   ``(workspace_id, project_name, project_root_path)`` triple
   actually shifts versus the cached row, every ``task-*``
   descendant must re-extract so its inherited project follows.

3. **Parent deletion propagates.** A vanished parent removes its
   descendants' inheritance anchor; they must re-extract so Pass 6
   walks further up the chain (or falls back to ``(global)``).

4. **New ``tool_call_parent`` edge propagates only the targeted
   ``task-<tcid>`` child, not its sibling.** A second tool-call
   bubble fired on a parent that already had one tool-call child
   must drag the *new* child into ``modified_cids`` while leaving
   the existing child's row ids untouched -- this is the surgical
   trigger that distinguishes the new gating from the
   pre-implementation walk's "every descendant of every dirty
   parent" semantic.

5. **Soft-deleted parent propagates.** A directly-modified parent
   whose primary extraction yields no chat (every bubble pruned by
   the ``composerData.fullConversationHeadersOnly`` orphan invariant)
   has its ``chat_summary`` and ``composer_state`` cleared by
   ``_apply_chat_writes`` but never re-inserted, so descendants face
   the same vanished-anchor situation a hard deletion produces. The
   only difference is bookkeeping (``modified_cids`` rather than
   ``deleted_cids``); the propagation walk must treat the two
   identically. Witness: ``dirty.subagent_propagated_cids`` includes
   the descendant and the descendant's ``chat_message`` rowids
   change (the secondary scoped extraction ran a fresh
   delete-then-insert), even when the post-extraction inherited
   project happens to land on the same workspace because some other
   source row (e.g. the parent's pane-view key) still resolves it.

Synthetic-Cursor-DB harness mirrors the shape used by
``tests/test_chat_index_incremental.py`` per
``.cursor/rules/project-layout.mdc`` "Tests".
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


def _delete_kv(db_path: pathlib.Path, key: str) -> None:
    """Remove one ``cursorDiskKV`` row; used by the parent-deletion test."""
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("DELETE FROM cursorDiskKV WHERE key=?", (key,))
        con.commit()
    finally:
        con.close()


def _delete_item(db_path: pathlib.Path, key: str) -> None:
    """Remove one ``ItemTable`` row; used to scrub a workspace pane-view row."""
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("DELETE FROM ItemTable WHERE key=?", (key,))
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
    name: str, headers: list[tuple[str, int]] | None = None
) -> dict:
    """Build a composerData value; leaves ``subagentInfo`` null to mirror ``task_v2`` spawns.

    ``headers`` populates ``fullConversationHeadersOnly`` as the list
    of ``{"bubbleId": <bid>, "type": <role_type>}`` entries Cursor
    treats as the canonical transcript. Tests that exercise the
    orphan-filter / soft-deletion path supply this explicitly so they
    can pin the parent's bubbles in or out of the allowlist; tests
    that don't care leave it unset and the legacy-fallback encounter-
    order path applies.
    """
    v: dict = {
        "name": name,
        "createdAt": 1_700_000_000_000,
        "lastUpdatedAt": 1_700_000_001_000,
        "subagentInfo": None,
    }
    if headers is not None:
        v["fullConversationHeadersOnly"] = [
            {"bubbleId": bid, "type": role_type} for bid, role_type in headers
        ]
    return v


class PropagationGatingTest(unittest.TestCase):
    """End-to-end coverage for the apply-time subagent-propagation gate."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="cursor-view-propagation-")
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

    def _seed_parent_with_subagent(
        self,
        parent_cid: str,
        tcid: str,
        child_cid: str,
        *,
        promote_parent: bool,
    ) -> None:
        """Seed one workspace-resident parent + one ``task-<tcid>`` subagent child.

        The parent has two bubbles: a user prompt and an assistant turn
        that fires the tool call. The child has its own two bubbles. When
        ``promote_parent`` is true, an ``aichat.view.<parent_cid>`` pane
        key resolves the parent into ``self.ws_id`` so Pass 5 + Pass 6
        let the child inherit it.
        """
        _put_kv(self.global_db, f"composerData:{parent_cid}", _composer("Parent"))
        _put_kv(self.global_db, f"bubbleId:{parent_cid}:b1", _bubble("parent ask"))
        _put_kv(
            self.global_db,
            f"bubbleId:{parent_cid}:b2",
            _bubble("calling tool", role_type=2, tool_call_id=tcid),
        )
        if promote_parent:
            _put_item(
                self.ws_db,
                f"workbench.panel.aichat.view.{parent_cid}",
                {"paneId": "p1"},
            )
        _put_kv(self.global_db, f"composerData:{child_cid}", _composer("Child"))
        _put_kv(self.global_db, f"bubbleId:{child_cid}:b1", _bubble("child work"))
        _put_kv(
            self.global_db,
            f"bubbleId:{child_cid}:b2",
            _bubble("child done", role_type=2),
        )

    # ---------------------------------------------------------------
    # Case 1: parent bubble append without project shift does NOT propagate
    # ---------------------------------------------------------------
    def test_bubble_append_without_project_shift_does_not_propagate(self) -> None:
        parent_cid = "11111111-1111-1111-1111-111111111111"
        tcid = "toolu_case1"
        child_cid = f"task-{tcid}"
        self._seed_parent_with_subagent(parent_cid, tcid, child_cid, promote_parent=True)

        ci = self._build_index()
        # Sanity: child inherited the parent's workspace via Pass 5 + Pass 6.
        self.assertEqual(self._summary(child_cid)[2], self.ws_id)
        child_before = self._messages_with_rowid(child_cid)
        self.assertEqual(len(child_before), 2)

        # Append a non-tool-call user bubble to the parent. No new
        # tool_call_parent edge, no project shift.
        _put_kv(self.global_db, f"bubbleId:{parent_cid}:b3", _bubble("follow up"))

        dirty = self._refresh(ci)
        self.assertIn(parent_cid, dirty.modified_cids)
        self.assertNotIn(
            child_cid,
            dirty.subagent_propagated_cids,
            "Bubble append without project shift must not propagate to the subagent",
        )
        self.assertNotIn(
            child_cid,
            dirty.modified_cids,
            "Subagent must not be folded into modified_cids on a bubble-only parent change",
        )

        child_after = self._messages_with_rowid(child_cid)
        self.assertEqual(
            child_before,
            child_after,
            "Subagent chat_message rows must stay byte-for-byte identical -- "
            "rowid equality is the witness that the gate skipped the descendant entirely",
        )

    # ---------------------------------------------------------------
    # Case 2: parent project promotion DOES propagate
    # ---------------------------------------------------------------
    def test_parent_project_promotion_propagates_to_subagent(self) -> None:
        parent_cid = "22222222-2222-2222-2222-222222222222"
        tcid = "toolu_case2"
        child_cid = f"task-{tcid}"
        # Build with NO pane-view promotion so both parent and child
        # start "(global)"; the child still inherits via the tool-call
        # edge but inherits the parent's "(global)" tag.
        self._seed_parent_with_subagent(parent_cid, tcid, child_cid, promote_parent=False)

        ci = self._build_index()
        self.assertEqual(
            self._summary(parent_cid)[2],
            "(global)",
            "Without pane-view promotion the parent should start at (global)",
        )
        self.assertEqual(
            self._summary(child_cid)[2],
            "(global)",
            "Subagent inheriting from a (global) parent stays (global)",
        )

        # Promote the parent into the workspace via a pane-view key.
        # The classify pass adds parent_cid to dirty.modified_cids and
        # the apply step's project-shift detector should see the
        # post-extraction (workspace_id, ...) tuple differ from the
        # cached "(global)" row.
        _put_item(
            self.ws_db,
            f"workbench.panel.aichat.view.{parent_cid}",
            {"paneId": "p1"},
        )

        dirty = self._refresh(ci)
        self.assertIn(parent_cid, dirty.modified_cids)
        self.assertIn(
            child_cid,
            dirty.subagent_propagated_cids,
            "Project shift on parent must propagate to the task-* subagent",
        )

        self.assertEqual(
            self._summary(parent_cid)[2],
            self.ws_id,
            "Parent should now resolve to the workspace via the pane-view key",
        )
        self.assertEqual(
            self._summary(child_cid)[2],
            self.ws_id,
            "Subagent must re-inherit the parent's new workspace through "
            "_augment_cached_state_for_secondary",
        )

    # ---------------------------------------------------------------
    # Case 3: parent deletion propagates
    # ---------------------------------------------------------------
    def test_parent_deletion_propagates_to_subagent(self) -> None:
        parent_cid = "33333333-3333-3333-3333-333333333333"
        tcid = "toolu_case3"
        child_cid = f"task-{tcid}"
        self._seed_parent_with_subagent(parent_cid, tcid, child_cid, promote_parent=True)

        ci = self._build_index()
        self.assertEqual(
            self._summary(child_cid)[2],
            self.ws_id,
            "Subagent should have inherited the parent's workspace before deletion",
        )

        # Drop every source row for the parent so _process_deletions
        # classifies it as deleted. Bubbles must go too, AND the
        # workspace pane-view key must go: while that pane-view row
        # carries ``composer_id == parent_cid`` in its source-row
        # snapshot, ``_process_deletions`` keeps the cid in
        # ``cids_with_new_rows`` and demotes it to ``modified_cids``
        # instead of ``deleted_cids``. Scrubbing the pane-view row
        # is what lets this test exercise the deletion-trigger arm
        # of the propagation gate.
        _delete_kv(self.global_db, f"composerData:{parent_cid}")
        _delete_kv(self.global_db, f"bubbleId:{parent_cid}:b1")
        _delete_kv(self.global_db, f"bubbleId:{parent_cid}:b2")
        _delete_item(self.ws_db, f"workbench.panel.aichat.view.{parent_cid}")

        dirty = self._refresh(ci)
        self.assertIn(parent_cid, dirty.deleted_cids)
        self.assertIn(
            child_cid,
            dirty.subagent_propagated_cids,
            "Parent deletion must trigger descendant propagation",
        )

        # Parent row is gone from chat_summary.
        self.assertIsNone(self._summary(parent_cid))
        # Child re-extracted; with the parent excluded from
        # cached_state.ancestor_comp2ws (via dirty.deleted_cids in the
        # skip set), Pass 6's walk falls through to "(global)".
        self.assertEqual(
            self._summary(child_cid)[2],
            "(global)",
            "Without an inheritable parent the subagent re-resolves to (global)",
        )

    # ---------------------------------------------------------------
    # Case 4: new tool-call edge propagates only the targeted child
    # ---------------------------------------------------------------
    def test_new_edge_propagates_only_targeted_child(self) -> None:
        parent_cid = "44444444-4444-4444-4444-444444444444"
        tcid_a = "toolu_case4_a"
        tcid_b = "toolu_case4_b"
        child_a = f"task-{tcid_a}"
        child_b = f"task-{tcid_b}"

        # Initial: parent has one tool-call (tcid_a) wired to child_a;
        # child_b exists in cursorDiskKV but is not yet linked to the
        # parent (no bubble fires tcid_b yet), so it starts (global).
        self._seed_parent_with_subagent(parent_cid, tcid_a, child_a, promote_parent=True)
        _put_kv(self.global_db, f"composerData:{child_b}", _composer("Sibling"))
        _put_kv(self.global_db, f"bubbleId:{child_b}:b1", _bubble("sibling ask"))
        _put_kv(
            self.global_db,
            f"bubbleId:{child_b}:b2",
            _bubble("sibling reply", role_type=2),
        )

        ci = self._build_index()
        self.assertEqual(self._summary(child_a)[2], self.ws_id)
        self.assertEqual(
            self._summary(child_b)[2],
            "(global)",
            "child_b has no parent edge yet; it should still be (global)",
        )
        child_a_before = self._messages_with_rowid(child_a)
        self.assertEqual(len(child_a_before), 2)

        # Append a SECOND tool-call bubble on the parent that fires
        # tcid_b. The first tool-call bubble (tcid_a) is unchanged, so
        # its row hash stays the same; only tcid_b is staged as a
        # tool_call_parent_updates entry.
        _put_kv(
            self.global_db,
            f"bubbleId:{parent_cid}:b3",
            _bubble("calling other tool", role_type=2, tool_call_id=tcid_b),
        )

        dirty = self._refresh(ci)
        self.assertIn(parent_cid, dirty.modified_cids)
        self.assertIn(
            child_b,
            dirty.subagent_propagated_cids,
            "New tool_call_parent edge must propagate to task-<tcid_b>",
        )
        self.assertNotIn(
            child_a,
            dirty.subagent_propagated_cids,
            "Sibling subagent whose edge is unchanged must NOT propagate -- "
            "this is the surgical-trigger guarantee that distinguishes the "
            "new gating from the pre-implementation 'every parent's task-* "
            "descendants' walk",
        )
        self.assertNotIn(
            child_a,
            dirty.modified_cids,
            "Sibling subagent must not be folded into modified_cids either",
        )

        child_a_after = self._messages_with_rowid(child_a)
        self.assertEqual(
            child_a_before,
            child_a_after,
            "Sibling chat_message rowids prove no DELETE+INSERT cycle ran for child_a",
        )
        # The newly-edged child does pick up the parent's workspace
        # via the augmented ancestor map.
        self.assertEqual(
            self._summary(child_b)[2],
            self.ws_id,
            "child_b should now inherit the parent's workspace via the new edge",
        )

    # ---------------------------------------------------------------
    # Case 5: soft-deleted parent propagates (orphan-filtered to no chat)
    # ---------------------------------------------------------------
    def test_soft_deleted_parent_propagates_to_subagent(self) -> None:
        """A parent whose primary extraction yields no chat must still propagate.

        Cursor's "summarization checkpoint" / "reset to this point"
        UX rewrites ``composerData.fullConversationHeadersOnly`` to
        an allowlist that no longer covers the existing
        ``bubbleId:*`` rows. The orphan-filter invariant (see
        ``.cursor/rules/sqlite-cursor-db.mdc`` "Canonical bubble
        order") then drops every bubble during scoped re-extraction
        and ``_finalize_sessions`` collapses the empty session, so
        ``new_chats[parent_cid]`` is ``None`` and the cid never
        lands in ``primary_formatted``. Because the parent's
        ``composerData`` row hash changed (and its workspace pane-
        view key still ties at least one source row to the cid),
        the parent stays in ``dirty.modified_cids`` rather than
        falling into ``dirty.deleted_cids`` -- the trigger arm a
        plain hard deletion would exercise.

        The fix folds ``modified_cids - primary_formatted`` into
        ``walk_starts``; this test pins that the descendant
        ``task-<tcid>`` actually rides the secondary scoped
        extraction and re-resolves its inheritance, rather than
        keeping the parent's now-stale workspace until some
        unrelated future refresh dirties the descendant directly.
        """
        parent_cid = "55555555-5555-5555-5555-555555555555"
        tcid = "toolu_case5"
        child_cid = f"task-{tcid}"

        # Seed the parent with a headers allowlist that covers both
        # of its real bubbles, and promote it into the workspace via
        # a pane-view key. After the rebuild the subagent inherits
        # the parent's workspace through the tool_call_parent edge.
        _put_kv(
            self.global_db,
            f"composerData:{parent_cid}",
            _composer("Parent", headers=[("b1", 1), ("b2", 2)]),
        )
        _put_kv(self.global_db, f"bubbleId:{parent_cid}:b1", _bubble("parent ask"))
        _put_kv(
            self.global_db,
            f"bubbleId:{parent_cid}:b2",
            _bubble("calling tool", role_type=2, tool_call_id=tcid),
        )
        _put_item(
            self.ws_db,
            f"workbench.panel.aichat.view.{parent_cid}",
            {"paneId": "p1"},
        )
        _put_kv(self.global_db, f"composerData:{child_cid}", _composer("Child"))
        _put_kv(self.global_db, f"bubbleId:{child_cid}:b1", _bubble("child work"))
        _put_kv(
            self.global_db,
            f"bubbleId:{child_cid}:b2",
            _bubble("child done", role_type=2),
        )

        ci = self._build_index()
        self.assertEqual(
            self._summary(parent_cid)[2],
            self.ws_id,
            "Parent should resolve to the workspace via the pane-view key on first build",
        )
        self.assertEqual(
            self._summary(child_cid)[2],
            self.ws_id,
            "Subagent should have inherited the parent's workspace before soft-deletion",
        )
        child_before = self._messages_with_rowid(child_cid)
        self.assertEqual(
            len(child_before), 2,
            "Subagent should have its two seeded messages before soft-deletion",
        )

        # Rewrite the headers array to point at a bubble id that does
        # not exist; both real bubbles ``b1`` / ``b2`` become orphans
        # under the canonical-bubble-order invariant. The composerData
        # row hash flips so the parent lands in ``modified_cids``, but
        # because the workspace pane-view key still associates one
        # source row with the cid, ``_process_deletions`` keeps it out
        # of ``deleted_cids`` -- exactly the soft-deletion shape.
        _put_kv(
            self.global_db,
            f"composerData:{parent_cid}",
            _composer("Parent", headers=[("b_nonexistent", 1)]),
        )

        dirty = self._refresh(ci)
        self.assertIn(parent_cid, dirty.modified_cids)
        self.assertNotIn(
            parent_cid,
            dirty.deleted_cids,
            "Soft deletion lives in modified_cids, not deleted_cids -- "
            "this distinction is what the gap closure has to cover",
        )
        self.assertIsNone(
            self._summary(parent_cid),
            "Parent's chat_summary row must be gone: _apply_chat_writes "
            "deleted it and skipped the re-insert because the orphan "
            "filter left no messages",
        )
        self.assertIn(
            child_cid,
            dirty.subagent_propagated_cids,
            "Soft-deleted parent must propagate to the task-* subagent so "
            "its inherited project is re-resolved instead of staying stale",
        )

        # Witness that the secondary scoped extraction actually ran on
        # the descendant: the apply path's delete-then-insert cycle
        # gives every chat_message row a fresh rowid. This is the same
        # rowid-equality witness Case 1 uses inverted -- there
        # equality proves the gate skipped the descendant; here
        # inequality proves it didn't. Without the fix to fold
        # ``modified_cids - primary_formatted`` into ``walk_starts``
        # the propagation walk never reaches the child and these
        # rowids stay equal.
        child_after = self._messages_with_rowid(child_cid)
        before_rowids = [row[0] for row in child_before]
        after_rowids = [row[0] for row in child_after]
        self.assertNotEqual(
            before_rowids,
            after_rowids,
            "Subagent chat_message rowids must change: re-extraction under "
            "the secondary pass is what the soft-deletion trigger arm is "
            "for, and a stable rowid would mean the walk skipped the "
            "descendant entirely",
        )


if __name__ == "__main__":
    unittest.main()
