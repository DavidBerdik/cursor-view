"""File logging for desktop mode.

``run_desktop`` configures stderr logging via ``logging.basicConfig``, but
Improvement 07's windowless binary has no console on Windows, so that
output goes nowhere and a user hitting a problem has no diagnostic trail
to attach to a bug report. This module adds a rotating file handler under
the per-user cache dir (alongside, not instead of, the stderr handler)
and, in frozen builds only, routes stray ``print`` / library stdout-stderr
writes into the same log so nothing is silently lost.

Installed only from ``cursor_view/desktop/__init__.py::run_desktop``;
terminal mode keeps its stderr-only logging.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from cursor_view.paths import cursor_view_log_dir

logger = logging.getLogger(__name__)

# Mirror the format string run_desktop / create_app pass to
# logging.basicConfig so file and stderr lines look identical.
_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_MAX_BYTES = 1024 * 1024  # 1 MB cap per file
_BACKUP_COUNT = 3
_LOG_FILENAME = "desktop.log"


def configure_desktop_logging() -> Path:
    """Attach a rotating file handler to the root logger; return its path.

    Idempotent: a second call (e.g. a relaunch within the same process
    during tests) does not stack a duplicate handler for the same file.
    The handler is added to the root logger so every module logger
    (which propagates to root) lands in the file.
    """
    log_file = cursor_view_log_dir() / _LOG_FILENAME
    root = logging.getLogger()

    # FileHandler stores baseFilename = os.path.abspath(filename); match
    # that normalization so the idempotency check is reliable.
    target = os.path.abspath(str(log_file))
    for handler in root.handlers:
        if (
            isinstance(handler, RotatingFileHandler)
            and getattr(handler, "baseFilename", None) == target
        ):
            return log_file

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    file_handler.setLevel(logging.INFO)
    # Ensure the root logger actually emits INFO; basicConfig sets this,
    # but configure_desktop_logging may run before it on some paths.
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    root.addHandler(file_handler)

    logger.info("Desktop logging to %s", log_file)
    return log_file


class _StreamToLogger:
    """Minimal file-like object that forwards writes to a logger.

    Used only for the frozen-build stdout/stderr capture. Buffers partial
    writes until a newline so multi-call ``print`` statements log as one
    line, and drops blank lines so the log is not padded with the empty
    trailing fragments ``print`` emits.
    """

    def __init__(self, target_logger: logging.Logger, level: int) -> None:
        self._logger = target_logger
        self._level = level
        self._buffer = ""

    def write(self, message: object) -> None:
        if not isinstance(message, str):
            return
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip()
            if line:
                self._logger.log(self._level, "%s", line)

    def flush(self) -> None:
        remainder = self._buffer.strip()
        self._buffer = ""
        if remainder:
            self._logger.log(self._level, "%s", remainder)

    def isatty(self) -> bool:
        return False


def redirect_stdio_to_logging() -> None:
    """Route ``sys.stdout`` / ``sys.stderr`` into the logger in frozen builds.

    No-op when not frozen (``sys.frozen`` unset) so dev launches keep
    their real console. In the windowless PyInstaller binary the standard
    streams are otherwise ``None`` (or a dead console), so a library that
    ``print``s would either crash or vanish; routing them through the
    logger lands that output in ``desktop.log``. Idempotent. The root
    logger's stderr ``StreamHandler`` captured the original stream at
    ``basicConfig`` time, so this redirect cannot feed back into itself.
    """
    if not getattr(sys, "frozen", False):
        return
    if isinstance(sys.stdout, _StreamToLogger) and isinstance(
        sys.stderr, _StreamToLogger
    ):
        return
    sys.stdout = _StreamToLogger(logging.getLogger("cursor_view.stdout"), logging.INFO)
    sys.stderr = _StreamToLogger(logging.getLogger("cursor_view.stderr"), logging.ERROR)
