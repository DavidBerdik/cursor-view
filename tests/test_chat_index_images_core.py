"""Original end-to-end ``chat_image`` scenarios + the two original coalescer unit cases.

Covers scenarios 1, 2, 3, and 5 from section 11 of
``.cursor/plans/image_attachment_support_55e4fd2e.plan.md`` (modern-shape
rebuild, legacy-shape rebuild, modification-via-incremental-apply,
multiple images round-trip) plus the two original
``coalesce_consecutive_messages_by_role`` unit cases
(same-role image concatenation, image-only turn placeholder).

Related siblings:
- ``tests/test_chat_index_images_regressions.py`` -- E1 regressions
  including the E1-extended ``test_missing_disk_image_is_skipped_not_fatal``
  (scenario 4 from the original plan, now wrapped in ``assertLogs``).
- ``tests/test_chat_index_images_exports.py`` -- A8 Markdown / A9 HTML
  export regression cases.

Shared fixtures + ``BaseChatIndexImageTest`` harness live in
``tests/_image_test_helpers.py``.
"""

from __future__ import annotations

import sqlite3
import unittest

from tests._image_test_helpers import (
    BaseChatIndexImageTest,
    _bubble_with_legacy_image,
    _bubble_with_modern_image,
    _bubble_with_modern_images,
    _composer,
    _put_kv,
    PNG_PREFIX,
)


