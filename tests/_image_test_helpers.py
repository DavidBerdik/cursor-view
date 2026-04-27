"""Shared fixtures + base harness for the image-attachment test sibling modules.

Leading-underscore name keeps this module out of ``unittest.discover``'s
default ``test_*.py`` pattern so it is imported as a helper rather than
run as a test module.

Consumers:
- ``tests/test_chat_index_images_core.py``       -- original end-to-end
  rebuild scenarios (modern-shape rebuild, legacy-shape rebuild,
  modification-via-incremental-apply, multiple images round-trip) plus
  the two original coalescer unit cases.
- ``tests/test_chat_index_images_regressions.py`` -- E1 regressions
  on ``ChatIndexImageTest`` (A1, A4, B1, dedup, data_uri round-trip,
  E1-extended missing-disk skip) plus ``test_coalesce_post_loop_placeholder_clear``.
- ``tests/test_chat_index_images_exports.py``     -- A8 Markdown export
  and A9 HTML export regression cases.

The full coverage context for each scenario lives in
``.cursor/plans/image_attachment_support_55e4fd2e.plan.md`` section 11
(original five) and
``.cursor/plans/image_attachment_post-impl_followup_2b026aae.plan.md``
section E1 (regression set).
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


def _export_chat_fixture(
    messages: list[dict[str, Any]],
    *,
    title: str = "",
) -> dict[str, Any]:
    """Return a minimal chat dict in the shape the Markdown / HTML exporters accept.

    The exporters read ``session_id``, ``date``, ``project.name``,
    ``project.rootPath``, ``title``, and ``messages[*].{role,content,images}``
    directly from the dict; they do not go through the chat-index
    cache, so the A8 / A9 image-export and chat-title export
    regressions can feed fixtures in-process without building a
    Cursor-DB harness. ``title`` defaults to ``""`` so existing
    image regression callers continue to exercise the title-absent
    legacy header shape unchanged.
    """
    return {
        "session_id": "export-test",
        "date": 1_700_000_000,
        "project": {"name": "Test", "rootPath": "/tmp"},
        "title": title,
        "messages": messages,
    }


class BaseChatIndexImageTest(unittest.TestCase):
    """Synthetic-Cursor-DB harness shared by the core and regressions sibling modules.

    Mirrors ``test_chat_index_incremental``'s layout: four ``cursor_root``
    patches aim every caller at a temp directory so the tests never
    touch the developer's real Cursor state.
    """

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
