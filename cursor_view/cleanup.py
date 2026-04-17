"""Process-startup housekeeping for the Cursor View cache directory."""

import logging

from cursor_view.paths import cursor_view_cache_dir

logger = logging.getLogger(__name__)


def cleanup_orphan_temp_files() -> None:
    """Remove ``chat-index.*.tmp*`` files left in the cache dir from prior
    runs that were terminated mid-rebuild (see ``ChatIndex._rebuild``).

    Sweeps only the top level of ``cursor_view_cache_dir()`` so sibling
    subdirectories such as ``webview-storage/`` (managed by WebView2) are
    untouched. Files held open by a concurrently-running instance will
    fail to delete on Windows; those errors are logged at debug level
    and skipped.

    Intended to be called exactly once per process at startup, before any
    ``ChatIndex`` rebuild can begin creating new tmp files.
    """
    cache_dir = cursor_view_cache_dir()
    removed = 0
    for path in cache_dir.glob("chat-index.*.tmp*"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            logger.debug("Could not remove orphan temp file %s", path, exc_info=True)
    if removed:
        logger.info("Removed %d orphan temp file(s) from %s", removed, cache_dir)
