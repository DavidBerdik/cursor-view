"""Cursor source-database access helpers.

Internals are split by source table:

- :mod:`cursor_view.sources.sqlite_util` — ``j()`` and the shared
  ``cursorDiskKV`` connection handshake.
- :mod:`cursor_view.sources.bubbles` — ``bubbleId:*`` iterators.
- :mod:`cursor_view.sources.composer_data` — ``composerData:*``
  iterators and the ``fullConversationHeadersOnly`` order map.
- :mod:`cursor_view.sources.item_table` — workspace / global
  ``ItemTable`` chat-shaped reads.

Future Cursor data sources (filesystem-backed caches, IPC-based
sources, etc.) should land alongside these as new submodules.
"""
