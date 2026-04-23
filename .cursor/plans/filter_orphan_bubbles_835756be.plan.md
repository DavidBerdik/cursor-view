---
name: filter orphan bubbles
overview: Fix Pass 2 so bubbles on disk that are absent from the composer's `fullConversationHeadersOnly` array (orphan bubbles Cursor pruned from the canonical transcript) are dropped instead of sorted to the end, which otherwise manifests as "recent messages missing, old messages repeated at the bottom" in chats like `7676aa8c-6c48-481e-ac24-1b1f434e6206`.
todos:
  - id: baseline
    content: Run `python -m unittest discover -s tests -v` and confirm all 14 existing tests pass as the regression baseline
    status: completed
  - id: add-tests
    content: Add four new tests to tests/test_chat_index_incremental.py (orphan filtered on full rebuild, orphan filtered on incremental, orphan tool-call not linked into tool_call_parent, explicit legacy-no-headers regression), run them and confirm they fail against current code
    status: completed
  - id: implement-fix
    content: In cursor_view/extraction/passes/global_bubbles.py::_collect_global_bubbles, skip bubbles whose bubbleId is not in ordinal_map when ordinal_map is non-empty (no message, no URIs, no tool_call_parent, no comp_meta seed, no db_path write); keep the legacy encounter-order fallback when ordinal_map is empty; update the docstring paragraph to explain the orphan-filter invariant; add a logger.debug counter guarded by isEnabledFor(DEBUG). Also filter orphans in cursor_view/cache/diff/global_db.py::_diff_global_cursor_disk_kv to block the second write path into tool_call_parent (required for the orphan-tool-call regression test to pass; see `_header_bubble_ids_from_composer` helper added to cursor_view/cache/diff/hashing.py).
    status: completed
  - id: update-rule
    content: Add a 'Canonical bubble order' subsection to .cursor/rules/sqlite-cursor-db.mdc documenting the orphan-filter invariant and citing the two new regression tests
    status: completed
  - id: verify-green
    content: Re-run `python -m unittest discover -s tests -v` and confirm all tests (the four new ones plus the original 14) pass
    status: completed
  - id: manual-smoke
    content: Start the server against the real Cursor data, open http://127.0.0.1:5000/chat/7676aa8c-6c48-481e-ac24-1b1f434e6206 and confirm the orphan 'After the changes...' block no longer appears at the bottom and the last message is the canonical 'The diagram is in place...' assistant response; press Refresh once to force a full rebuild and re-verify
    status: completed
isProject: false
---

## Why the bug appears only after the incremental-cache redesign

Cursor stores per-composer bubbles two ways in the global `state.vscdb.cursorDiskKV`:

- One row per bubble keyed `bubbleId:<cid>:<bid>` (JSON payload with `type`, `text`, etc.).
- The canonical chronological order as a single array on the composer: `composerData:<cid>.fullConversationHeadersOnly = [{bubbleId, type, ...}, ...]`.

Cursor routinely **prunes bubbles out of `fullConversationHeadersOnly`** (summarization checkpoints, conversation restarts, "reset to this point" UX) but **leaves the orphaned `bubbleId:*` rows on disk**. For the reproducer session the orphan set is:

- 775 `bubbleId:7676aa8c-...:*` rows on disk
- 636 entries in `fullConversationHeadersOnly`
- 139 orphan bubbles (1 user + 138 assistant)

Before the ordering fix landed in [.cursor/plans/cursor-view_structure_cleanup_d9ba8085.plan.md](.cursor/plans/cursor-view_structure_cleanup_d9ba8085.plan.md), Pass 2 ignored `fullConversationHeadersOnly` and appended bubbles in `cursorDiskKV` PK order (UUID-alphabetical). Orphans were just interleaved randomly and the "big block at the end" effect did not show up. After the fix, [cursor_view/extraction/passes/global_bubbles.py](cursor_view/extraction/passes/global_bubbles.py) tags every bubble missing from the headers array with `_UNMAPPED_BUBBLE_ORDINAL = 10**9` and places it *after* every canonical bubble:

```117:140:cursor_view/extraction/passes/global_bubbles.py
        ordinal_map = bubble_order_by_cid.get(cid) or {}
        ordinal = ordinal_map.get(bubble_id, _UNMAPPED_BUBBLE_ORDINAL)
        messages_by_cid[cid].append(...)
    for cid, bucket in messages_by_cid.items():
        bucket.sort(key=lambda item: (item[0], item[1]))
        sessions[cid]["messages"].extend(msg for _ord, _s, msg in bucket)
```

That fallback was designed for "bubble written after the composerData snapshot we read" (a tiny TOCTOU window), but in practice the dominant case is Cursor-pruned orphans, and the fallback concentrates them into one visible block at the end — precisely the symptom in the report.

## Fix: filter orphans when the headers array exists

