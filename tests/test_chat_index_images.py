"""Tests for the ``chat_image`` content table + image-aware coalescer.

Covers the seven scenarios called out in section 11 of
``.cursor/plans/image_attachment_support_55e4fd2e.plan.md``:

1. Modern (on-disk ``context.selectedImages``) image materializes into
   ``chat_image`` on a full rebuild.
2. Legacy (inline top-level ``images`` Uint8Array dict) image
   materializes with round-trip byte equality.
3. Editing a bubble's image value flips the source-row hash, the delta
   path runs ``_delete_cid_rows`` (which now drops ``chat_image``) and
   the re-insert replaces the stale row.
4. A missing on-disk image path is skipped (with a ``logger.warning``)
   rather than raising; the owning message still lands in
   ``chat_message``.
5. Two images on the same bubble round-trip end-to-end: per-index rows
   in ``chat_image``, ordered results from ``_fetch_images_for_session``,
   both images attached to the single message by ``ChatIndex.get_chat``,
   and each uuid returns its own bytes via ``ChatIndex.get_image``.

Plus two unit cases against ``coalesce_consecutive_messages_by_role``:

6. Same-role consecutive messages with image lists concatenate in order
   when merged.
7. An image-only user turn renders with empty content, not
   "Content unavailable" -- so the UI's gallery isn't paired with a
   misleading placeholder.

Plus the E1 regression set tracked by
``.cursor/plans/image_attachment_post-impl_followup_2b026aae.plan.md``,
one test per fix so a regression on any of them fails here:

- ``test_image_only_chat_preview_is_not_content_unavailable`` (A1)
- ``test_coalesce_post_loop_placeholder_clear`` (section 5 post-loop)
- ``test_get_chat_with_include_image_bytes_round_trip`` (``data_uri``
  base64 round-trip through :meth:`ChatIndex.get_chat`)
- ``test_missing_disk_image_is_skipped_not_fatal`` wraps its rebuild
  in ``assertLogs`` so a regression that silently swallows ``OSError``
  fails instead of passing with zero observable output
- ``test_disk_and_legacy_dedup_prefers_disk`` (section 3.1 dedup)
- ``test_non_dict_bubble_json_is_skipped`` (B1)
- ``test_out_of_range_image_position_logs_and_drops`` (A4)
- ``MarkdownExportImageTest`` (A8 blank-line separator)
- ``HtmlExportImageTest`` (A9 anchor wrapper + CSS)

The synthetic-Cursor-DB harness mirrors ``test_chat_index_incremental``
with four ``cursor_root`` patches aiming every caller at a temp
directory, so the tests never touch the developer's real Cursor state.
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


PNG_PREFIX = b"\x89PNG\r\n\x1a\n"


def _create_source_schema(db_path: pathlib.Path) -> None:
    """Create a minimal Cursor-shaped ``state.vscdb`` with ItemTable + cursorDiskKV."""
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS cursorDiskKV (key TEXT PRIMARY KEY, value BLOB)"
        )
        con.commit()
    finally:
        con.close()


def _encode(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


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


def _composer(name: str, headers: list[tuple[str, int]] | None = None) -> dict:
    """Build a composerData value with an optional ``fullConversationHeadersOnly``."""
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


def _bubble_with_modern_image(
    text: str,
    uuid: str,
    disk_path: pathlib.Path,
    role_type: int = 1,
    width: int = 10,
    height: int = 10,
) -> dict:
    """One bubble carrying a single modern-shape on-disk image reference."""
    return {
        "type": role_type,
        "text": text,
        "context": {
            "selectedImages": [
                {
                    "uuid": uuid,
                    "path": str(disk_path),
                    "dimension": {"width": width, "height": height},
                    "loadedAt": 1_700_000_000_000,
                    "addedWithoutMention": False,
                }
            ],
        },
    }


def _bubble_with_modern_images(
    text: str,
    entries: list[dict[str, Any]],
    role_type: int = 1,
) -> dict:
    """One bubble carrying N modern-shape on-disk image references."""
    return {
        "type": role_type,
        "text": text,
        "context": {
            "selectedImages": [
                {
                    "uuid": entry["uuid"],
                    "path": str(entry["path"]),
                    "dimension": {
                        "width": entry.get("width", 10),
                        "height": entry.get("height", 10),
                    },
                    "loadedAt": 1_700_000_000_000,
                    "addedWithoutMention": False,
                }
                for entry in entries
            ],
        },
    }


def _bubble_with_legacy_image(
    text: str,
    uuid: str,
    data_bytes: bytes,
    role_type: int = 1,
    width: int = 10,
    height: int = 10,
) -> dict:
    """One bubble carrying a single legacy-shape inline byte dict."""
    return {
        "type": role_type,
        "text": text,
        "images": [
            {
                "uuid": uuid,
                "dimension": {"width": width, "height": height},
                "data": {str(i): b for i, b in enumerate(data_bytes)},
            }
        ],
    }


def _bubble_with_both_shapes_same_uuid(
    text: str,
    uuid: str,
    disk_path: pathlib.Path,
    inline_bytes: bytes,
    role_type: int = 1,
) -> dict:
    """One bubble carrying the same uuid in both modern and legacy shapes.

    Used by the disk+legacy dedup regression test: ``parse_bubble_images``
    iterates ``context.selectedImages`` (disk) before the top-level
    ``images`` (inline) and first-seen-wins, so this bubble must produce
    exactly one ``chat_image`` row whose bytes came from ``disk_path``.
    """
    return {
        "type": role_type,
        "text": text,
        "context": {
            "selectedImages": [
                {
                    "uuid": uuid,
                    "path": str(disk_path),
                    "dimension": {"width": 10, "height": 10},
                    "loadedAt": 1_700_000_000_000,
                    "addedWithoutMention": False,
                }
            ],
        },
        "images": [
            {
                "uuid": uuid,
                "dimension": {"width": 10, "height": 10},
                "data": {str(i): b for i, b in enumerate(inline_bytes)},
            }
        ],
    }


class ChatIndexImageTest(unittest.TestCase):
    """End-to-end tests for the ``chat_image`` content table."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="cursor-view-images-")
        self.tmp_path = pathlib.Path(self.tmp)

        self.cursor_root = self.tmp_path / "cursor_root"
        self.cache_path = self.tmp_path / "cache" / "chat-index.sqlite3"
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        self.global_db = self.cursor_root / "User" / "globalStorage" / "state.vscdb"
        self.global_db.parent.mkdir(parents=True, exist_ok=True)
        _create_source_schema(self.global_db)

        # Separate dir for on-disk PNGs referenced by modern-shape bubbles;
        # kept out of the Cursor root so the extraction pipeline doesn't
        # trip on unexpected files inside workspaceStorage.
        self.images_dir = self.tmp_path / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)

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

    def _chat_image_rows(self, cid: str) -> list[dict[str, Any]]:
        con = sqlite3.connect(self.cache_path)
        con.row_factory = sqlite3.Row
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT session_id, position, image_index, uuid, mime_type, "
                "width, height, data FROM chat_image "
                "WHERE session_id=? ORDER BY position, image_index",
                (cid,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            con.close()

    def _chat_messages(self, cid: str) -> list[tuple[str, str]]:
        con = sqlite3.connect(self.cache_path)
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT role, content FROM chat_message "
                "WHERE session_id=? ORDER BY position",
                (cid,),
            )
            return list(cur.fetchall())
        finally:
            con.close()

    def _write_png(self, suffix: str, body: bytes = b"body") -> pathlib.Path:
        path = self.images_dir / f"image-{suffix}.png"
        path.write_bytes(PNG_PREFIX + body)
        return path

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
    # Case 4: missing on-disk image is skipped, not fatal
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


