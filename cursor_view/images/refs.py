"""Parse image attachment references out of Cursor bubble JSON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ImageRef:
    """Lightweight pointer to an image attached to a Cursor bubble.

    Two source shapes exist in Cursor's on-disk format:

    - ``source_kind="disk"`` — the modern shape stored under
      ``bubble.context.selectedImages``; ``disk_path`` is the absolute
      filesystem path to the image file.
    - ``source_kind="inline"`` — the legacy shape stored under
      ``bubble.images``; ``inline_data_dict`` is the string-keyed
      ``Uint8Array`` serialization ``{"0": byte, "1": byte, ...}``.

    Bytes are resolved lazily by :func:`cursor_view.images.loading.load_image_bytes`
    so a ref itself stays cheap to pass around.
    """

    uuid: str
    width: int | None
    height: int | None
    source_kind: Literal["disk", "inline"]
    disk_path: str | None = None
    inline_data_dict: dict[str, int] | None = None


def _dimension_pair(dimension: Any) -> tuple[int | None, int | None]:
    if not isinstance(dimension, dict):
        return (None, None)
    width = dimension.get("width")
    height = dimension.get("height")
    return (
        width if isinstance(width, int) else None,
        height if isinstance(height, int) else None,
    )


def parse_bubble_images(bubble: dict[str, Any]) -> list[ImageRef]:
    """Return every image attachment referenced by ``bubble``.

    Walks both the modern ``context.selectedImages`` (on-disk path) and
    the legacy top-level ``images`` (inline ``Uint8Array`` dict) shapes.
    Dedups by ``uuid`` with first-seen-wins, iterating disk entries
    first so a bubble that carries the same image in both shapes rides
    the live disk file rather than re-parsing the byte dict.
    """
    seen: set[str] = set()
    refs: list[ImageRef] = []

    context = bubble.get("context")
    selected_images = context.get("selectedImages") if isinstance(context, dict) else None
    if isinstance(selected_images, list):
        for entry in selected_images:
            if not isinstance(entry, dict):
                continue
            uuid = entry.get("uuid")
            path = entry.get("path")
            if not isinstance(uuid, str) or not isinstance(path, str) or not path:
                continue
            if uuid in seen:
                continue
            width, height = _dimension_pair(entry.get("dimension"))
            refs.append(
                ImageRef(
                    uuid=uuid,
                    width=width,
                    height=height,
                    source_kind="disk",
                    disk_path=path,
                )
            )
            seen.add(uuid)

    inline_images = bubble.get("images")
    if isinstance(inline_images, list):
        for entry in inline_images:
            if not isinstance(entry, dict):
                continue
            uuid = entry.get("uuid")
            data = entry.get("data")
            if not isinstance(uuid, str) or not isinstance(data, dict):
                continue
            if uuid in seen:
                continue
            width, height = _dimension_pair(entry.get("dimension"))
            refs.append(
                ImageRef(
                    uuid=uuid,
                    width=width,
                    height=height,
                    source_kind="inline",
                    inline_data_dict=data,
                )
            )
            seen.add(uuid)

    return refs


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