Only one authoritative source describes a composer's message sequence: its `fullConversationHeadersOnly`. When that array is populated, every bubble NOT in it is stale state Cursor itself does not show. The fix is a single-file behavior change in [cursor_view/extraction/passes/global_bubbles.py](cursor_view/extraction/passes/global_bubbles.py):

- If `ordinal_map` is non-empty and `bubble_id not in ordinal_map` → **skip the bubble entirely**: no message, no URIs into `bubble_file_uris_by_cid` / `bubble_folder_uris_by_cid`, no `tool_call_parent.setdefault`, no `comp_meta` seed, no `db_path` write.
- If `ordinal_map` is empty (composer predates `fullConversationHeadersOnly` — legacy Cursor builds) → keep the current `_UNMAPPED_BUBBLE_ORDINAL` append-in-encounter-order path unchanged. The existing `test_bubble_order_falls_back_to_encounter_order_without_headers` is the regression guard for this branch.

Skipping URIs and `tool_call_parent` from orphans is correct:

- Orphan bubbles point at files/folders that are no longer part of the visible transcript; inferring a project from them would let stale data override a live signal.
- A `toolFormerData.toolCallId` on an orphan would resurrect a dead subagent parent link in `tool_call_parent` for an upcoming `task-<toolCallId>` lookup. `tool_call_parent` entries for canonical-only bubbles are already handled by the existing diff/apply logic (see [cursor_view/cache/diff/engine.py](cursor_view/cache/diff/engine.py)); skipping orphans here keeps the cached map consistent with the canonical transcript.

The incremental path inherits the fix for free: `_extract_modified_chats` in [cursor_view/cache/delta/composer_rows.py](cursor_view/cache/delta/composer_rows.py) calls the same `extract_chats(cids=..., cached_state=...)` orchestrator, which runs the same Pass 2 via `iter_bubbles_for_cids` + `build_bubble_order_map(..., cids=...)`.

### Observability

Add a single `logger.debug("Skipped %s orphan bubbles for %s", n, cid[:8])` counter per cid inside Pass 2 (guarded by `logger.isEnabledFor(logging.DEBUG)` to avoid the dict lookup in the hot path when debug is off). This matches the existing debug-level counters in the same module and lets a future contributor confirm from logs that orphan counts match disk reality without re-running the investigation in this plan.

## Rule compliance

Adheres to rules as currently written:

- [.cursor/rules/python-standards.mdc](.cursor/rules/python-standards.mdc) — `global_bubbles.py` is 142 lines today; the change adds ~6 lines and a docstring update, still well under the 400-line soft cap. The existing module docstring stays; the `_collect_global_bubbles` docstring gets one new paragraph explaining the orphan-filter invariant (intent, not mechanics, per [.cursor/rules/comments-style.mdc](.cursor/rules/comments-style.mdc)).
- [.cursor/rules/sqlite-cursor-db.mdc](.cursor/rules/sqlite-cursor-db.mdc) — no SQL lifecycle changes; the existing `_connect_cursor_disk_kv` + `contextlib.closing` pattern in [cursor_view/sources/bubbles.py](cursor_view/sources/bubbles.py) is reused unchanged.
- [.cursor/rules/known-bugs.mdc](.cursor/rules/known-bugs.mdc) — this is a "fix now" change, not a `TODO(bug):` annotation, because the user explicitly asked for the fix.
- [.cursor/rules/project-layout.mdc](.cursor/rules/project-layout.mdc) — the "any new behavior that touches the chat-index refresh path must land with a synthetic-Cursor-DB regression test in `tests/test_chat_index_incremental.py` or a new sibling" clause is satisfied by the new tests below.
- [.cursor/rules/comments-style.mdc](.cursor/rules/comments-style.mdc) rule-drift clause: update [.cursor/rules/sqlite-cursor-db.mdc](.cursor/rules/sqlite-cursor-db.mdc) in the same change to document the new invariant (details in §Rule updates below).

## Rule updates

### `.cursor/rules/sqlite-cursor-db.mdc`

Add a new subsection under the existing "Cache tables" / "Invalidation" region titled **"Canonical bubble order"**:

> The canonical chronological order of a composer's messages lives on `composerData:<cid>.fullConversationHeadersOnly`, not on the `bubbleId:<cid>:*` row set. Cursor routinely prunes bubbles out of that array (summarization checkpoints, conversation restarts) without deleting the corresponding `bubbleId:*` rows, so extraction must treat any bubble whose `bubbleId` is absent from the headers array of a composer that HAS a non-empty headers array as stale and drop it — no message, no URI into project inference, no `tool_call_parent` upsert. The fallback "append in encounter order" path is reserved for composers whose headers array is missing or empty (legacy Cursor builds that predate the array). This invariant is enforced in [cursor_view/extraction/passes/global_bubbles.py](cursor_view/extraction/passes/global_bubbles.py) `_collect_global_bubbles`; the regression guards live in `tests/test_chat_index_incremental.py::test_orphan_bubble_filtered_full_rebuild` and `::test_orphan_bubble_filtered_incremental`.

