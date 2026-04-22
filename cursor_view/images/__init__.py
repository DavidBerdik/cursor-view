"""Image attachment parsing and byte-loading helpers.

Public API:

- :class:`ImageRef` — lightweight pointer to an image attached to a
  Cursor bubble (either a disk path or an inline byte dict).
- :func:`parse_bubble_images` — walk a bubble JSON value and emit every
  referenced :class:`ImageRef`.
- :func:`load_image_bytes` — materialize an :class:`ImageRef` into
  ``(bytes, mime_type)``, sniffing MIME from magic bytes and gracefully
  skipping missing or malformed sources.
- :func:`image_ref_to_transport_dict` /
  :func:`image_ref_from_transport_dict` — transport-dict helpers used
  by the extraction pipeline and the chat-index writer so cross-package
  callers do not grow their own serialization copies.
"""

from cursor_view.images.loading import load_image_bytes
from cursor_view.images.refs import (
    ImageRef,
    image_ref_from_transport_dict,
    image_ref_to_transport_dict,
    parse_bubble_images,
)

__all__ = [
    "ImageRef",
    "image_ref_from_transport_dict",
    "image_ref_to_transport_dict",
    "load_image_bytes",
    "parse_bubble_images",
]
