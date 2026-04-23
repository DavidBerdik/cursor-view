"""Serialize :class:`ImageRef` across the extraction-pipeline boundary.

The extraction pipeline (``cursor_view.extraction.*``) hands chats to
the chat-index writer (``cursor_view.chat_index.rows``) as plain
:class:`dict` / :class:`list` trees so pickling across threads and
JSON-ing for tests stay trivial. These helpers are the one-and-only
serialization pair for :class:`ImageRef` values crossing that
boundary; everything else in the codebase should import them from the
:mod:`cursor_view.images` package re-exports rather than touching the
transport dict's key layout directly.

Split off from :mod:`cursor_view.images.refs` (the ``ImageRef``
dataclass and its ``parse_bubble_images`` constructor) so ``refs.py``
stays under the <100-line target called out in the original feature
plan's §3.1.
"""

from __future__ import annotations

from typing import Any

from cursor_view.images.refs import ImageRef


def image_ref_to_transport_dict(ref: ImageRef) -> dict[str, Any]:
    """Serialize ``ref`` for the in-memory extraction pipeline."""
    return {
        "uuid": ref.uuid,
        "width": ref.width,
        "height": ref.height,
        "source_kind": ref.source_kind,
        "disk_path": ref.disk_path,
        "inline_data_dict": ref.inline_data_dict,
    }


def image_ref_from_transport_dict(d: dict[str, Any]) -> ImageRef | None:
    """Inverse of :func:`image_ref_to_transport_dict`.

    Returns ``None`` when ``uuid`` or ``source_kind`` is missing so
    callers can skip malformed entries defensively after a round-trip
    through the extraction pipeline.
    """
    uuid = d.get("uuid")
    source_kind = d.get("source_kind")
    if not isinstance(uuid, str) or source_kind not in ("disk", "inline"):
        return None
    width = d.get("width")
    height = d.get("height")
    disk_path = d.get("disk_path")
    inline_data_dict = d.get("inline_data_dict")
    return ImageRef(
        uuid=uuid,
        width=width if isinstance(width, int) else None,
        height=height if isinstance(height, int) else None,
        source_kind=source_kind,
        disk_path=disk_path if isinstance(disk_path, str) else None,
        inline_data_dict=inline_data_dict if isinstance(inline_data_dict, dict) else None,
    )
