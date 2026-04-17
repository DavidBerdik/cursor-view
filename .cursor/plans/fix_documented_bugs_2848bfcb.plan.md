---
name: fix documented bugs
overview: "Fix the five `TODO(bug):` issues documented during the refactor: two user-specific hardcoded values in the project-name pipeline, one cookie-on-cancel frontend bug, and two SQLite connection-leak patterns (one in `sources/sqlite_data.py`, one in `extraction/diagnostics.py`). Each fix is a small, isolated change; no refactor is in scope here."
todos:
  - id: bug1_chat_format_saharmor
    content: Delete the Documents/codebase elif branch + 'cursor-view' literal fallback + its TODO(bug) comment in cursor_view/chat_format.py
    status: pending
  - id: bug2_inference_known_projects
    content: Delete the hardcoded known_projects list and its loop + TODO(bug) comment in cursor_view/projects/inference.py; reword the orphaned trailing comment
    status: pending
  - id: bug3_export_warning_cookie
    content: Gate the persist() call on `confirmed` in frontend/src/hooks/useExportFlow.js handleWarningConfirm, collapse the two confirmed checks, remove the TODO(bug) comment
    status: pending
  - id: bug4_sqlite_leak
    content: Wrap iter_bubbles_from_disk_kv and iter_composer_data in cursor_view/sources/sqlite_data.py with the con=None + outer try/finally pattern used by iter_chat_from_item_table; remove both TODO(bug) comments and the now-redundant inline con.close() calls
    status: pending
  - id: bug5_diagnostics_rewrite
    content: Rewrite cursor_view/extraction/diagnostics.py to split into _dump_first_workspace/_dump_global_storage helpers using contextlib.closing; bump routine messages to logger.info; replace the except-clause logger.debug with logger.exception; remove the TODO(bug) comment
    status: pending
isProject: false
---

## Goals

- Fix every `TODO(bug):` marker planted during the refactor.
- Remove each marker alongside the fix so the codebase doesn't accumulate stale "known bug" annotations.
- No new features, no refactors, no dependency changes.

## Quick pre-flight

Run this to confirm the marker inventory matches the plan before starting:

```powershell
rg -n --hidden "TODO\(bug\):" .
```

Expected sites (post-refactor):

- [cursor_view/chat_format.py](cursor_view/chat_format.py) line 113
- [cursor_view/projects/inference.py](cursor_view/projects/inference.py) line 57
- [cursor_view/sources/sqlite_data.py](cursor_view/sources/sqlite_data.py) lines 109 and 227
- [cursor_view/extraction/diagnostics.py](cursor_view/extraction/diagnostics.py) line 29
- [frontend/src/hooks/useExportFlow.js](frontend/src/hooks/useExportFlow.js) line 77

After all five todos are complete, the same grep should return zero matches.

## Bug 1: hardcoded Documents/codebase fallback in `chat_format.py`

### Where

[cursor_view/chat_format.py](cursor_view/chat_format.py), lines 113-129.

### Current code

```103:129:cursor_view/chat_format.py
                # Only use the new name if it's meaningful
                if (
                    project_name
                    and project_name != "Unknown Project"
                    and project_name != username
                    and project_name not in ["Documents", "Downloads", "Desktop"]
                ):

                    logger.debug("Improved project name from '%s' to '%s'", current_name, project_name)
                    project["name"] = project_name
                # TODO(bug): This branch was written against one developer's
                # ``/Users/saharmor/Documents/codebase/<X>`` layout. It only
                # triggers on macOS paths that match the current user's home
                # ("username" above), so it effectively runs for any user who
                # happens to keep projects under ``~/Documents/codebase/``, and
                # the literal ``"cursor-view"`` fallback is almost certainly
                # wrong for anyone else. Leave the behavior unchanged here and
                # revisit as a standalone fix (do not silently delete this path
                # or the hard-coded default).
                elif project.get("rootPath").startswith(f"/Users/{username}/Documents/codebase/"):
                    # Special case for /Users/saharmor/Documents/codebase/X
                    parts = project.get("rootPath").split("/")
                    if len(parts) > 5:  # /Users/username/Documents/codebase/X
                        project["name"] = parts[5]
                        logger.debug("Set project name to specific codebase subdirectory: %s", parts[5])
                    else:
                        project["name"] = "cursor-view"  # Current project as default
```

### Why the fix is safe

