"""Persistent cached chat index used by the API."""

from cursor_view.chat_index.index import ChatIndex, get_chat_index
from cursor_view.chat_index.schema import INDEX_SCHEMA_VERSION

__all__ = ["ChatIndex", "get_chat_index", "INDEX_SCHEMA_VERSION"]
