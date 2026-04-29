---
name: refresh-button-delta-cache
overview: Reroute the home page Refresh button (which currently forces a full cache rebuild via `ChatIndex.ensure_current(force=True)`) to a synchronous delta-cache refresh, falling back to a full rebuild only for the existing correctness gates (missing/corrupt cache, schema drift) or an apply-time failure. Update the supporting cursor rule, contributing docs, and add regression coverage.
todos:
  - id: impl-helper
    content: Add `_run_synchronous_delta_or_rebuild` helper in `cursor_view/chat_index/index.py` that holds `_rebuild_build_lock`, runs `compute_source_diff` + `apply_delta`, and falls back to `_rebuild` inside the same lock on `sqlite3.DatabaseError` or apply exception.
    status: pending
  - id: impl-force-branch
    content: "Rewrite the `if force:` branch of `ensure_current` to: re-check `db_path.exists()`, route to `_rebuild` on missing-cache / `sqlite3.DatabaseError` / `cached_schema != str(INDEX_SCHEMA_VERSION)`, otherwise call the new shared helper. Keep concurrency under `_rebuild_build_lock` for the entire critical section."
    status: pending
  - id: impl-bg-reuse
    content: Refactor `_background_refresh_worker` to call the same shared helper so the two paths cannot drift on fallback semantics; verify the structured log line in `cursor_view/cache/delta/engine.py::_log_refresh_summary` still fires for the manual-refresh path.
    status: pending
  - id: rule-refresh-update
    content: "Update `.cursor/rules/chat-index-refresh.mdc`: move `force=True` out of the synchronous-rebuild bullet list, document the new \"synchronous delta with rebuild fallback\" path, and explain that the rebuild fallback is gated on the same correctness signals as before (missing cache / `DatabaseError` / schema drift / apply failure). Cite both the new helper and `_background_refresh_worker` as canonical call sites."
    status: pending
  - id: rule-known-bugs-check
    content: Re-read `.cursor/rules/known-bugs.mdc` and ensure no live `# TODO(bug):` markers were silently removed and no suspicious-but-out-of-scope code path was rewritten without one.
    status: pending
  - id: rule-comments-style-check
    content: Re-read `.cursor/rules/comments-style.mdc` and audit every comment added in this change to confirm it explains intent / invariants / non-obvious platform behavior, never re-narrates the code.
    status: pending
  - id: rule-python-standards-check
    content: "Re-read `.cursor/rules/python-standards.mdc` and confirm: lazy `%s`-style logging in any new log lines, typed signatures on the new helper, no new module > ~400 lines or function > ~100 lines, no module-load side effects in `cursor_view/chat_index/index.py`."
    status: pending
  - id: rule-sqlite-cursor-db-check
    content: "Re-read `.cursor/rules/sqlite-cursor-db.mdc` and confirm: read-only URI form for any source-DB read added (none expected); writable cache connections continue to use the `_connect(read_only=False)` context manager so connection cleanup uses `try/finally` rather than `if 'con' in locals(): con.close()`."
    status: pending
  - id: rule-project-layout-check
    content: Re-read `.cursor/rules/project-layout.mdc` and confirm no new top-level Python file is created and no module crosses the 400-line soft limit. If `cursor_view/chat_index/index.py` grows past ~400 lines after the change, propose a split of `ensure_current`'s helper out into a new module under the same subpackage.
    status: pending
  - id: doc-contributing
    content: "Update `.github/CONTRIBUTING.md`: revise the `chat_index/` paragraph that lists `force_refresh` as a full-rebuild trigger so it instead documents the synchronous-delta-with-rebuild-fallback path. Mention the shared helper by name."
    status: pending
  - id: doc-readme
    content: Audit `README.md` for any user-facing claims about Refresh latency or full-rebuild semantics. Update only if such claims exist; otherwise leave unchanged and record the no-op decision in the PR description.
    status: pending
  - id: test-force-uses-delta
    content: "Add a regression test in `tests/test_chat_index_incremental.py` that builds an index, mutates a single bubble, calls `ensure_current(force=True)`, and asserts: (a) `_rebuild` was NOT called (use `patch.object(ci, '_rebuild', wraps=ci._rebuild)`), (b) `apply_delta` was called, (c) the new bubble shows up via `list_summaries`. Mirror the patching style used by `test_schema_version_bump_forces_synchronous_rebuild` and `test_source_fingerprint_bump_uses_background_refresh`."
    status: pending
  - id: test-force-fallback
    content: "Add a regression test that pins the rebuild fallback: simulate `apply_delta` raising `sqlite3.DatabaseError`, call `ensure_current(force=True)`, and assert `_rebuild` was called exactly once and the cache ends up usable (a follow-up `list_summaries` succeeds)."
    status: pending
  - id: test-existing-still-pass
    content: Run the full `python -m unittest discover -s tests` suite and confirm no pre-existing tests regress (especially `test_schema_version_bump_forces_synchronous_rebuild`, `test_source_fingerprint_bump_uses_background_refresh`, and `test_chat_index_propagation_gating`).
    status: pending
  - id: bug-final-pass
    content: "Final bug-hunt pass over `cursor_view/chat_index/index.py` and the apply-delta seam: confirm `_rebuild_build_lock` covers both delta and fallback inside the force branch, the `db_path.exists()` re-check inside the lock matches the existing double-check pattern, no connection leaks were introduced (each `_connect` invocation is consumed by exactly one `with` block), and any genuinely suspicious out-of-scope path got a `# TODO(bug):` marker per `.cursor/rules/known-bugs.mdc` rather than a silent rewrite."
    status: pending