The `elif` branch is effectively dead for every user. It only fires when the extracted `project_name` is one of `None` / `"Unknown Project"` / `username` / `"Documents"` / `"Downloads"` / `"Desktop"` AND the rootPath is under `~/Documents/codebase/`. For any such rootPath (e.g. `/Users/me/Documents/codebase/myproj`), `extract_project_name_from_path` already extracts `myproj` via its own Documents/codebase detection at [cursor_view/projects/inference.py](cursor_view/projects/inference.py) lines 76-84, so the `if` branch on line 104 succeeds and the `elif` is never reached.

The only way the `elif` can fire is on pathological inputs (e.g. rootPath is literally `/Users/me/Documents/codebase/Documents`). For those, the behavior of picking `parts[5]` or falling back to the literal string `"cursor-view"` is wrong.

### Fix

Delete the entire `elif` block and the `TODO(bug)` comment. Net result:

```python
                # Only use the new name if it's meaningful
                if (
                    project_name
                    and project_name != "Unknown Project"
                    and project_name != username
                    and project_name not in ["Documents", "Downloads", "Desktop"]
                ):

                    logger.debug("Improved project name from '%s' to '%s'", current_name, project_name)
                    project["name"] = project_name
```

### Verification

1. Grep: `rg "saharmor|cursor-view" cursor_view/chat_format.py` must return zero matches.
2. `python -c "import ast; ast.parse(open('cursor_view/chat_format.py', encoding='utf-8').read())"` passes.
3. Manually construct a chat with `project.rootPath = "/Users/me/Documents/codebase/myproj"` and confirm `format_chat_for_frontend` returns `project.name == "myproj"` (behavior before the change).

## Bug 2: hardcoded `known_projects` list in `projects/inference.py`

### Where

[cursor_view/projects/inference.py](cursor_view/projects/inference.py), lines 56-71.

### Current code

```56:71:cursor_view/projects/inference.py
    if username_index >= 0 and username_index + 1 < len(path_parts):
        # TODO(bug): This ``known_projects`` list was populated from the
        # original author's personal repos ("genaisf", "universal-github",
        # "inquiry", etc.) and has no general meaning. Picking any of these
        # names as the project regardless of where they appear in the path
        # is a hardcoded bias that can mislabel unrelated chats. Revisit as
        # a standalone fix.
        known_projects = ["genaisf", "cursor-view", "cursor", "cursor-apps", "universal-github", "inquiry"]

        # Look at the most specific/deepest part of the path first
        for i in range(len(path_parts) - 1, username_index, -1):
            if path_parts[i] in known_projects:
                project_name = path_parts[i]
                if debug:
                    logger.debug("Found known project name from specific list: %s", project_name)
                break
```

### Why the fix is safe

The function is only called with **project root directory paths**, never file paths. For a root like `/Users/me/dev/cursor-view`, removing the list means we fall through to:

1. The `Documents/codebase` special-case (lines 76-84) — doesn't apply here (no Documents/codebase in path).
2. The generic `path_parts[-1]` fallback (lines 87-90) — returns `"cursor-view"`.

Same result. The only scenarios where removing the list changes behavior are when one of the six listed names appears in a non-tail position of the project root path (e.g. `/Users/me/cursor-view/sub-project`), in which case the current behavior of preferring the known name over the actual trailing segment is itself wrong (the project really is `sub-project`).

### Fix

Delete the `TODO(bug)` comment, the `known_projects = [...]` line, and the `for` loop that consults it. The block becomes:

```python
    if username_index >= 0 and username_index + 1 < len(path_parts):
        # If no known project found, use the last part of the path as it's likely the project directory
        if not project_name and len(path_parts) > username_index + 1:
            # Check if we have a structure like /Users/username/Documents/codebase/project_name
            if "Documents" in path_parts and "codebase" in path_parts:
                ...
```

