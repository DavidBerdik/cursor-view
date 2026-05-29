"""Single-instance enforcement for the desktop launcher.

Once desktop mode is the default, double-clicking the icon twice (or
re-launching from a file association) is common and would otherwise
spawn a second Flask server + window on a second random port, neither
aware of the other's window state. This module makes the second launch
detect the first via a lockfile, ask it to focus its window over a
loopback IPC, and exit.

The lockfile lives at ``cursor_view_cache_dir() / "desktop.lock"`` and
holds ``{pid, port, started_at_ns}`` JSON. Liveness of the recorded PID
is what decides whether a lock is stale:

- POSIX uses ``os.kill(pid, 0)``, the canonical existence probe.
- Windows must **not** use ``os.kill(pid, 0)``: CPython implements
  ``os.kill`` on Windows by opening the process and calling
  ``TerminateProcess(handle, sig)``, so a "probe" with ``sig=0`` would
  terminate the target. We open the process with
  ``PROCESS_QUERY_LIMITED_INFORMATION`` via :mod:`ctypes` and read its
  exit code instead -- a read-only existence check.

The module deliberately does not import :mod:`webview`; the
``POST /__desktop_focus__`` route that consumes ``notify_existing`` is
registered in :mod:`cursor_view.desktop` where the window handle lives,
keeping this module import-safe for the unit tests.
"""

import json
import logging
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

from cursor_view.paths import cursor_view_cache_dir

logger = logging.getLogger(__name__)

LOCK_FILENAME = "desktop.lock"
FOCUS_ROUTE = "/__desktop_focus__"


def _lock_path() -> pathlib.Path:
    """Return the path to the single-instance lockfile."""
    return cursor_view_cache_dir() / LOCK_FILENAME


def read_lock() -> dict | None:
    """Return the parsed lockfile contents, or None if missing / malformed."""
    path = _lock_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_lock(port: int) -> None:
    """Write this process's ``{pid, port, started_at_ns}`` to the lockfile."""
    path = _lock_path()
    payload = {
        "pid": os.getpid(),
        "port": int(port),
        "started_at_ns": time.time_ns(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        logger.warning("Failed to write desktop lock to %s", path, exc_info=True)


def _process_alive(pid: int | None) -> bool:
    """Return True if ``pid`` names a live process, cross-platform.

    A dead or reused-then-dead PID makes the lock stale and reclaimable.
    PID reuse by an unrelated live process is an accepted false positive
    (the same limitation ``os.kill(pid, 0)`` carries); the worst case is
    the new launch focuses nothing and exits, never data loss.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        return _process_alive_windows(pid)
    return _process_alive_posix(pid)


def _process_alive_posix(pid: int) -> bool:
    """POSIX liveness probe via the signal-0 no-op."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by another user; still a live process.
        return True
    return True


def _process_alive_windows(pid: int) -> bool:
    """Windows liveness probe that never terminates the target.

    ``os.kill(pid, 0)`` is unsafe on Windows (it routes through
    ``TerminateProcess``), so open the process read-only and check that
    its exit code is still ``STILL_ACTIVE``.
    """
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        process_query_limited_information, False, pid
    )
    if not handle:
        # Access-denied means the process exists but is not ours to open;
        # any other error (notably invalid-parameter) means it is gone.
        return ctypes.get_last_error() == error_access_denied
    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return exit_code.value == still_active
        return True
    finally:
        kernel32.CloseHandle(handle)


def acquire_lock(port: int) -> bool:
    """Claim the single-instance lock for ``port``.

    Returns True and writes our lock when no fresh lock exists (or the
    existing one names a dead process, i.e. is stale). Returns False
    without touching the file when a live instance already holds it, so
    the caller can :func:`notify_existing` and exit.
    """
    existing = read_lock()
    if existing is not None and _process_alive(existing.get("pid")):
        logger.info(
            "Desktop lock held by live PID %s on port %s",
            existing.get("pid"),
            existing.get("port"),
        )
        return False
    _write_lock(port)
    return True


def release_lock() -> None:
    """Remove the lockfile, but only if it is still ours.

    Guarding on PID avoids deleting a lock a newer instance wrote after
    we were declared stale and reclaimed.
    """
    lock = read_lock()
    if lock is not None and lock.get("pid") == os.getpid():
        try:
            _lock_path().unlink()
        except OSError:
            logger.warning(
                "Failed to remove desktop lock at %s", _lock_path(), exc_info=True
            )


def notify_existing(port_from_lock: int | None) -> bool:
    """Ask the instance on ``port_from_lock`` to focus its window.

    POSTs to the loopback focus route with a short timeout. Returns True
    on a 2xx, False on any connection / timeout error (which also serves
    as the Windows fallback liveness signal: a recorded PID that is gone
    will refuse the connection).
    """
    if not port_from_lock:
        return False
    url = f"http://127.0.0.1:{port_from_lock}{FOCUS_ROUTE}"
    request = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=2.0) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError) as exc:
        logger.info(
            "Could not notify existing instance on port %s: %s",
            port_from_lock,
            exc,
        )
        return False
