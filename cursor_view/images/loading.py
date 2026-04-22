"""Materialize ImageRef bytes + sniff MIME from magic bytes."""

from __future__ import annotations

import logging

from cursor_view.images.refs import ImageRef

logger = logging.getLogger(__name__)


def _sniff_mime(data: bytes) -> str:
    """Infer an ``image/*`` MIME type from ``data``'s magic bytes.

    Stdlib-only on purpose — Pillow / ``imghdr`` / ``python-magic`` are
    heavier than the four MIME types Cursor has ever emitted warrant,
    and pulling them in would bloat the PyInstaller bundle.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xFF\xD8\xFF"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    logger.debug(
        "Unknown image magic %r for first 16 bytes; defaulting to image/png",
        data[:16],
    )
    return "image/png"


def load_image_bytes(ref: ImageRef) -> tuple[bytes, str] | None:
    """Return ``(raw_bytes, mime_type)`` for ``ref`` or ``None`` on failure.

    Returns ``None`` for a missing on-disk file or a malformed inline
    byte dict — callers treat that as "skip this image, keep the
    message" rather than propagating the error. Not a ``TODO(bug):``
    because the graceful skip is intentional, not known-broken
    behavior.
    """
    if ref.source_kind == "disk":
        if not ref.disk_path:
            logger.warning("Image ref %s has source_kind=disk but no disk_path", ref.uuid)
            return None
        try:
            with open(ref.disk_path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            logger.warning(
                "Image file missing for %s: %s (%s)", ref.uuid, ref.disk_path, exc
            )
            return None
        return (data, _sniff_mime(data))

    if ref.source_kind == "inline":
        inline = ref.inline_data_dict
        if not isinstance(inline, dict):
            logger.warning(
                "Image ref %s has source_kind=inline but no inline_data_dict", ref.uuid
            )
            return None
        try:
            data = bytes(inline[str(i)] for i in range(len(inline)))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Malformed inline image data for %s: %s", ref.uuid, exc
            )
            return None
        return (data, _sniff_mime(data))

    logger.warning("Unknown image source_kind %r for %s", ref.source_kind, ref.uuid)
    return None