The comment `# If no known project found, use the last part...` that follows now reads slightly off (there's no "known project" check anymore). Reword it to `# Use the last part of the path as it's likely the project directory`.

### Verification

1. Grep: `rg "known_projects|genaisf|universal-github|inquiry" cursor_view/` must return zero matches.
2. Unit check (manual REPL):
   - `extract_project_name_from_path("/Users/me/dev/cursor-view")` returns `"cursor-view"`.
   - `extract_project_name_from_path("/Users/me/Documents/codebase/myproj")` returns `"myproj"`.
   - `extract_project_name_from_path("/Users/me")` returns `"Home Directory"`.

## Bug 3: warning cookie persists on Cancel

### Where

[frontend/src/hooks/useExportFlow.js](frontend/src/hooks/useExportFlow.js), lines 73-91.

### Current code

```73:91:frontend/src/hooks/useExportFlow.js
  const handleWarningConfirm = useCallback(
    (confirmed) => {
      setWarningDialogOpen(false);

      // TODO(bug): persists the cookie regardless of `confirmed`, so a
      // user who ticks "Don't show this warning again" and then clicks
      // Cancel still has the preference recorded. Original behavior was
      // duplicated across both pages before this hook was introduced;
      // preserve it for now and fix in a dedicated change. The guard
      // should be `if (confirmed) { persist(); }`.
      persist();

      if (confirmed && pendingSessionId) {
        proceed(pendingSessionId, format);
      }
      setPendingSessionId(null);
    },
    [persist, pendingSessionId, format, proceed],
  );
```

### Fix

Gate `persist()` on `confirmed`, drop the `TODO(bug)` comment:

```jsx
  const handleWarningConfirm = useCallback(
    (confirmed) => {
      setWarningDialogOpen(false);

      if (confirmed) {
        persist();
        if (pendingSessionId) {
          proceed(pendingSessionId, format);
        }
      }
      setPendingSessionId(null);
    },
    [persist, pendingSessionId, format, proceed],
  );
```

Collapsing the two `confirmed` checks into one is a small readability win and keeps the semantics: on Cancel we do nothing except close the dialog and clear `pendingSessionId`.

### Verification

1. Manual UX test (requires a running dev server):
   - Click Export on any chat card, pick a format, click Continue.
   - In the warning dialog, tick "Don't show this warning again", then click Cancel.
   - Confirm via DevTools that `document.cookie` does **not** contain `dontShowExportWarning=true`.
   - Open the warning dialog again; it must still appear.
2. Repeat, but click Continue Export instead. Cookie is set; next export skips the warning. Previous behavior preserved on the confirm path.
3. Grep: `rg "TODO\(bug\)" frontend/` must return zero matches.

## Bug 4: SQLite connection leaks in `sources/sqlite_data.py`

### Where

Two functions in [cursor_view/sources/sqlite_data.py](cursor_view/sources/sqlite_data.py):

- `iter_bubbles_from_disk_kv` (lines 101-154, `TODO(bug)` at line 109).
- `iter_composer_data` (lines 225-260, `TODO(bug)` at line 227).

Both follow the same buggy structure: `con = sqlite3.connect(...)` inside the same `try` that catches `sqlite3.DatabaseError` and returns, so if a `cur.execute` raises between the `connect` and the `return`, `con` is never closed.

### Fix pattern

Apply the same `con = None` + outer `try/finally` pattern already used by `iter_chat_from_item_table` (which this refactor fixed during todo 6). The generator's `finally` block fires when the generator is closed or garbage-collected, so partial iteration is also safe.

For `iter_bubbles_from_disk_kv`, replace lines 109-154 with:

```python
def iter_bubbles_from_disk_kv(
    db: pathlib.Path,
) -> Iterable[tuple[str, str, str, str, list[str], list[str]]]:
    """Yield (composerId, role, text, db_path, file_uris, folder_uris).

    ``file_uris`` and ``folder_uris`` are kept separate so project inference
    can trim filenames from files while treating folders as candidate roots.
    """
    # Initialize con to None so the outer finally can close it regardless
    # of whether sqlite3.connect or a subsequent cur.execute is what fails.
    con = None
    try:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'")
            if not cur.fetchone():
                return
            cur.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'")
        except sqlite3.DatabaseError as e:
            logger.debug("Database error with %s: %s", db, e)
            return

        db_path_str = str(db)

        for k, v in cur:
            try:
                if v is None:
                    continue
                b = json.loads(v)
            except Exception as e:
                logger.debug("Failed to parse bubble JSON for key %s: %s", k, e)
                continue

            if isinstance(b, dict):
                file_uris, folder_uris = _extract_uris_from_bubble(b)
            else:
                file_uris, folder_uris = [], []
            txt = (b.get("text") or b.get("richText") or "").strip()
            if not txt and not file_uris and not folder_uris:
                continue
            role = "user" if b.get("type") == 1 else "assistant"
            composerId = k.split(":")[1]  # Format is bubbleId:composerId:bubbleId
            yield composerId, role, txt, db_path_str, file_uris, folder_uris
    finally:
        if con is not None:
            con.close()
```

For `iter_composer_data`, apply the same shape to lines 227-260:

```python
def iter_composer_data(db: pathlib.Path) -> Iterable[tuple[str, dict, str]]:
    """Yield (composerId, composerData, db_path) from cursorDiskKV table."""
    con = None
    try:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursorDiskKV'")
            if not cur.fetchone():
                return
            cur.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")
        except sqlite3.DatabaseError as e:
            logger.debug("Database error with %s: %s", db, e)
            return

        db_path_str = str(db)

        for k, v in cur:
            try:
                if v is None:
                    continue
                composer_data = json.loads(v)
                composer_id = k.split(":")[1]
                yield composer_id, composer_data, db_path_str
            except Exception as e:
                logger.debug("Failed to parse composer data for key %s: %s", k, e)
                continue
    finally:
        if con is not None:
            con.close()
```

Key structural changes from the current code:

- The explicit `con.close()` on lines 121 and 237 (the "table doesn't exist" early-return) is removed; the `finally` block handles it.
- The `con.close()` at the end of both functions (after the main `for` loop) is removed; again, `finally` handles it.
- Both `TODO(bug)` comments are removed.
- Matches the `iter_chat_from_item_table` pattern already in the same file.

### Verification

1. Grep: `rg "TODO\(bug\)" cursor_view/sources/sqlite_data.py` must return zero matches.
2. `python -c "import ast; ast.parse(open('cursor_view/sources/sqlite_data.py', encoding='utf-8').read())"` passes.
3. Smoke test (requires a real `state.vscdb` or a fake one):
   - Point `iter_bubbles_from_disk_kv` at a corrupt / non-existent DB and confirm it returns without raising and without leaking a connection (no `ResourceWarning` when `gc.collect()` is forced).
   - Point it at a valid DB with `cursorDiskKV` and confirm the yielded rows match the pre-fix output byte-for-byte.

## Bug 5: diagnostic leak + error-swallowing in `extraction/diagnostics.py`

### Where

[cursor_view/extraction/diagnostics.py](cursor_view/extraction/diagnostics.py), lines 22-89.

### Current problems

1. Both `sqlite3.connect(...)` calls (lines 41 and 63) are unprotected; any `cur.execute` between the connect and the matching `con.close()` leaks the connection.
2. The outer `except Exception as e: logger.debug("Error in diagnostics: %s", e)` catches real errors at `debug` level. Since the rest of the app runs at `INFO`, a user who explicitly set `CURSOR_CHAT_DIAGNOSTICS=1` to troubleshoot missing chats sees no output at all if the probe itself fails.
3. All routine diagnostic lines also use `logger.debug`, so even a **successful** diagnostic run produces no visible output at the default log level — defeating the purpose of the feature.

### Fix

Rewrite the module to:

- Split `dump_workspace_diagnostics` into two small helpers (`_dump_first_workspace`, `_dump_global_storage`) so each manages its own connection.
- Use `contextlib.closing(sqlite3.connect(...))` so both connections are guaranteed to close regardless of where in the block an exception fires.
- Bump the routine messages from `logger.debug` to `logger.info` (the feature is explicitly opt-in via environment variable; when the user turns it on, they expect to see output at the default log level).
- Replace the outer `logger.debug("Error in diagnostics: %s", e)` with `logger.exception("Diagnostic probe failed")` so failures surface with a full traceback.

Full replacement for [cursor_view/extraction/diagnostics.py](cursor_view/extraction/diagnostics.py):

```python
"""Optional workspace/global-DB diagnostics, gated by ``CURSOR_CHAT_DIAGNOSTICS``.

Kept in its own module so the main extraction pipeline reads as a sequence
of extraction passes without being interrupted by ~60 lines of probe code.
"""

import logging
import os
import pathlib
import sqlite3
from contextlib import closing

from cursor_view.paths import global_storage_path, workspaces

logger = logging.getLogger(__name__)


_AI_KEY_PATTERNS = ("%ai%", "%chat%", "%composer%", "%prompt%", "%generation%")


def diagnostics_enabled() -> bool:
    """Return True when ``CURSOR_CHAT_DIAGNOSTICS`` is set to a truthy value."""
    return bool(os.environ.get("CURSOR_CHAT_DIAGNOSTICS"))


def dump_workspace_diagnostics(root: pathlib.Path) -> None:
    """Log a summary of tables/keys in the first workspace and the global DB.

    Intended as a one-shot probe to help users investigate why their chats
    are or aren't showing up. Errors are caught so a probe failure does
    not block the real extraction pipeline, but they are logged with a
    traceback so the user can see why the probe itself misbehaved.
    """
    try:
        _dump_first_workspace(root)
        _dump_global_storage(root)
        logger.info("\n--- END DIAGNOSTICS ---\n")
    except Exception:
        logger.exception("Diagnostic probe failed")


def _dump_first_workspace(root: pathlib.Path) -> None:
    first_ws = next(workspaces(root), None)
    if first_ws is None:
        return
    ws_id, db = first_ws
    logger.info("\n--- DIAGNOSTICS for workspace %s ---", ws_id)
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as con:
        cur = con.cursor()
        tables = _list_tables(cur)
        logger.info("Tables in workspace DB: %s", tables)
        if "ItemTable" in tables:
            _dump_item_table_keys(cur)


def _dump_global_storage(root: pathlib.Path) -> None:
    global_db = global_storage_path(root)
    if global_db is None:
        return
    logger.info("\n--- DIAGNOSTICS for global storage ---")
    with closing(sqlite3.connect(f"file:{global_db}?mode=ro", uri=True)) as con:
        cur = con.cursor()
        tables = _list_tables(cur)
        logger.info("Tables in global DB: %s", tables)
        if "ItemTable" in tables:
            _dump_item_table_keys(cur)
        if "cursorDiskKV" in tables:
            _dump_cursor_disk_kv_prefixes(cur)


def _list_tables(cur: sqlite3.Cursor) -> list[str]:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [row[0] for row in cur.fetchall()]


def _dump_item_table_keys(cur: sqlite3.Cursor) -> None:
    for pattern in _AI_KEY_PATTERNS:
        cur.execute("SELECT key FROM ItemTable WHERE key LIKE ?", (pattern,))
        keys = [row[0] for row in cur.fetchall()]
        if keys:
            logger.info("Keys matching '%s': %s", pattern, keys)


def _dump_cursor_disk_kv_prefixes(cur: sqlite3.Cursor) -> None:
    cur.execute("SELECT DISTINCT substr(key, 1, instr(key, ':') - 1) FROM cursorDiskKV")
    prefixes = [row[0] for row in cur.fetchall()]
    logger.info("Key prefixes in cursorDiskKV: %s", prefixes)
```

Notable preserved behavior:

- The `diagnostics_enabled()` helper is unchanged (`extraction/core.py` calls it at the top of `extract_chats`).
- The five AI key patterns are unchanged; just hoisted to a module-level `_AI_KEY_PATTERNS` constant so both helpers share them.
- The `"\n--- DIAGNOSTICS for ... ---"` / `"\n--- END DIAGNOSTICS ---\n"` header/footer lines are preserved verbatim.
- The per-SQL cursor execution ordering is identical; only the connection lifetime and log level change.

### Verification

1. `python -c "from cursor_view.extraction.diagnostics import diagnostics_enabled, dump_workspace_diagnostics; print('imports OK')"` (once the env has `flask` / `pygments` / etc. installed).
2. Grep: `rg "TODO\(bug\)" cursor_view/extraction/diagnostics.py` must return zero matches.
3. Functional smoke test:
   - Run `CURSOR_CHAT_DIAGNOSTICS=1 python3 terminal.py --no-browser` (Linux/macOS) or `$env:CURSOR_CHAT_DIAGNOSTICS = "1"; python3 terminal.py --no-browser` (Windows PowerShell).
   - Confirm `--- DIAGNOSTICS for workspace ... ---` and friends appear on stdout at INFO level (previously: invisible).
4. Negative test: temporarily make `workspaces()` raise (e.g. monkey-patch in a REPL) and confirm the traceback is logged via `logger.exception`, while `extract_chats()` itself still completes.

## Final cleanup

After all five todos:

1. `rg "TODO\(bug\):"` across the repo must return zero matches (ignore matches inside `.cursor/rules/known-bugs.mdc` and `.cursor/plans/*.md`, which document the convention itself).
2. `python -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in pathlib.Path('.').rglob('*.py')]; print('syntax OK')"`.
3. ReadLints over the whole repo; no new warnings.
4. Consider adding a short "Fixed bugs" note in the parent refactor plan or a standalone CHANGELOG if the project maintains one (optional; the commit/PR messages plus the plan file's "Known issues" section already serve as record).