This belongs in `sqlite-cursor-db.mdc` (not a new rule) because the whole file is about how to reason over Cursor's on-disk SQLite shape, and the orphan-bubble behavior is a property of Cursor's storage — readers of this rule are exactly the contributors who will next edit extraction or the diff.

No new rule file is added. The project-layout / python-standards / known-bugs / comments-style / react-components / frontend-hooks / image-attachments rules all stay verbatim: this change doesn't introduce a new pattern that lacks guidance, it's a targeted fix to one pass that already has guidance in the sqlite rule.

## Tests

All test work happens in [tests/test_chat_index_incremental.py](tests/test_chat_index_incremental.py), next to the existing `test_bubble_order_uses_headers_array` / `test_bubble_order_falls_back_to_encounter_order_without_headers` pair that covers the previous ordering-fix iteration.

Sequence:

1. **Baseline (no code changes yet).** Run `python -m unittest discover -s tests -v` from the repo root and confirm the current 14 tests all pass. This is the regression surface the fix must preserve. (Just verified: 14/14 green.)
2. **Add new tests** (still before any production change, so the new tests fail initially — proves they actually exercise the bug):
   - `test_orphan_bubble_filtered_full_rebuild`: composer with headers `[("b1", 1), ("b2", 2)]` plus an extra `bubbleId:<cid>:b_orphan` row whose text is `"orphan text"`. After a full rebuild, `chat_message` rows must be exactly `[(user, "b1 text"), (assistant, "b2 text")]`; `"orphan text"` must NOT appear.
   - `test_orphan_bubble_filtered_incremental`: same setup, then on a second pass (incremental refresh triggered by editing `bubbleId:<cid>:b2`) assert the same two-row content and that `dirty.modified_cids == {cid}`.
   - `test_orphan_tool_call_bubble_not_linked`: parent composer with headers listing only a non-tool-call bubble, plus an orphan `bubbleId:<parent>:<orphan>` whose `toolFormerData.toolCallId == "toolu_orphan"`. Assert that after a refresh the cache's `tool_call_parent` table does NOT contain `"toolu_orphan"`. The test fixture's `_bubble(..., tool_call_id=...)` helper already exists.
   - `test_legacy_composer_still_includes_all_bubbles`: negative-case regression (no headers array at all), asserting both bubbles still land — this supplements the existing `test_bubble_order_falls_back_to_encounter_order_without_headers` but explicitly names the "extra bubble that would have been orphan if headers existed" case so future readers see the two branches side-by-side.
3. **Implement the fix** in [cursor_view/extraction/passes/global_bubbles.py](cursor_view/extraction/passes/global_bubbles.py).
4. **Re-run** `python -m unittest discover -s tests -v` and confirm **all** tests (including the four new ones and the pre-existing 14) pass.
5. **Manual smoke test**: start the local server against the real Cursor data, open `http://127.0.0.1:5000/chat/7676aa8c-6c48-481e-ac24-1b1f434e6206`, and verify the last message is the canonical `"The diagram is in place..."` assistant response and that no orphan "After the changes you made..." / big assistant block appears at the bottom. Press the UI's Refresh button once to force `ensure_current(force=True)` through the full-rebuild path and confirm the same.

## Files touched

- [cursor_view/extraction/passes/global_bubbles.py](cursor_view/extraction/passes/global_bubbles.py) — orphan-filter branch inside `_collect_global_bubbles`; updated docstring paragraph explaining the invariant (intent, not mechanics, per `comments-style.mdc`); optional `logger.debug` counter.
- [tests/test_chat_index_incremental.py](tests/test_chat_index_incremental.py) — four new tests as listed above.
- [.cursor/rules/sqlite-cursor-db.mdc](.cursor/rules/sqlite-cursor-db.mdc) — one new "Canonical bubble order" subsection, cited from the tests.

No other files change. No schema bump needed (cache layout is unchanged); developers with a stale cache can delete `chat-index.sqlite3` or hit Refresh, identical to the ordering-fix rollout.

## Non-goals

- Not adding logic to detect or repair the orphan rows in Cursor's own `cursorDiskKV` — they're Cursor's data; extraction's contract is "render what Cursor considers the canonical transcript", not "garbage-collect Cursor's disk state".
- Not changing how the coarse fingerprint or the fine diff classify dirty cids. Orphan bubbles whose content changes will still flip their cid into `modified_cids` via `source_row`, which triggers a re-extract; the re-extract will then drop them. The extra cycle is rare and self-heals.
- Not bumping `INDEX_SCHEMA_VERSION`; orphan-polluted caches were never shipped to users, and a manual Refresh reclaims them.
- Not touching the frontend; the chat-detail view renders whatever the API returns, so correcting the server-side extraction is sufficient.