"""Round-trip + search + incremental-rename coverage for the ``chat_summary.title`` column.

Covers the v3 schema column added by the chat-title plan
(``.cursor/plans/chat_title_support_f75142a7.plan.md``):

- Real ``composerData.name`` flows end-to-end through extraction,
  ``format_chat_for_frontend``, ``_insert_chat``, the FTS search blob,
  and the API surfaces (``list_summaries`` and ``get_chat``).
- Synthetic placeholder titles (the ``Chat <8hex>`` fallback the
  global-composers extraction pass invents when ``name`` is empty)
  collapse to ``""`` in the cache so downstream consumers can gate
  rendering with a plain truthy check.
- Searching the home-page query bar by a title fragment finds the
  named chat, exercising the ``title``-prepended ``_search_blob``.
- Incremental refresh picks up a ``composerData.name`` rename
  in place, exercising the ``_composer_hash`` payload that now
  includes the title (a name-only edit still flips ``source_row``
  too, but the hash addition keeps the watermark column congruent
  with the served payload).

Reuses the ``BaseChatIndexImageTest`` harness from
``tests/_image_test_helpers.py``: it owns the synthetic-Cursor-DB
fixture (temp ``state.vscdb`` under a patched ``cursor_root``) every
chat-index regression test in this directory needs, regardless of
whether the test exercises image attachments specifically.
"""

from __future__ import annotations

import unittest

from tests._image_test_helpers import (
    BaseChatIndexImageTest,
    _composer,
    _put_kv,
)


def _bubble(text: str, role_type: int = 1) -> dict:
    """Build a minimal bubble value (no images, no tool calls).

    ``role_type`` follows Cursor's convention: ``1`` for user,
    ``2`` for assistant. Mirrors the local ``_bubble`` helper in
    ``tests/test_chat_index_incremental.py`` so a future helper
    promotion (lifting both into ``_image_test_helpers.py``) is a
    pure consolidation rather than a rewrite.
    """
    return {"type": role_type, "text": text}


class ChatIndexTitleTest(BaseChatIndexImageTest):
    """End-to-end coverage for the ``chat_summary.title`` column."""

    def _seed_named_chat(
        self,
        cid: str,
        name: str,
        bubble_text: str = "hello world",
    ) -> None:
        """Stage one composer with ``name`` plus a single user bubble."""
        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer(name, headers=[("b1", 1)]),
        )
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b1",
            _bubble(bubble_text),
        )

    def test_real_title_round_trips_through_cache_and_api(self) -> None:
        """A real ``composerData.name`` must surface as ``title`` on both API surfaces."""
        cid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self._seed_named_chat(cid, "My great plan")

        ci = self._build_index()

        summaries = ci.list_summaries()
        items = [item for item in summaries["items"] if item["session_id"] == cid]
        self.assertEqual(len(items), 1, "the named chat should appear in list_summaries")
        self.assertEqual(items[0]["title"], "My great plan")

        detail = ci.get_chat(cid)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["title"], "My great plan")

    def test_synthetic_title_collapses_to_empty_string(self) -> None:
        """A composer with no real ``name`` must cache ``title=''``.

        Empty / missing ``name`` triggers the
        ``cursor_view/extraction/passes/global_composers.py``
        ``Chat <8hex>`` fallback; ``_real_chat_title`` must classify
        that placeholder as synthetic and store ``""`` so UI / export
        / search consumers see a falsy gate.
        """
        cid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        self._seed_named_chat(cid, "")

        ci = self._build_index()

        summaries = ci.list_summaries()
        items = [item for item in summaries["items"] if item["session_id"] == cid]
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["title"], "",
            "synthetic 'Chat <8hex>' titles must collapse to empty string",
        )

        detail = ci.get_chat(cid)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["title"], "")

    def test_search_matches_chat_by_title_fragment(self) -> None:
        """Searching for a phrase from the title must find the named chat.

        Exercises the ``title``-prepended ``_search_blob``: the title
        landed in both ``chat_search_text`` and (when FTS5 is
        available) ``chat_search_fts``, so either branch of
        ``_count_summaries`` / ``_fetch_summaries`` resolves the
        query. The phrase ``"great plan"`` is intentionally chosen
        so it does NOT appear in the bubble body or project name,
        forcing the match to come from the title field rather than
        any incidental overlap.
        """
        named_cid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        other_cid = "dddddddd-dddd-dddd-dddd-dddddddddddd"
        self._seed_named_chat(named_cid, "My great plan", bubble_text="hi there")
        self._seed_named_chat(other_cid, "Unrelated chat", bubble_text="ok")

        ci = self._build_index()

        results = ci.list_summaries(query="great plan")
        matched_ids = {item["session_id"] for item in results["items"]}
        self.assertIn(named_cid, matched_ids, "title search should find the named chat")
        self.assertNotIn(
            other_cid, matched_ids,
            "title search must not pull in chats whose blobs lack the phrase",
        )

    def test_incremental_refresh_picks_up_title_rename(self) -> None:
        """A rename of ``composerData.name`` must propagate on the next refresh.

        Drives the incremental path (no full rebuild) so the change
        flows through the source-diff engine, ``_delete_cid_rows``,
        and ``_insert_chat`` again, which is the same path that
        consumes the updated ``_composer_hash`` payload (now folding
        in ``title``).
        """
        cid = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
        self._seed_named_chat(cid, "Original title")

        ci = self._build_index()
        before = ci.get_chat(cid)
        self.assertIsNotNone(before)
        self.assertEqual(before["title"], "Original title")

        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("Renamed title", headers=[("b1", 1)]),
        )
        self._refresh(ci)

        after = ci.get_chat(cid)
        self.assertIsNotNone(after)
        self.assertEqual(after["title"], "Renamed title")


if __name__ == "__main__":
    unittest.main()