class ChatIndexImageTest(BaseChatIndexImageTest):
    """End-to-end tests for the ``chat_image`` content table."""

    # ---------------------------------------------------------------
    # Case 1: modern shape (on-disk path) round-trips on full rebuild
    # ---------------------------------------------------------------
    def test_full_rebuild_materializes_modern_image(self) -> None:
        cid = "11111111-1111-1111-1111-111111111111"
        uuid = "img-modern-1"
        png_path = self._write_png("modern")
        png_bytes = png_path.read_bytes()

        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("Chat M", headers=[("b1", 1)]),
        )
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b1",
            _bubble_with_modern_image("look at this", uuid, png_path),
        )

        self._build_index()
        rows = self._chat_image_rows(cid)
        self.assertEqual(len(rows), 1, "one modern-shape image should land as one row")
        self.assertEqual(rows[0]["uuid"], uuid)
        self.assertEqual(rows[0]["mime_type"], "image/png")
        self.assertEqual(bytes(rows[0]["data"]), png_bytes)
        self.assertEqual(rows[0]["position"], 0)
        self.assertEqual(rows[0]["image_index"], 0)

    # ---------------------------------------------------------------
    # Case 2: legacy shape (inline byte dict) round-trips exactly
    # ---------------------------------------------------------------
    def test_full_rebuild_materializes_legacy_image(self) -> None:
        cid = "22222222-2222-2222-2222-222222222222"
        uuid = "img-legacy-1"
        png_bytes = PNG_PREFIX + b"legacy-body-\x00\x01\x02"

        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("Chat L", headers=[("b1", 1)]),
        )
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b1",
            _bubble_with_legacy_image("look at this", uuid, png_bytes),
        )

        self._build_index()
        rows = self._chat_image_rows(cid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["uuid"], uuid)
        self.assertEqual(rows[0]["mime_type"], "image/png")
        self.assertEqual(
            bytes(rows[0]["data"]),
            png_bytes,
            "inline Uint8Array dict must round-trip to the exact original bytes",
        )

    # ---------------------------------------------------------------
    # Case 3: editing a bubble's image refreshes chat_image via delta
    # ---------------------------------------------------------------
    def test_modification_updates_chat_image(self) -> None:
        cid = "33333333-3333-3333-3333-333333333333"
        png_v1 = self._write_png("v1", b"version-1-body")
        png_v2 = self._write_png("v2", b"version-2-body")

        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("Chat S", headers=[("b1", 1)]),
        )
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b1",
            _bubble_with_modern_image("first", "uuid-a", png_v1),
        )

        ci = self._build_index()
        before = self._chat_image_rows(cid)
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]["uuid"], "uuid-a")
        self.assertEqual(bytes(before[0]["data"]), png_v1.read_bytes())

        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b1",
            _bubble_with_modern_image("second", "uuid-b", png_v2),
        )

        dirty = self._refresh(ci)
        self.assertIn(
            cid,
            dirty.modified_cids,
            "the edited bubble should flip the source-row hash and dirty its composer",
        )

        after = self._chat_image_rows(cid)
        self.assertEqual(
            len(after), 1, "stale chat_image row should be dropped by _delete_cid_rows"
        )
        self.assertEqual(after[0]["uuid"], "uuid-b")
        self.assertEqual(bytes(after[0]["data"]), png_v2.read_bytes())

    # ---------------------------------------------------------------
    # Case 5: multiple images per message round-trip end-to-end
    # ---------------------------------------------------------------
    def test_full_rebuild_materializes_multiple_images_per_message(self) -> None:
        from cursor_view.chat_index.rows import _fetch_images_for_session

        cid = "55555555-5555-5555-5555-555555555555"
        uuid_a = "multi-uuid-a"
        uuid_b = "multi-uuid-b"
        png_a = self._write_png("multi-a", b"body-A-\xde\xad")
        png_b = self._write_png("multi-b", b"body-B-\xbe\xef")
        bytes_a = png_a.read_bytes()
        bytes_b = png_b.read_bytes()
        self.assertNotEqual(
            bytes_a, bytes_b, "sanity: fixture bytes must differ for (d) to be meaningful"
        )

        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("Multi", headers=[("b1", 1)]),
        )
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b1",
            _bubble_with_modern_images(
                "two images on one turn",
                [
                    {"uuid": uuid_a, "path": png_a, "width": 10, "height": 20},
                    {"uuid": uuid_b, "path": png_b, "width": 30, "height": 40},
                ],
            ),
        )

        ci = self._build_index()

        # (a) Two chat_image rows in the right (position, image_index) slots.
        rows = self._chat_image_rows(cid)
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [(r["position"], r["image_index"], r["uuid"]) for r in rows],
            [(0, 0, uuid_a), (0, 1, uuid_b)],
        )
        self.assertEqual(bytes(rows[0]["data"]), bytes_a)
        self.assertEqual(bytes(rows[1]["data"]), bytes_b)

        # (b) _fetch_images_for_session returns them in image_index order.
        con = sqlite3.connect(self.cache_path)
        con.row_factory = sqlite3.Row
        try:
            fetched = _fetch_images_for_session(con, cid, include_bytes=False)
        finally:
            con.close()
        self.assertEqual([img["uuid"] for img in fetched], [uuid_a, uuid_b])

        # (c) get_chat attaches both to the single message, in order, with
        #     storage-layer internals stripped.
        detail = ci.get_chat(cid)
        self.assertIsNotNone(detail)
        self.assertEqual(len(detail["messages"]), 1)
        msg_images = detail["messages"][0]["images"]
        self.assertEqual([img["uuid"] for img in msg_images], [uuid_a, uuid_b])
        for img in msg_images:
            self.assertNotIn("position", img)
            self.assertNotIn("image_index", img)

        # (d) get_image returns each uuid's own bytes, not the other's.
        got_a = ci.get_image(cid, uuid_a)
        got_b = ci.get_image(cid, uuid_b)
        self.assertIsNotNone(got_a)
        self.assertIsNotNone(got_b)
        self.assertEqual(got_a[0], bytes_a)
        self.assertEqual(got_b[0], bytes_b)
        self.assertNotEqual(
            got_a[0],
            got_b[0],
            "get_image must scope by uuid, not return the first chat_image row",
        )


class CoalescerImageTest(unittest.TestCase):
    """Unit cases for image handling in ``coalesce_consecutive_messages_by_role``."""

    def test_coalesce_concatenates_images_on_same_role_merge(self) -> None:
        from cursor_view.chat_format import coalesce_consecutive_messages_by_role

        img = {"uuid": "i1"}
        out = coalesce_consecutive_messages_by_role(
            [
                {"role": "user", "content": "hello", "images": []},
                {"role": "user", "content": "", "images": [img]},
            ]
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["role"], "user")
        self.assertEqual(
            out[0]["content"],
            "hello",
            "the text-only segment's content must survive the merge",
        )
        self.assertEqual(
            out[0]["images"],
            [img],
            "the image-only segment's images must be appended in order",
        )

    def test_coalesce_image_only_turn_does_not_get_content_unavailable_placeholder(self) -> None:
        from cursor_view.chat_format import coalesce_consecutive_messages_by_role

        img = {"uuid": "lonely-image"}
        out = coalesce_consecutive_messages_by_role(
            [{"role": "user", "content": "", "images": [img]}]
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(
            out[0]["content"],
            "",
            "image-only turns keep empty text; the gallery conveys the signal",
        )
        self.assertEqual(out[0]["images"], [img])


if __name__ == "__main__":
    unittest.main()
