"""Vendored third-party browser assets inlined into HTML exports.

Currently holds only ``mermaid.min.js`` (matched to the npm ``mermaid``
version pinned in ``frontend/package.json``). See
``cursor_view/export/mermaid.py`` for the loader that reads these
files at export time and ``.cursor/rules/mermaid-rendering.mdc`` for
the update procedure.
"""