isProject: false
---

## Problem

The "Refresh" button in [`frontend/src/components/chat-list/ChatList.js`](frontend/src/components/chat-list/ChatList.js) calls `useChatSummaries.refresh`, which sends `GET /api/chats?refresh=1`. The Flask handler in [`cursor_view/routes.py`](cursor_view/routes.py) translates that into `force_refresh=True`, which `ChatIndex.list_summaries` forwards to `ensure_current(force=True)`. That branch unconditionally calls `_rebuild` — the slow, build-to-temp-and-atomic-swap full reindex path — even though the existing background `_background_refresh_worker` already knows how to do an incremental delta apply with a full-rebuild fallback.

Today's force=True path (synchronous full rebuild):

```170:173:cursor_view/chat_index/index.py
        if force:
            with self._rebuild_build_lock:
                self._rebuild(source_fingerprint, sources)
            return
```

## Approach

Keep the manual Refresh synchronous (the user is staring at a spinner), but mirror the path that `_background_refresh_worker` already takes:

1. Coarse fingerprint check first; if the cache is already current, return immediately.
2. If the cache is missing, unreadable (`sqlite3.DatabaseError`), or its `schema_version` row does not match `INDEX_SCHEMA_VERSION`, fall back to `_rebuild` — these are correctness gates, not freshness ones (per [`.cursor/rules/chat-index-refresh.mdc`](.cursor/rules/chat-index-refresh.mdc)).
3. Otherwise, run `compute_source_diff` + `apply_delta` under the existing `_rebuild_build_lock`. On any `sqlite3.DatabaseError` or apply exception, fall back to `_rebuild` (same fallback discipline as the background worker).

Concretely, factor the refresh body so the `force=True` branch and `_background_refresh_worker` share a single helper (`_run_synchronous_delta_or_rebuild`). This removes duplication and makes it impossible to drift between the two paths' fallback logic.

## Key files

- [`cursor_view/chat_index/index.py`](cursor_view/chat_index/index.py) — core change in `ensure_current` and a new shared helper that wraps `_compute_source_diff` + `_apply_delta` with the `DatabaseError -> _rebuild` fallback. `_background_refresh_worker` calls the same helper from inside its existing `_rebuild_build_lock` block.
- [`.cursor/rules/chat-index-refresh.mdc`](.cursor/rules/chat-index-refresh.mdc) — `force=True` is no longer a synchronous-rebuild trigger by default; it becomes a synchronous-delta trigger that only escalates to full rebuild on the same correctness gates as the SWR path.
- [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) — the `chat_index/` paragraph claims the cache "[falls] back to a full rebuild only on `force_refresh`, schema drift, `DatabaseError`, or a missing cache file"; update it so `force_refresh` lands on the delta path.
- [`README.md`](README.md) — does not currently describe refresh-cache routing, so no edit is expected. Verify and add a brief note only if other parts of the change make a user-visible behavior promise (e.g. "Refresh is now incremental").
- [`tests/test_chat_index_incremental.py`](tests/test_chat_index_incremental.py) — add a regression test that pins the new behavior (force=True against a readable, schema-current cache uses delta) and confirm the existing schema-drift / fingerprint-bump tests still pass without modification (they monkey-patch `_schedule_background_refresh` and `_rebuild`, neither of which the new force-delta arm calls into).

## Routing diagram (after change)

```mermaid
flowchart TD
    A[ensure_current force?] -->|no| B{cache up to date?}
    A -->|yes force=True| C{cache exists?}
    C -->|no| FR[Synchronous full _rebuild]
    C -->|yes| D{schema OK & readable?}
    D -->|no| FR
    D -->|yes| DELTA[Synchronous delta: compute_source_diff + apply_delta]
    DELTA -->|DatabaseError or apply failure| FR
    B -->|yes| RET[Return current rows]
    B -->|no| SWR[Schedule background refresh]
    SWR --> DELTA2[Delta inside worker]
    DELTA2 -->|DatabaseError or apply failure| FR2[Background full _rebuild]
```

## Frontend

No frontend change required. The button already shows a spinner (`loading=true`) until the API call returns, and the API call's response is whatever rows `apply_delta` produced. The button's perceived latency drops from "rebuild whole index" to "apply diff", which is the entire point.

## Bug-hunt check (mandatory final step)

After the implementation lands, do one focused read pass over the changed file and the apply-delta seam looking specifically for:

- A force=True caller that races a background refresh thread — both arms now need `_rebuild_build_lock`; the new synchronous delta arm must hold the lock for the whole `compute_source_diff` + `apply_delta` window so it cannot interleave with `_background_refresh_worker`. Verify the lock acquisition order matches and that `_compute_source_diff` (which opens its own read-only connection) does not deadlock against the writable connection `apply_delta` opens later.
- The `_rebuild` fallback inside the new helper must run **without** the lock already released — a naive refactor that does `with lock: try delta` then `_rebuild()` outside the `with` would lose the single-writer guarantee. The fallback must be inside the same `with self._rebuild_build_lock:` block.
- A force=True call against a cache that was deleted between the existence check and the build-lock acquisition — re-check `db_path.exists()` after taking the lock, mirroring the existing double-check in the `not self.db_path.exists()` branch of `ensure_current`.
- Per [`.cursor/rules/known-bugs.mdc`](.cursor/rules/known-bugs.mdc), if any code path looks suspicious but is out-of-scope for this change, leave a `# TODO(bug):` marker rather than silently rewriting it.