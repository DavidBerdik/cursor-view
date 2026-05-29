"""Single-instance lockfile coverage for the desktop launcher.

Pins the lifecycle the second-launch path depends on: a fresh acquire
writes the lock, a second acquire while a live PID holds it fails
without disturbing the file, release removes only our own lock, and a
stale lock (dead PID) is reclaimable. Also exercises the cross-platform
liveness probe directly -- on Windows that probe must never route
through ``os.kill`` / ``TerminateProcess``, so confirming our own PID
reads as alive (and the test process survives) is a real safety check.
"""

from __future__ import annotations

import json
import os
import pathlib
import socket
import tempfile
import unittest
from unittest.mock import patch

from cursor_view.desktop import single_instance


class DesktopSingleInstanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_dir = pathlib.Path(self._tmp.name)
        patcher = patch.object(
            single_instance, "cursor_view_cache_dir", return_value=self.cache_dir
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def _write_lock(self, pid: int, port: int) -> pathlib.Path:
        path = self.cache_dir / single_instance.LOCK_FILENAME
        path.write_text(
            json.dumps({"pid": pid, "port": port, "started_at_ns": 1}),
            encoding="utf-8",
        )
        return path

    def test_acquire_second_fails_release_reacquire(self) -> None:
        self.assertTrue(single_instance.acquire_lock(40001))
        lock = single_instance.read_lock()
        self.assertIsNotNone(lock)
        self.assertEqual(lock["pid"], os.getpid())
        self.assertEqual(lock["port"], 40001)

        # A live holder (our own PID) blocks a second acquire and leaves
        # the existing lock untouched.
        self.assertFalse(single_instance.acquire_lock(40002))
        self.assertEqual(single_instance.read_lock()["port"], 40001)

        single_instance.release_lock()
        self.assertIsNone(single_instance.read_lock())

        # With the lock gone, the next acquire succeeds and records the
        # new port.
        self.assertTrue(single_instance.acquire_lock(40003))
        self.assertEqual(single_instance.read_lock()["port"], 40003)

    def test_stale_lock_is_reclaimed(self) -> None:
        # A PID this large cannot name a live process on any supported
        # platform, so the lock is stale and acquire takes it over.
        self._write_lock(pid=2_000_000_000, port=40010)
        self.assertTrue(single_instance.acquire_lock(40011))
        reclaimed = single_instance.read_lock()
        self.assertEqual(reclaimed["pid"], os.getpid())
        self.assertEqual(reclaimed["port"], 40011)

    def test_release_does_not_remove_foreign_lock(self) -> None:
        path = self._write_lock(pid=os.getpid() + 1, port=40020)
        single_instance.release_lock()
        self.assertTrue(path.exists())

    def test_process_alive_self_true_bogus_false(self) -> None:
        self.assertTrue(single_instance._process_alive(os.getpid()))
        self.assertFalse(single_instance._process_alive(2_000_000_000))
        self.assertFalse(single_instance._process_alive(0))
        self.assertFalse(single_instance._process_alive(None))

    def test_notify_existing_returns_false_when_unreachable(self) -> None:
        # Bind then release a port so nothing is listening on it; the
        # focus POST must fail fast rather than hang.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]
        self.assertFalse(single_instance.notify_existing(free_port))
        self.assertFalse(single_instance.notify_existing(None))


if __name__ == "__main__":
    unittest.main()
