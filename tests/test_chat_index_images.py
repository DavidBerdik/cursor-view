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
        self._build_index()

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
