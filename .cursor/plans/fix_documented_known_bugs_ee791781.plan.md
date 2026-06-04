---
name: fix documented known bugs
overview: Fix all three live TODO(bug) defects documented in known-bugs.mdc — the desktop single-instance lock write-failure (made fatal), the transient source-DB read failure that misclassifies chats as deletions (carry-forward at all read-failure sites), and the malformed-allComposers crash (graceful skip) — each with a regression test and the required rule/doc sync.
todos:
  - id: bug1-lock
    content: "Bug 1: add AcquireResult tri-state + bool _write_lock in single_instance.py; wire run_desktop WRITE_FAILED -> show_startup_error + exit 1; update/add single-instance tests; sync desktop-mode.mdc"
    status: pending
  - id: bug2-carryforward
    content: "Bug 2: add _carry_forward_cached_rows to types.py; wire it into workspace_db.py (return None on fail) and all three global_db.py read-failure sites; add three transient-read-failure regression tests to test_chat_index_incremental.py"
    status: pending
  - id: bug3-allcomposers
    content: "Bug 3: guard the allComposers loop in inference.py to skip non-dict / composerId-less entries; add WorkspaceInfoMalformedComposerTest to test_known_bug_fixes.py"
    status: pending
  - id: rule-sync
    content: "Update known-bugs.mdc: remove the three live markers, move them to the retired list (12 -> 15) with regression-test citations"
    status: pending
  - id: verify
    content: "Run python -m unittest discover -s tests and grep TODO(bug): to confirm zero real markers remain"
    status: pending
isProject: false
---

# Fix the three documented known bugs

Three live `# TODO(bug):` defects are documented in [.cursor/rules/known-bugs.mdc](.cursor/rules/known-bugs.mdc) and confirmed in the tree (4 markers, since Bug 2 spans two files). This plan fixes all three, pins each with a regression test, and syncs the affected rules per [comments-style.mdc](.cursor/rules/comments-style.mdc) "Rule drift".

Confirmed design decisions (from clarifying questions):
- Bug 1 lock write-failure is **fatal**: route to the native startup-error window and exit non-zero rather than launch a second un-coordinated instance.
- Bug 2 fixes **all** read-failure sites (connection-open + both inner global reads + workspace fetch), not only the two marked ones.

## Bug 1 — Single-instance lock write-failure (fatal)

Today [`acquire_lock`](cursor_view/desktop/single_instance.py) returns `True` unconditionally even when `_write_lock` swallowed an `OSError`, so `run_desktop` believes it holds a lock that was never written and every later launch becomes a "first" instance.

Edit [cursor_view/desktop/single_instance.py](cursor_view/desktop/single_instance.py):
- Add `import enum` and a tri-state result so the launcher can tell "another live instance holds it" (exit 0 + focus) from "we could not write our lock" (fatal):

```python
class AcquireResult(enum.Enum):
    ACQUIRED = "acquired"
    HELD = "held"
    WRITE_FAILED = "write_failed"
```

- Change `_write_lock(port) -> bool`: return `False` (instead of silently returning) in the `except OSError` branch, `True` on success. Keep the existing lazy `%s` warning.
- Rewrite `acquire_lock(port) -> AcquireResult` (drop the `# TODO(bug):` block at line 155):

```python
def acquire_lock(port: int) -> AcquireResult:
    existing = read_lock()
    if existing is not None and _process_alive(existing.get("pid")):
        logger.info("Desktop lock held by live PID %s on port %s",
                    existing.get("pid"), existing.get("port"))
        return AcquireResult.HELD
    if _write_lock(port):
        return AcquireResult.ACQUIRED
    return AcquireResult.WRITE_FAILED
```

Edit [cursor_view/desktop/__init__.py](cursor_view/desktop/__init__.py):
- Add `AcquireResult` to the `single_instance` import block.
- Replace the `if not acquire_lock(port):` block (around line 134) with a tri-state dispatch. The `HELD` branch keeps today's notify-and-exit-0 behavior; the new `WRITE_FAILED` branch closes the just-bound socket and calls `show_startup_error(...)` (already imported), which is safe here because the main `webview.start` has not run yet:

