"""E1 regression cases for ``chat_image`` and the image-aware coalescer.

Tracks the regression set called out in
``.cursor/plans/image_attachment_post-impl_followup_2b026aae.plan.md``
section E1, one test per fix so a regression on any of them fails
here rather than silently in production:

- ``test_image_only_chat_preview_is_not_content_unavailable`` (A1)
- ``test_coalesce_post_loop_placeholder_clear`` (section 5 post-loop)
- ``test_get_chat_with_include_image_bytes_round_trip`` (``data_uri``
  base64 round-trip through :meth:`ChatIndex.get_chat`)
- ``test_missing_disk_image_is_skipped_not_fatal`` -- the E1-extended
  form (wraps the original scenario-4 rebuild in ``assertLogs`` so a
  regression that silently swallows ``OSError`` fails here instead of
  passing with zero observable output)
- ``test_disk_and_legacy_dedup_prefers_disk`` (section 3.1 dedup)
- ``test_non_dict_bubble_json_is_skipped`` (B1)
- ``test_out_of_range_image_position_logs_and_drops`` (A4)

The ``assertLogs("cursor_view.images.loading", level="WARNING")`` and
``assertLogs("cursor_view.chat_index.rows", level="WARNING")`` call
sites here must keep the exact logger paths the production code uses.

Related siblings:
- ``tests/test_chat_index_images_core.py`` -- original end-to-end
  scenarios + two original coalescer unit cases.
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
    _bubble_with_both_shapes_same_uuid,
    _bubble_with_modern_image,
    _composer,
    _put_kv,
    PNG_PREFIX,
)


class ChatIndexImageRegressionTest(BaseChatIndexImageTest):
    """E1 regressions layered on top of the ``chat_image`` end-to-end harness."""

    # ---------------------------------------------------------------
    # E1 regression: missing on-disk image is skipped, not fatal
    # (extends scenario 4 with an ``assertLogs`` wrapper so silent
    # OSError-swallow regressions fail here)
    # ---------------------------------------------------------------
    def test_missing_disk_image_is_skipped_not_fatal(self) -> None:
        cid = "44444444-4444-4444-4444-444444444444"
        missing = self.images_dir / "never-written.png"
        self.assertFalse(missing.exists())

        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("Chat G", headers=[("b1", 1)]),
        )
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b1",
            _bubble_with_modern_image("still has text", "u-missing", missing),
        )

        # Must not raise: load_image_bytes returns None for OSError and the
        # insert helper skips that image. The owning message still lands.
        # ``assertLogs`` on the loading module pins the WARNING so a
        # regression that silently swallows ``OSError`` fails here
        # instead of passing with zero observable output.
        with self.assertLogs("cursor_view.images.loading", level="WARNING") as log_ctx:
            self._build_index()
        self.assertTrue(
            any("Image file missing" in entry for entry in log_ctx.output),
            f"expected a missing-disk WARNING; got {log_ctx.output!r}",
        )

        self.assertEqual(
            self._chat_image_rows(cid),
            [],
            "missing-disk image must be skipped rather than producing a row",
        )
        msgs = self._chat_messages(cid)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0][1], "still has text")

    # ---------------------------------------------------------------
    # E1 regression: image-only chat preview (A1)
    # ---------------------------------------------------------------
    def test_image_only_chat_preview_is_not_content_unavailable(self) -> None:
        """A1: a chat whose only signal is an image must not render as "Content unavailable"."""
        cid = "a1000000-0000-0000-0000-000000000001"
        uuid = "a1-img"
        png_path = self._write_png("a1")

        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("Image Only", headers=[("b1", 1)]),
        )
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b1",
            # Bubble has empty text and one image attachment; the
            # coalescer emits content="" and the preview-builder's
            # image-aware fallback should kick in.
            _bubble_with_modern_image("", uuid, png_path),
        )

        ci = self._build_index()
        items = ci.list_summaries()["items"]
        match = next((item for item in items if item["session_id"] == cid), None)
        self.assertIsNotNone(
            match, "image-only chat must still appear in list_summaries"
        )
        self.assertNotEqual(
            match["preview"],
            "Content unavailable",
            "image-only preview must not reuse the text-fallback label",
        )
        # Belt-and-suspenders: A1's fix specifically emits "(image
        # attachment)", so anchor the observable text the user sees.
        self.assertIn("image", match["preview"].lower())

    # ---------------------------------------------------------------
    # E1 regression: include_image_bytes=True data_uri round-trip
    # ---------------------------------------------------------------
    def test_get_chat_with_include_image_bytes_round_trip(self) -> None:
        """get_chat(include_image_bytes=True) base64-decodes back to the original bytes."""
        import base64

        cid = "c1000000-0000-0000-0000-000000000001"
        uuid = "round-trip"
        png_path = self._write_png("roundtrip", b"round-trip-body-\xde\xad\xbe\xef")
        original_bytes = png_path.read_bytes()

        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("Round Trip", headers=[("b1", 1)]),
        )
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b1",
            _bubble_with_modern_image("look", uuid, png_path),
        )

        ci = self._build_index()
        detail = ci.get_chat(cid, include_image_bytes=True)
        self.assertIsNotNone(detail)
        msgs = detail["messages"]
        self.assertEqual(len(msgs), 1)
        images = msgs[0]["images"]
        self.assertEqual(len(images), 1)
        data_uri = images[0].get("data_uri")
        self.assertIsNotNone(
            data_uri, "include_image_bytes=True must populate data_uri"
        )
        self.assertTrue(
            data_uri.startswith("data:image/png;base64,"),
            f"data_uri prefix must be data:<mime>;base64, got {data_uri[:40]!r}",
        )
        encoded = data_uri.split(",", 1)[1]
        self.assertEqual(
            base64.b64decode(encoded),
            original_bytes,
            "base64-decoded data_uri must equal the source bytes exactly",
        )

    # ---------------------------------------------------------------
    # E1 regression: disk + legacy duplicate uuids dedup, disk wins
    # ---------------------------------------------------------------
    def test_disk_and_legacy_dedup_prefers_disk(self) -> None:
        """A bubble carrying the same uuid in both shapes dedups to one disk-backed row."""
        cid = "d1000000-0000-0000-0000-000000000001"
        uuid = "dedup-uuid"
        # Deliberately different bytes so we can prove which shape won.
        disk_body = b"disk-wins-payload"
        inline_body = b"inline-loses-payload"
        png_path = self.images_dir / "image-dedup.png"
        png_path.write_bytes(PNG_PREFIX + disk_body)

        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("Dedup", headers=[("b1", 1)]),
        )
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b1",
            _bubble_with_both_shapes_same_uuid(
                "same uuid both shapes",
                uuid,
                png_path,
                PNG_PREFIX + inline_body,
            ),
        )

        self._build_index()
        rows = self._chat_image_rows(cid)
        self.assertEqual(
            len(rows), 1, "disk+legacy duplicate uuids should dedup to one row"
        )
        self.assertEqual(rows[0]["uuid"], uuid)
        self.assertEqual(
            bytes(rows[0]["data"]),
            PNG_PREFIX + disk_body,
            "disk-preferred dedup: on-disk bytes must win over the inline dict",
        )

    # ---------------------------------------------------------------
    # E1 regression: non-dict bubble JSON is skipped, not crashed on (B1)
    # ---------------------------------------------------------------
    def test_non_dict_bubble_json_is_skipped(self) -> None:
        """B1: bubble bodies that parse to a list / null / string must not crash extraction."""
        cid = "b1000000-0000-0000-0000-000000000001"
        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("NonDict", headers=[("b1", 1), ("b2", 1), ("b3", 1)]),
        )
        # Three pathological JSON bodies. ``_put_kv`` passes plain
        # strings through to SQLite unchanged, and the parser under
        # test runs ``json.loads`` on each.
        _put_kv(self.global_db, f"bubbleId:{cid}:b1", "[]")
        _put_kv(self.global_db, f"bubbleId:{cid}:b2", "null")
        _put_kv(self.global_db, f"bubbleId:{cid}:b3", '"just a bare string"')

        # Pre-B1 this raised ``AttributeError: 'list' object has no
        # attribute 'get'`` inside the extraction pipeline; post-B1
        # the non-dict bubbles are skipped.
        self._build_index()
        self.assertEqual(
            self._chat_messages(cid),
            [],
            "a composer whose every bubble fails the isinstance(dict) gate must land no messages",
        )

    # ---------------------------------------------------------------
    # E1 regression: out-of-range chat_image.position (A4)
    # ---------------------------------------------------------------
    def test_out_of_range_image_position_logs_and_drops(self) -> None:
        """A4: chat_image rows with position outside [0, len(messages)) are dropped with a WARNING."""
        cid = "a4000000-0000-0000-0000-000000000001"
        uuid_in_range = "a4-in-range"
        uuid_oob = "a4-out-of-range"
        png_path = self._write_png("a4")

        _put_kv(
            self.global_db,
            f"composerData:{cid}",
            _composer("OOB", headers=[("b1", 1)]),
        )
        _put_kv(
            self.global_db,
            f"bubbleId:{cid}:b1",
            _bubble_with_modern_image("look", uuid_in_range, png_path),
        )

        ci = self._build_index()

        # Inject an OOB row directly into the cache DB; production
        # code never writes position=999, but a partial delta-apply,
        # a manual DB edit, or a future regression could produce one.
        con = sqlite3.connect(self.cache_path)
        try:
            con.execute(
                "INSERT INTO chat_image("
                "session_id, position, image_index, uuid, mime_type, width, height, data"
                ") VALUES (?, 999, 0, ?, 'image/png', 10, 10, ?)",
                (cid, uuid_oob, png_path.read_bytes()),
            )
            con.commit()
        finally:
            con.close()

        with self.assertLogs("cursor_view.chat_index.rows", level="WARNING") as log_ctx:
            detail = ci.get_chat(cid)
        self.assertIsNotNone(detail)
        self.assertEqual(len(detail["messages"]), 1)
        msg_images = detail["messages"][0]["images"]
        attached_uuids = [img["uuid"] for img in msg_images]
        self.assertEqual(
            attached_uuids,
            [uuid_in_range],
            "only the in-range image must attach; OOB row must be dropped silently from the payload",
        )
        self.assertNotIn(
            uuid_oob,
            attached_uuids,
            "out-of-range image must not be misrouted to an unrelated message",
        )
        self.assertTrue(
            any("out-of-range chat_image" in entry for entry in log_ctx.output),
            f"expected an out-of-range WARNING; got {log_ctx.output!r}",
        )


class CoalescerImageRegressionTest(unittest.TestCase):
    """E1 regression in ``coalesce_consecutive_messages_by_role``'s post-loop."""

    def test_coalesce_post_loop_placeholder_clear(self) -> None:
        """Section 5 post-loop: a placeholder seeded by a truly-empty first turn
        must be cleared once a same-role image-only turn appends its images.

        Trace for the input below:
          1. First turn: no text, no images -> seeds content="Content
             unavailable", images=[] (the truly-empty-segment fallback).
          2. Second turn: same role, empty text, one image -> merges into
             the record above, appending images without writing over the
             placeholder content.
          3. Post-loop: any record whose content=="Content unavailable"
             AND whose images list is non-empty has its content cleared
             to "" so the gallery is not rendered next to a misleading
             text label.
        """
        from cursor_view.chat_format import coalesce_consecutive_messages_by_role

        img = {"uuid": "merged-in"}
        out = coalesce_consecutive_messages_by_role(
            [
                {"role": "user", "content": "", "images": []},
                {"role": "user", "content": "", "images": [img]},
            ]
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(
            out[0]["content"],
            "",
            "post-loop must clear the 'Content unavailable' placeholder "
            "once same-role image merging makes the record image-bearing",
        )
        self.assertEqual(out[0]["images"], [img])


if __name__ == "__main__":
    unittest.main()