def _export_chat_fixture(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a minimal chat dict in the shape the Markdown / HTML exporters accept.

    The exporters read ``session_id``, ``date``, ``project.name``,
    ``project.rootPath``, and ``messages[*].{role,content,images}``
    directly from the dict; they do not go through the chat-index
    cache, so the A8 and A9 regression tests can feed fixtures
    in-process without building a Cursor-DB harness.
    """
    return {
        "session_id": "export-test",
        "date": 1_700_000_000,
        "project": {"name": "Test", "rootPath": "/tmp"},
        "messages": messages,
    }


class MarkdownExportImageTest(unittest.TestCase):
    """A8: Markdown export must emit a blank line between the last ``<img>`` and ``---``.

    CommonMark renders ``---`` as a thematic break only when preceded
    by a blank line; otherwise the preceding paragraph (the final
    ``<img>`` tag) consumes it as a setext-H2 underline or literal
    text. These tests pin both the image-bearing-message fix and the
    text-only byte-identity invariant so a future edit cannot silently
    regress either shape.
    """

    def test_image_message_has_blank_line_before_thematic_break(self) -> None:
        from cursor_view.export.markdown import generate_markdown

        chat = _export_chat_fixture(
            [
                {
                    "role": "user",
                    "content": "look at this",
                    "images": [
                        {"uuid": "u1", "data_uri": "data:image/png;base64,AAA"},
                    ],
                }
            ]
        )
        out = generate_markdown(chat)
        self.assertIn(
            "/>\n\n---",
            out,
            "image-bearing message must have a blank line between the "
            "last <img/> and its trailing --- thematic break",
        )
        self.assertNotIn(
            "/>\n---",
            out,
            "direct <img/>\\n--- shape breaks CommonMark thematic-break "
            "parsing (parsers fall back to setext-H2 or literal text)",
        )
        lines = out.split("\n")
        last_img_index = max(i for i, line in enumerate(lines) if line.startswith("<img"))
        self.assertEqual(
            lines[last_img_index + 1],
            "",
            "blank separator must immediately follow the last <img> line",
        )
        self.assertEqual(
            lines[last_img_index + 2],
            "---",
            "thematic break must immediately follow the blank separator",
        )

    def test_text_only_message_separator_unchanged(self) -> None:
        from cursor_view.export.markdown import generate_markdown

        chat = _export_chat_fixture(
            [{"role": "user", "content": "plain text", "images": []}]
        )
        out = generate_markdown(chat)
        # Text-only turns already have the required blank from the
        # ``content.rstrip() + ""`` pair in ``_markdown_message_lines``.
        # Pin the exact serialized shape so a future edit cannot
        # accidentally introduce a second blank or strip the one the
        # thematic break depends on.
        self.assertIn("plain text\n\n---\n", out)


class HtmlExportImageTest(unittest.TestCase):
    """A9: HTML export must wrap each ``<img>`` in a clickable anchor opening the data URI in a new tab.

    Parity with the live React gallery's one-click full-size behavior.
    The wrapper's ``href`` and the image's ``src`` must carry the same
    data URI (no double-payload; same inlined resource). Two companion
    CSS rules neutralize the global ``.message-content a:hover`` underline
    under image-wrapping anchors so hovered images do not sprout a line
    beneath them.
    """

    def test_image_message_wraps_img_in_anchor(self) -> None:
        import re
        from cursor_view.export.html import generate_standalone_html

        data_uri = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAAAA"
        chat = _export_chat_fixture(
            [
                {
                    "role": "user",
                    "content": "look",
                    "images": [{"uuid": "u1", "data_uri": data_uri}],
                }
            ]
        )
        out = generate_standalone_html(chat)

        # Anchor wrapper + <img> + close tag form a single substring
        # because ``_render_message_images_html`` joins them without
        # intervening whitespace. Regex pulls href and src so we can
        # assert they point at the same data URI.
        pattern = re.compile(
            r'<a href="(?P<href>[^"]+)" target="_blank" rel="noopener">'
            r'<img src="(?P<src>[^"]+)" alt="[^"]*" />'
            r'</a>'
        )
        match = pattern.search(out)
        self.assertIsNotNone(
            match,
            "each <img> inside .message-images must be wrapped in "
            '<a href="..." target="_blank" rel="noopener">...</a>',
        )
        self.assertEqual(
            match.group("href"),
            match.group("src"),
            "anchor href and <img> src must reference the same data URI",
        )

        self.assertIn(
            ".message-content .message-images a {",
            out,
            "CSS rule scoping link styling to .message-images must be present",
        )
        self.assertIn(
            ".message-content .message-images a:hover {",
            out,
            ":hover override must be present so the global underline "
            "does not manifest under hovered images",
        )
        # The global ``.message-content a:hover`` rule keeps its own
        # ``text-decoration: underline``; the new base+hover rules for
        # ``.message-images a`` each carry ``text-decoration: none``.
        # Including the pre-existing ``.message-content a``
        # ``text-decoration: none``, three ``text-decoration: none``
        # occurrences are the post-A9 minimum.
        self.assertGreaterEqual(
            out.count("text-decoration: none"),
            3,
            "expected at least 3 text-decoration: none CSS declarations "
            "(existing .message-content a plus A9's base and :hover)",
        )

    def test_text_only_message_has_no_anchor_wrapper(self) -> None:
        from cursor_view.export.html import generate_standalone_html

        chat = _export_chat_fixture(
            [{"role": "user", "content": "plain text", "images": []}]
        )
        out = generate_standalone_html(chat)
        self.assertNotIn(
            '<div class="message-images">',
            out,
            "text-only message must not emit a .message-images container",
        )
        self.assertNotIn(
            '<a href="data:',
            out,
            "text-only message must not emit a data-URI anchor; "
            "A9's wrapper applies only to image-bearing messages",
        )


if __name__ == "__main__":
    unittest.main()
