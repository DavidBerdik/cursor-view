"""Per-project chat sort-order coverage for the createdAt-first ``sort_key_ms``.

Locks down the contract established by the project-chat sort-by-createdAt
fix-pass (``.cursor/plans/project-chat-sort-by-createdat_*.plan.md``):

- ``list_summaries`` returns chats in ``createdAt`` DESC order, even
  when ``lastUpdatedAt`` would invert that ordering. This is the
  symptom the screenshot in the originating bug report shows: a chat
  whose card displays an older ``createdAt`` was sorting ahead of a
  chat with a newer ``createdAt`` because the persisted sort key was
  derived from ``lastUpdatedAt`` and Cursor bumps that field on
  navigation-only writes (see
  ``.cursor/rules/sqlite-cursor-db.mdc`` "Invalidation: hash rows,
  don't stat files").
- The ``lastUpdatedAt`` fallback still resolves a sensible position
  when ``createdAt`` is missing. Without this guard, dropping the
  ``lastUpdatedAt``-priority branch entirely would silently demote
  every legacy composer that lacks ``createdAt`` to the bottom of
  the list (``session_sort_key_ms`` would return ``0``).

Reuses the ``BaseChatIndexImageTest`` harness from
``tests/_image_test_helpers.py``: it owns the synthetic-Cursor-DB
fixture (temp ``state.vscdb`` under a patched ``cursor_root``) every
chat-index regression test in this directory needs.
"""

from __future__ import annotations

import unittest

from tests._image_test_helpers import (
    BaseChatIndexImageTest,
    _composer,
    _put_kv,
)


def _bubble(text: str, role_type: int = 1) -> dict:
    """Build a minimal user-or-assistant bubble (no images, no tool calls).

    Mirrors the local ``_bubble`` helper in
    ``tests/test_chat_index_titles.py`` and
    ``tests/test_chat_index_incremental.py`` so a future helper
    promotion (lifting all three into ``_image_test_helpers.py``) is a
    pure consolidation rather than a rewrite.
    """
    return {"type": role_type, "text": text}


def _composer_with_timestamps(
    name: str,
    *,
    created_at: int | None,
    last_updated_at: int | None,
    headers: list[tuple[str, int]] | None = None,
) -> dict:
    """``_composer`` with overridable ``createdAt`` / ``lastUpdatedAt``.

    The shared ``_composer`` helper hard-codes both timestamps; this
    test module needs to vary them independently to drive the
    createdAt-vs-lastUpdatedAt sort decision, so we build on top of
    ``_composer`` and patch the two fields. ``None`` removes the key
    entirely so the absence-fallback branch in
    ``cursor_view.timestamps.session_sort_key_ms`` actually fires.
    """
    value = _composer(name, headers=headers)
    if created_at is None:
        value.pop("createdAt", None)
    else:
        value["createdAt"] = created_at
    if last_updated_at is None:
        value.pop("lastUpdatedAt", None)
    else:
        value["lastUpdatedAt"] = last_updated_at
    return value


class ChatIndexSortOrderTest(BaseChatIndexImageTest):
    """End-to-end coverage for createdAt-first ``sort_key_ms``."""

    def _seed_chat(
        self,
        cid: str,
        *,
        created_at: int | None,
        last_updated_at: int | None,
        bubble_id: str = "b1",
        bubble_text: str = "hello",
    ) -> None:
        """Stage one composer with explicit timestamps and a single bubble."""
        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer_with_timestamps(
                name="",
                created_at=created_at,
                last_updated_at=last_updated_at,
                headers=[(bubble_id, 1)],
            ),
        )
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:{bubble_id}",
            _bubble(bubble_text),
        )

    def test_created_at_priority_drives_order_not_last_updated_at(self) -> None:
        """A newer ``createdAt`` must sort first, even if its ``lastUpdatedAt`` is older.

        Pinned scenario from the originating bug report: chat A was
        created more recently but never re-touched, while chat B was
        created earlier and recently revisited (which bumped
        ``lastUpdatedAt``). The user expects A above B because the
        cards display ``createdAt`` -- the previous
        ``lastUpdatedAt``-first sort put B first instead.
        """
        cid_recent_creation = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        cid_recent_touch = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        # Newer createdAt, untouched since.
        self._seed_chat(
            cid_recent_creation,
            created_at=1_741_132_800_000,  # 2026-03-04T22:00Z-ish
            last_updated_at=1_741_132_800_000,
        )
        # Older createdAt but freshly revisited (lastUpdatedAt > recent_creation's).
        self._seed_chat(
            cid_recent_touch,
            created_at=1_736_337_600_000,  # 2026-01-08T...
            last_updated_at=1_745_000_000_000,  # 2026-04-18T...
        )

        ci = self._build_index()
        items = ci.list_summaries()["items"]

        ordered_ids = [item["session_id"] for item in items]
        self.assertIn(cid_recent_creation, ordered_ids)
        self.assertIn(cid_recent_touch, ordered_ids)
        self.assertLess(
            ordered_ids.index(cid_recent_creation),
            ordered_ids.index(cid_recent_touch),
            "chat with the newer createdAt must sort ahead of one with a "
            "newer lastUpdatedAt; this is the regression covered by the "
            "createdAt-first session_sort_key_ms change",
        )

    def test_last_updated_at_fallback_when_created_at_missing(self) -> None:
        """A composer with only ``lastUpdatedAt`` must still sort sensibly.

        Without the fallback, ``session_sort_key_ms`` would return
        ``0`` for any legacy composer that never wrote a
        ``createdAt`` and the chat would silently sink to the bottom
        of every list. The fallback branch is what keeps
        ``createdAt``-first from being a regression for those users.
        """
        cid_with_created = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        cid_only_last_updated = "dddddddd-dddd-dddd-dddd-dddddddddddd"

        self._seed_chat(
            cid_with_created,
            created_at=1_736_337_600_000,  # 2026-01-08
            last_updated_at=1_736_337_600_000,
        )
        self._seed_chat(
            cid_only_last_updated,
            created_at=None,
            last_updated_at=1_745_000_000_000,  # 2026-04-18
        )

        ci = self._build_index()
        items = ci.list_summaries()["items"]
        ordered_ids = [item["session_id"] for item in items]

        self.assertIn(cid_with_created, ordered_ids)
        self.assertIn(cid_only_last_updated, ordered_ids)
        self.assertLess(
            ordered_ids.index(cid_only_last_updated),
            ordered_ids.index(cid_with_created),
            "the createdAt-less chat must fall back to its lastUpdatedAt "
            "and outrank a chat whose createdAt is older than that "
            "fallback timestamp",
        )


if __name__ == "__main__":
    unittest.main()