```python
lock_result = acquire_lock(port)
if lock_result is AcquireResult.HELD:
    existing = read_lock()
    if existing is not None:
        notify_existing(existing.get("port"))
    logger.info("Another Cursor View desktop instance is running; focusing it")
    server.server_close()
    sys.exit(0)
if lock_result is AcquireResult.WRITE_FAILED:
    server.server_close()
    show_startup_error(
        "Cursor View could not create its single-instance lock file, so it "
        "cannot guarantee only one window is open. The cache directory may be "
        "read-only or the disk may be full."
    )
    sys.exit(1)
```

Tests — [tests/test_desktop_single_instance.py](tests/test_desktop_single_instance.py):
- Update the three existing assertions that treat the return as a bool to compare against the enum (`AcquireResult.ACQUIRED` for fresh/stale/non-object acquires; `AcquireResult.HELD` for the live-holder second acquire).
- Add `test_write_lock_returns_false_on_oserror`: patch `pathlib.Path.write_text` to raise `OSError`, assert `_write_lock(...)` is `False` and no lockfile is left behind.
- Add `test_acquire_reports_write_failed`: patch `single_instance._write_lock` to return `False`, assert `acquire_lock(...)` is `AcquireResult.WRITE_FAILED` and `read_lock()` is `None` (no false claim of ownership). The `run_desktop` wiring itself stays read-verified, consistent with how the desktop launcher is otherwise untested.

Doc sync — [.cursor/rules/desktop-mode.mdc](.cursor/rules/desktop-mode.mdc): in "Single-instance lockfile" and "Startup errors go to a native window", note that a lock-write failure is now a fatal startup error (routes to `show_startup_error`, exit 1) and that `acquire_lock` returns the `AcquireResult` tri-state.

## Bug 2 — Transient source-DB read failure misclassified as deletions

A momentary `sqlite3.DatabaseError` (DB locked while Cursor writes, transient I/O) currently makes a read site return empty/early while the DB file still exists. `_process_deletions` in [cursor_view/cache/diff/propagation.py](cursor_view/cache/diff/propagation.py) then sees the DB's cached `source_row` keys as vanished and folds their composers into `deleted_cids`, so the chats disappear from the index until a later refresh. Fix by carrying the cached rows forward (treat "couldn't read" as "unchanged") at every read-failure site.

Add a shared helper to [cursor_view/cache/diff/types.py](cursor_view/cache/diff/types.py) next to `_record`:

```python
def _carry_forward_cached_rows(
    snapshot: dict[SourceKey, SourceRowRecord],
    cached: dict[SourceKey, tuple[str, str]],
    db_path_str: str,
) -> None:
    for sk, (row_hash, composer_id) in cached.items():
        if sk.db_path != db_path_str or sk in snapshot:
            continue
        snapshot[sk] = SourceRowRecord(
            db_path=sk.db_path, table_name=sk.table_name, key=sk.key,
            row_hash=row_hash, composer_id=composer_id,
        )
```

The `sk in snapshot` guard makes this safe to call from a sub-diff even when a sibling sub-diff already recorded fresh rows for the same `db_path` (real changes are preserved, only gaps are backfilled). `cached` is `SourceKey -> (row_hash, composer_id)`, per [cache_state.py](cursor_view/cache/diff/cache_state.py).

Edit [cursor_view/cache/diff/workspace_db.py](cursor_view/cache/diff/workspace_db.py):
- `_fetch_workspace_item_rows(db) -> list[tuple[str, Any]] | None`: return `None` (was `[]`) in the `except sqlite3.DatabaseError` branch so the caller can distinguish "read failed" from "genuinely empty"; drop the `# TODO(bug):` block (lines 71-80).
- In `_diff_workspace_db`, after `rows = _fetch_workspace_item_rows(db)`:

```python
if rows is None:
    _carry_forward_cached_rows(dirty.source_row_snapshot, cached, db_path_str)
    return
```

