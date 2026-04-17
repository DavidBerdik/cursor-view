"""Optional workspace/global-DB diagnostics, gated by ``CURSOR_CHAT_DIAGNOSTICS``.

Kept in its own module so the main extraction pipeline reads as a sequence
of extraction passes without being interrupted by ~60 lines of probe code.
"""

import logging
import os
import pathlib
import sqlite3

from cursor_view.paths import global_storage_path, workspaces

logger = logging.getLogger(__name__)


def diagnostics_enabled() -> bool:
    """Return True when ``CURSOR_CHAT_DIAGNOSTICS`` is set to a truthy value."""
    return bool(os.environ.get("CURSOR_CHAT_DIAGNOSTICS"))


def dump_workspace_diagnostics(root: pathlib.Path) -> None:
    """Log a summary of tables/keys in the first workspace and the global DB.

    Intended as a one-shot probe to help users investigate why their chats
    are or aren't showing up. Wrapped in a blanket ``try/except`` at debug
    level so a failure here never blocks the real extraction pipeline.
    """
    # TODO(bug): The two ``sqlite3.connect`` calls below are not protected
    # by ``try/finally`` or ``contextlib.closing``, so if any ``cur.execute``
    # in the loops raises, the connection leaks. The outer ``except
    # Exception`` also swallows real errors at ``logger.debug`` level,
    # which hides misconfiguration when users are actively trying to
    # investigate why their chats don't show up (the whole point of this
    # probe). Fix both in a follow-up.
    try:
        first_ws = next(workspaces(root), None)
        if first_ws:
            ws_id, db = first_ws
            logger.debug("\n--- DIAGNOSTICS for workspace %s ---", ws_id)
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            cur = con.cursor()

            # List all tables
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cur.fetchall()]
            logger.debug("Tables in workspace DB: %s", tables)

            # Search for AI-related keys
            if "ItemTable" in tables:
                for pattern in ["%ai%", "%chat%", "%composer%", "%prompt%", "%generation%"]:
                    cur.execute("SELECT key FROM ItemTable WHERE key LIKE ?", (pattern,))
                    keys = [row[0] for row in cur.fetchall()]
                    if keys:
                        logger.debug("Keys matching '%s': %s", pattern, keys)

            con.close()

        # Check global storage
        global_db = global_storage_path(root)
        if global_db:
            logger.debug("\n--- DIAGNOSTICS for global storage ---")
            con = sqlite3.connect(f"file:{global_db}?mode=ro", uri=True)
            cur = con.cursor()

            # List all tables
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cur.fetchall()]
            logger.debug("Tables in global DB: %s", tables)

            # Search for AI-related keys in ItemTable
            if "ItemTable" in tables:
                for pattern in ["%ai%", "%chat%", "%composer%", "%prompt%", "%generation%"]:
                    cur.execute("SELECT key FROM ItemTable WHERE key LIKE ?", (pattern,))
                    keys = [row[0] for row in cur.fetchall()]
                    if keys:
                        logger.debug("Keys matching '%s': %s", pattern, keys)

            # Check for keys in cursorDiskKV
            if "cursorDiskKV" in tables:
                cur.execute("SELECT DISTINCT substr(key, 1, instr(key, ':') - 1) FROM cursorDiskKV")
                prefixes = [row[0] for row in cur.fetchall()]
                logger.debug("Key prefixes in cursorDiskKV: %s", prefixes)

            con.close()

        logger.debug("\n--- END DIAGNOSTICS ---\n")
    except Exception as e:
        logger.debug("Error in diagnostics: %s", e)
