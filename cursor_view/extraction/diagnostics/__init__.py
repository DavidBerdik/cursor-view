"""Optional probes for triaging extraction failures.

Two probe surfaces live in this subpackage:

- :func:`dump_workspace_diagnostics` (in :mod:`.workspace_dump`) is a
  coarse "what tables and key prefixes does this Cursor install have?"
  log dump gated by the ``CURSOR_CHAT_DIAGNOSTICS`` environment
  variable. The extraction pipeline calls it once at the top of
  :func:`cursor_view.extraction.extract_chats` when the variable is
  set; that is the only side-effect-on-load path the package exposes.
- :func:`trace_project_resolution` (in :mod:`.trace`) is a one-shot
  per-cid replay that answers "why did this specific chat land on
  ``(unknown)`` / ``(global)``?" by inspecting the live source DBs and
  the chat-index cache, then mapping the failure to one of the four
  documented causes.

The CLI seam lives in :mod:`.__main__` and is invoked via
``python -m cursor_view.extraction.diagnostics --cid <session_id>``.
The rule against import-time side effects (see
``.cursor/rules/python-standards.mdc``) means importing this package
must NOT touch the user's disk; that contract is honored by every
helper here -- side-effecting work runs only inside the public
functions or the CLI ``main()``.
"""

from cursor_view.extraction.diagnostics.trace import trace_project_resolution
from cursor_view.extraction.diagnostics.workspace_dump import (
    diagnostics_enabled,
    dump_workspace_diagnostics,
)

__all__ = [
    "diagnostics_enabled",
    "dump_workspace_diagnostics",
    "trace_project_resolution",
]