Edit [cursor_view/cache/diff/global_db.py](cursor_view/cache/diff/global_db.py):
- `_diff_global_db`: in the open-failure `except` (drop the `# TODO(bug):` block at lines 123-132) call `_carry_forward_cached_rows(dirty.source_row_snapshot, cached, db_path_str)` before `return`.
- `_diff_global_cursor_disk_kv`: in its `except sqlite3.DatabaseError`, carry forward before `return`. Leave the legitimate "table absent" path (`if not cur.fetchone(): return`) untouched — a missing table is a real structural state, not a read error.
- `_diff_global_legacy_chatdata`: in its `except sqlite3.DatabaseError`, carry forward before `return` (the `row is None` legitimate-empty path stays as-is).
- Import `_carry_forward_cached_rows` from `cursor_view.cache.diff.types` in both modules.

Tests — add to [tests/test_chat_index_incremental.py](tests/test_chat_index_incremental.py) (per [project-layout.mdc](.cursor/rules/project-layout.mdc): refresh-path changes land with a synthetic-Cursor-DB regression test here). Each builds the cache cleanly, then refreshes once while forcing a read failure, asserting the affected cids are NOT in `dirty.deleted_cids` and still present in `chat_summary`, then a clean refresh keeps them:
- `test_transient_global_open_failure_does_not_delete_chats`: patch `cursor_view.cache.diff.global_db.sqlite3.connect` to raise `sqlite3.OperationalError("database is locked")`.
- `test_transient_workspace_read_failure_does_not_delete_chats`: seed a workspace-resident chat (pane-view key), patch `cursor_view.cache.diff.workspace_db.sqlite3.connect` to raise.
- `test_transient_global_inner_read_failure_does_not_delete_chats`: a small connection/cursor double whose `cursor().execute` raises `DatabaseError` only when the SQL contains `bubbleId:` (so `OpenProcess` succeeds but the cursorDiskKV data read fails), patched onto `global_db.sqlite3.connect`.

## Bug 3 — Malformed allComposers crash

In [cursor_view/projects/inference.py](cursor_view/projects/inference.py) the `allComposers` loop subscripts `c["composerId"]` and assumes `c` is a dict; one partial/non-dict entry raises `KeyError`/`TypeError`, which bypasses the only `except` (`sqlite3.DatabaseError`) and aborts `workspace_info`, so Pass 1 surfaces none of that workspace's titles/metadata.

Edit the loop (drop the `# TODO(bug):` block at lines 120-128) to degrade gracefully like every other read in the function:

```python
for c in cd.get("allComposers", []):
    if not isinstance(c, dict):
        continue
    cid = c.get("composerId")
    if not cid:
        continue
    comp_meta[cid] = {
        "title": c.get("name", "(untitled)"),
        "createdAt": c.get("createdAt"),
        "lastUpdatedAt": c.get("lastUpdatedAt"),
    }
```

Test — add `WorkspaceInfoMalformedComposerTest` to [tests/test_known_bug_fixes.py](tests/test_known_bug_fixes.py) (already the home for projects-module bug-fix regressions). Build a workspace `state.vscdb` whose `ItemTable` `composer.composerData` holds `allComposers` mixing a non-dict entry, a dict missing `composerId`, and one valid entry; call `workspace_info(db)` and assert it returns without raising, the valid composer's metadata is present, and the malformed entries were skipped.

## Rule sync — known-bugs.mdc

Edit [.cursor/rules/known-bugs.mdc](.cursor/rules/known-bugs.mdc):
- Change "Three live `# TODO(bug):` markers are in the tree at present:" to state there are no live markers, and remove the three live bullets.
- Change "Twelve retired examples now live in git history:" to "Fifteen retired examples...", adding one retired bullet per fix (symptom, cause, the closing change, and the regression-test citation) in the established style.

## Verification

Run the full suite (must stay green per [project-layout.mdc](.cursor/rules/project-layout.mdc)):

```
python -m unittest discover -s tests
```

Then `rg "TODO\(bug\):" --glob '*.py'` should report only the two prose "Not a `TODO(bug):`" hits in `images/loading.py` and `cache/delta/propagation.py` — zero real markers remaining.