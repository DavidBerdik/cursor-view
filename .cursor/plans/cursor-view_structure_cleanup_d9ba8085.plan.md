---
name: cursor-view structure cleanup
overview: "Restore rule compliance across the Python and React halves of the project after the incremental-refresh and bug-fix work: split six files that grew past the size soft limits into focused submodules, deduplicate a pane-view key parser that now lives in two places, stop importing private helpers across package boundaries, prune narrating comments, tighten a small chat-formatting DRY issue on the cache write path, and fix one severe bug in the extraction pipeline where bubbles are read in alphabetical-bubbleId order instead of the canonical order Cursor records in `composerData.fullConversationHeadersOnly`, which scrambles message order and makes `coalesce_consecutive_messages_by_role` merge unrelated user prompts."
todos:
  - id: fix_bubble_ordering
    content: "Fix the scrambled-messages bug: change the extraction pipeline to read composerData.fullConversationHeadersOnly FIRST and use it as the canonical bubble order, then sort each composer's messages by that order before coalescing. Affects full rebuild (iter_bubbles_from_disk_kv path) and cid-scoped extraction (iter_bubbles_for_cids path). Includes a regression test fixture with a fullConversationHeadersOnly array whose bubbleId order is the reverse of the bubbleIds' alphabetical order. Sequenced first so users stop reading gibberish chat histories during the refactor window. INDEX_SCHEMA_VERSION stays at 2 because the scrambled caches never shipped; developers with a stale local cache delete chat-index.sqlite3 or hit Refresh."
    status: completed
  - id: split_chat_index
    content: Split cursor_view/chat_index.py (819 lines) into a cursor_view/chat_index/ subpackage with schema.py, fingerprint.py, rebuild.py, rows.py, and index.py (the ChatIndex orchestrator)
    status: completed
  - id: split_extraction_core
    content: Split cursor_view/extraction/core.py (716 lines) into a cursor_view/extraction/passes/ subpackage with one module per pass (workspace_messages, global_bubbles, global_composers, uri_fallbacks, task_subagents, subagent_inheritance, item_table_chats, finalize); keep core.py as the orchestrator only
    status: completed
  - id: split_projects_inference
    content: Split cursor_view/projects/inference.py (685 lines) into name.py, uris.py, workspace_json.py, workspace_sources.py, workspace_identifier.py, composer_uris.py, pane_view.py, and a slimmed inference.py that owns only workspace_info; re-export the now-public helpers via projects/__init__.py and update extraction imports to drop the underscore-prefixed cross-package names
    status: completed
  - id: split_source_diff
    content: Split cursor_view/cache/source_diff.py (629 lines) into a cursor_view/cache/diff/ subpackage with types.py, hashing.py, cache_state.py, global_db.py, workspace_db.py, propagation.py, and engine.py; delete the old source_diff.py after updating call sites
    status: completed
  - id: split_apply_delta
    content: Split cursor_view/cache/apply_delta.py (534 lines) into a cursor_view/cache/delta/ subpackage with cached_state.py, composer_rows.py, project_only.py, metadata.py, engine.py, and backfill.py; delete the old apply_delta.py after updating call sites
    status: pending
  - id: split_sources
    content: Split cursor_view/sources/sqlite_data.py (419 lines) into sqlite_util.py (j, _connect_cursor_disk_kv), bubbles.py, composer_data.py, and item_table.py; unify iter_bubbles_from_disk_kv/iter_composer_data on _connect_cursor_disk_kv and swap the nested try/except for contextlib.closing where it shortens the function
    status: pending
  - id: move_legacy_chatdata_sql
    content: Move the global legacy-chatdata SQL out of cursor_view/extraction/core.py _collect_global_item_table_chats and into a new iter_global_legacy_chatdata() iterator in cursor_view/sources/item_table.py so extraction consumes sources instead of opening SQLite directly
    status: pending
  - id: dedupe_pane_view
    content: Delete the pane-view cid parsing duplicated between cursor_view/projects/inference.py and cursor_view/cache/source_diff.py; have cache/diff/hashing.py import cid_from_pane_view_key and cids_from_pane_container_value from cursor_view/projects/pane_view.py
    status: pending
  - id: dry_format_on_write
    content: Update ChatIndex._insert_chat to return (formatted_chat, coalesced_messages) (or accept pre-built args) so cursor_view/cache/delta/engine.py and cursor_view/cache/delta/backfill.py no longer re-run format_chat_for_frontend + coalesce_consecutive_messages_by_role on every refreshed composer
    status: pending
  - id: typing_cleanup
    content: Add dict[str, Any] / list[str] / typed return annotations to the composer-URI helpers (_project_from_global_composer_files, _extract_composerdata_context_uris, _project_from_root) that currently take a bare data argument
    status: pending
  - id: comment_hygiene
    content: Strip narrating comments in cursor_view/chat_format.py::format_chat_for_frontend and across the new extraction/passes/*.py modules per .cursor/rules/comments-style.mdc; keep the comments that explain heuristic priority or non-obvious intent
    status: pending
  - id: split_context_menu
    content: Split frontend/src/components/AppContextMenu.js (268 lines) by extracting isEditableElement + findSelectionContainer into frontend/src/utils/dom.js and the selection save/restore state into frontend/src/hooks/useSavedSelection.js; reduce AppContextMenu.js to handlers + <Menu> JSX
    status: pending
  - id: update_readme
    content: Refresh the README Project-layout section to reflect the new chat_index/, extraction/passes/, projects/ submodules, cache/diff/ and cache/delta/ subpackages, split sources/ modules, and the new useSavedSelection hook + utils/dom.js helpers
    status: pending
  - id: review_cursor_rules
    content: Review every .cursor/rules/*.mdc against the post-refactor reality; refresh motivating examples in project-layout/python-standards/react-components, add a "tests/" bullet to project-layout, add a "no cross-package private imports" clause to python-standards, add a "no import-time side effects at module load" clause, and author a new .cursor/rules/frontend-hooks.mdc capturing the useChatSummaries-style cancellation-and-useCallback discipline
    status: pending
  - id: verify
    content: Run the smoke-test import line documented in the plan, then python -m unittest discover -s tests and cd frontend && npm run build to confirm no regressions
    status: completed
isProject: false
---

## Motivation

This pass is a structural cleanup, not a behavior change. Each item below is either a direct violation of a rule under `.cursor/rules/` or a duplication / boundary issue the rules call out as a pattern to avoid.

Relevant rules:
- [.cursor/rules/python-standards.mdc](.cursor/rules/python-standards.mdc) — module <~400 lines, function <~100 lines, no f-string logging, docstrings + typed signatures.
- [.cursor/rules/project-layout.mdc](.cursor/rules/project-layout.mdc) — organize by concern using subpackages.
- [.cursor/rules/sqlite-cursor-db.mdc](.cursor/rules/sqlite-cursor-db.mdc) — cleanup conventions + new cache tables.
- [.cursor/rules/react-components.mdc](.cursor/rules/react-components.mdc) — ~250-line component cap + shared helpers.
- [.cursor/rules/comments-style.mdc](.cursor/rules/comments-style.mdc) — intent-only comments.

Behavior, HTTP API, on-disk cache layout, cookie names, and the PyInstaller build stay identical. No `TODO(bug):` markers are added; the previous round already fixed all five.

## Rule-violation inventory

Files over the soft limits, measured from the current tree:

- [cursor_view/chat_index.py](cursor_view/chat_index.py): 819 lines
- [cursor_view/extraction/core.py](cursor_view/extraction/core.py): 716 lines
- [cursor_view/projects/inference.py](cursor_view/projects/inference.py): 685 lines
- [cursor_view/cache/source_diff.py](cursor_view/cache/source_diff.py): 629 lines
- [cursor_view/cache/apply_delta.py](cursor_view/cache/apply_delta.py): 534 lines
- [cursor_view/sources/sqlite_data.py](cursor_view/sources/sqlite_data.py): 419 lines
- [frontend/src/components/AppContextMenu.js](frontend/src/components/AppContextMenu.js): 268 lines

Every other Python module is <~200 lines and every other React component is <~200 lines, so the remaining work is duplication and style only.

## Python refactors

### 1. Split `cursor_view/chat_index.py` into `cursor_view/chat_index/`

`ChatIndex` today owns five distinct concerns that each read as a unit:

- connection / read-guard lifecycle (`_cache_read_guard`, `_connect`, `_configure_connection`, `_read_meta_value`)
- schema and fingerprint (`_create_schema`, `_create_fts_table`, `_current_source_fingerprint`, `_source_entry`, `INDEX_SCHEMA_VERSION`)
- refresh routing (`ensure_current`, `_schedule_background_refresh`, `_background_refresh_worker`, `_cached_index_up_to_date`, `_apply_delta`, `_compute_source_diff`)
- full rebuild (`_rebuild`, `_build_index_to_temp`, `_swap_temp_into_place`)
- read / write row shaping (`_insert_chat`, module-level `_trim_preview`, `_preview_from_messages`, `_search_blob`, `_fts_query`, `_count_summaries`, `_fetch_summaries`, `_database_has_fts`, `_summary_row_to_api`)

Target layout:

```
cursor_view/chat_index/
  __init__.py           # re-exports ChatIndex, get_chat_index, INDEX_SCHEMA_VERSION
  index.py              # the ChatIndex class itself (thin orchestrator)
  schema.py             # INDEX_SCHEMA_VERSION, _create_schema, _create_fts_table
  fingerprint.py        # _current_source_fingerprint, _source_entry
  rebuild.py            # _rebuild, _build_index_to_temp, _swap_temp_into_place
  rows.py               # _insert_chat, _count_summaries, _fetch_summaries, _summary_row_to_api, _database_has_fts, _fts_query, _preview_from_messages, _search_blob, _trim_preview
```

Keep `get_chat_index` and `INDEX_SCHEMA_VERSION` importable from `cursor_view.chat_index` unchanged so [cursor_view/routes.py](cursor_view/routes.py) and [cursor_view/cache/apply_delta.py](cursor_view/cache/apply_delta.py) don't move. The refresh routing lives on `ChatIndex` itself; the split is mechanical function moves, not a protocol change.

### 2. Split `cursor_view/extraction/core.py` into per-pass modules

The eight passes documented in the file's module docstring are already private functions. Promote the split one level:

```
cursor_view/extraction/
  __init__.py                # re-exports extract_chats, CachedExtractionState
  core.py                    # CachedExtractionState, _merge_global_composer_into_meta, extract_chats (orchestrator only)
  passes/
    __init__.py
    workspace_messages.py    # _collect_workspace_messages (Pass 1)
    global_bubbles.py        # _collect_global_bubbles (Pass 2)
    global_composers.py      # _collect_global_composers (Pass 3)
    uri_fallbacks.py         # _apply_uri_fallbacks (Pass 4)
    task_subagents.py        # _link_task_subagents_to_parents (Pass 5), _TASK_CID_PREFIX
    subagent_inheritance.py  # _apply_subagent_inheritance (Pass 6), _MAX_PARENT_DEPTH
    item_table_chats.py      # _collect_global_item_table_chats (Pass 7)
    finalize.py              # _finalize_sessions (Pass 8)
  diagnostics.py             # unchanged
```

`extract_chats` in `core.py` becomes a ~60-line recipe that imports from `passes/` and wires the state dicts — matches the "top-level function as a short recipe" clause of `python-standards.mdc`.

### 3. Split `cursor_view/projects/inference.py` into project-specific modules

Today this file contains path-name heuristics, file URI decoding, `workspace.json` parsing, tree-view state, history.entries, debug.selectedroot, workspace identifier resolution, composerData URI mining, pane-view cid extraction, and the `workspace_info` orchestrator. That's seven separate concerns.

```
cursor_view/projects/
  __init__.py                # re-exports the public API used by extraction and chat_format
  inference.py               # workspace_info orchestrator only
  name.py                    # extract_project_name_from_path, _normalize_root_path_field, _project_from_root
  uris.py                    # _file_uri_to_path, _path_group_key, _normalize_uri_to_path, _path_from_workspace_uri_object, _trim_file_and_vscode_suffix
  workspace_json.py          # _project_root_from_workspace_json
  workspace_sources.py       # _project_root_from_tree_view_state, _project_root_from_history
  workspace_identifier.py    # _project_from_workspace_identifier
  composer_uris.py           # _extract_composerdata_context_uris, _project_from_global_composer_files, _project_from_folder_uri_list, _project_from_uri_list
  pane_view.py               # _COMPOSER_UUID_RE, _AICHAT_VIEW_PREFIX, _PANE_CONTAINER_PREFIX, _composer_ids_from_pane_view_state, cid_from_pane_view_key, cids_from_pane_container_value
  git.py                     # unchanged
```

The private-looking `_project_from_folder_uri_list`, `_project_from_global_composer_files`, `_project_from_uri_list`, `_project_from_workspace_identifier` are imported across package boundaries by [cursor_view/extraction/core.py](cursor_view/extraction/core.py). Re-export them through `cursor_view.projects.__init__` without the leading underscore (e.g. `project_from_folder_uri_list`) and update the extraction import site. Dropping the underscore marker fixes the "crossing package boundaries to import private names" smell.

Bonus: `extract_project_name_from_path` is 93 lines, right at the 100-line function limit, and contains nested early-exit branches for the Documents/codebase case (already deleted by the bug-fix pass) plus the home-directory / project-container / system-dir filters. Decompose it into a short dispatcher plus `_strip_windows_drive_prefix`, `_locate_user_home_dir`, `_choose_project_name_after_home`, `_reject_project_container_names` helpers in `projects/name.py` so `python-standards.mdc`'s ~100-line function limit is honored with headroom.

### 4. Split `cursor_view/cache/source_diff.py` into `cursor_view/cache/diff/`

Six concerns that each have their own section of comments today:

```
cursor_view/cache/diff/
  __init__.py             # re-exports DirtySet, compute_source_diff
  types.py                # SourceKey, SourceRowRecord, DirtySet
  hashing.py              # _hash_value, _composer_id_from_kv_key, _tool_call_id_from_bubble, _legacy_tab_ids, _cids_from_pane_container_value (thin wrappers around projects/pane_view.py after step 3)
  cache_state.py          # _load_cached_source_rows, _load_cached_tool_call_parent, _known_cids_by_workspace
  global_db.py            # _diff_global_cursor_disk_kv, _diff_global_legacy_chatdata, _diff_global_db
  workspace_db.py         # _fetch_workspace_item_rows, _classify_workspace_row, _diff_workspace_db, _diff_workspace_json
  propagation.py          # _process_deletions, _propagate_subagent_dirtiness, _trim_comp2ws_observability
  engine.py               # compute_source_diff orchestrator
```

Move the legacy `cursor_view/cache/source_diff.py` to a shim that re-exports from `cursor_view.cache.diff` so [cursor_view/cache/apply_delta.py](cursor_view/cache/apply_delta.py) and [cursor_view/chat_index.py](cursor_view/chat_index.py) aren't touched. Then delete the shim in the same change after updating the two callers — the rules forbid long-lived re-export files.

### 5. Split `cursor_view/cache/apply_delta.py` into `cursor_view/cache/delta/`

Five concerns flagged by the existing section comments:

```
cursor_view/cache/delta/
  __init__.py              # re-exports apply_delta, backfill_incremental_tables
  cached_state.py          # _load_cached_tool_call_parent, _load_ancestor_state, _compose_cached_state
  composer_rows.py         # _delete_cid_rows, _composer_hash, _upsert_composer_state, _extract_modified_chats
  project_only.py          # _project_only_refresh, _workspace_db_lookup
  metadata.py              # _apply_tool_call_parent_updates, _sync_source_row, _update_meta
  engine.py                # apply_delta orchestrator + _GLOBAL_WS sentinel
  backfill.py              # backfill_incremental_tables
```

Same shim-then-delete pattern as §4.

### 6. Split `cursor_view/sources/sqlite_data.py`

Four concerns in one file today. Split by source table:

```
cursor_view/sources/
  __init__.py
  sqlite_util.py           # j(), _connect_cursor_disk_kv
  bubbles.py               # _uri_from_bubble_context_entry, _extract_uris_from_bubble, _tool_call_from_bubble, iter_bubbles_from_disk_kv, iter_bubbles_for_cids
  composer_data.py         # iter_composer_data, iter_composer_data_for_cids
  item_table.py            # iter_chat_from_item_table + a new iter_global_legacy_chatdata (see §7)
```

While splitting, rewrite `iter_bubbles_from_disk_kv` and `iter_composer_data` to call the existing `_connect_cursor_disk_kv` helper (currently only used by the `_for_cids` variants) so the four iterators share one "open + probe `cursorDiskKV`" path. Drop the current double-nested `try/except sqlite3.DatabaseError: return`/outer-`try/finally` pattern in favor of `contextlib.closing` — the `sqlite-cursor-db.mdc` rule explicitly allows it as an alternative to `con = None` + `try/finally`.

### 7. Pull the legacy-chatdata SQL out of `extraction/core.py`

[cursor_view/extraction/core.py](cursor_view/extraction/core.py) `_collect_global_item_table_chats` opens the global DB directly with `sqlite3.connect(f"file:{global_db}?mode=ro", uri=True)` and runs a `j(cur, "ItemTable", "...chatdata")`. Extraction should not own the SQL layer. Move the iteration into a new `iter_global_legacy_chatdata(db)` generator in `sources/item_table.py` that yields `(tab_id, role, text)` and make `_collect_global_item_table_chats` a straight loop over that. Matches how the other passes already delegate to `sources/`.

### 8. Deduplicate pane-view cid parsing

Same regex and prefix constant live in two places today:

- [cursor_view/projects/inference.py](cursor_view/projects/inference.py) lines ~237-288 — `_COMPOSER_UUID_RE`, `_AICHAT_VIEW_PREFIX`, `_composer_ids_from_pane_view_state`.
- [cursor_view/cache/source_diff.py](cursor_view/cache/source_diff.py) lines ~41-183 — `_COMPOSER_UUID_RE`, `_PANE_VIEW_PREFIX`, `_PANE_CONTAINER_PREFIX`, `_cid_from_pane_view_key`, `_cids_from_pane_container_value`.

After step 3 there is one home for this logic: `cursor_view/projects/pane_view.py` exports:

- `COMPOSER_UUID_RE`
- `AICHAT_VIEW_PREFIX`
- `PANE_CONTAINER_PREFIX`
- `cid_from_pane_view_key(key: str) -> str`
- `cids_from_pane_container_value(raw: Any) -> list[str]`
- `composer_ids_from_pane_view_state(cur) -> list[str]`

`cache/diff/hashing.py` (from step 4) imports `cid_from_pane_view_key` and `cids_from_pane_container_value` instead of redefining them.

### 9. DRY `format_chat_for_frontend` on the cache write path

During one incremental refresh, [cursor_view/chat_index.py](cursor_view/chat_index.py) `_insert_chat` calls `format_chat_for_frontend` + `coalesce_consecutive_messages_by_role` internally, and then [cursor_view/cache/apply_delta.py](cursor_view/cache/apply_delta.py) `apply_delta` immediately runs the same two calls again against the same chat to hand the result to `_upsert_composer_state`. Same double-call in `backfill_incremental_tables`.

Change `_insert_chat` (post-refactor: `cursor_view/chat_index/rows.py`) to:

- accept `formatted_chat` + `coalesced_messages` as optional prebuilt args,
- or return `(formatted_chat, coalesced_messages)`,

and let the apply / backfill callers share the single formatted result with `_upsert_composer_state`. Equivalent behavior, one pass of message coalescing per chat per refresh.

### 10. Logger-style and typing cleanups (mechanical)

- Grep confirmed zero `logger.xxx(f"...")` uses across `cursor_view/*`; no change needed there.
- Add `data: dict[str, Any]` / return-type hints to helpers in `projects/composer_uris.py` (post-step-3) that currently take a bare `data` (`_project_from_global_composer_files`, `_extract_composerdata_context_uris`, `_project_from_root`) — the rule asks for typed signatures, and these are the most-called helpers during extraction.

### 11. Comment hygiene in `chat_format.py` and the pass modules

Strip narration from [cursor_view/chat_format.py](cursor_view/chat_format.py):

```
# Wrong (current)
# Generate a unique ID for this chat if it doesn't have one
session_id = str(uuid.uuid4())
...
# Get workspace_id from chat
workspace_id = chat.get("workspace_id", "unknown")
...
# Add workspace_id to the project data explicitly
project["workspace_id"] = workspace_id
...
# Create properly formatted chat object
return { ... }
```

Lines 63, 78, 81, 135, 138, 143 of the current file are straight narration and should be deleted. The substantive comments on the username-fallback branch (lines 84-89) and the git fallback (line 122) stay — those explain *why*.

Same sweep across the new `extraction/passes/*.py` modules after step 2: keep the comments that explain heuristic priority (e.g. "Explicit workspaceIdentifier (most reliable)" in `global_composers.py`) and drop the ones that narrate the next line.

## Frontend refactors

### 12. Decompose `frontend/src/components/AppContextMenu.js`

At 268 lines it exceeds the ~250-line soft cap in `react-components.mdc`. The component has four independently extractable pieces: DOM helpers, a selection save/restore hook, and a state-machine component. Target:

```
frontend/src/
  utils/
    dom.js                 # isEditableElement, findSelectionContainer
  hooks/
    useSavedSelection.js   # savedRangesRef, savedInputSelectionRef, save(), restore(), reset()
  components/
    AppContextMenu.js      # handlers + <Menu> JSX only (~130 lines)
```

`useSavedSelection` exposes `{ save(target, selectionText), restore(), reset() }` and owns the two refs plus the rAF-driven restore dance. `AppContextMenu` becomes the handler wiring plus the four `MenuItem`s, well under the limit.

### 13. Frontend layout changes that stay the same

The frontend `theme/`, `contexts/`, `hooks/`, `utils/`, `markdown/`, and feature folders under `components/` already match `react-components.mdc`. No other component is over the limit. The `App.js` shell (56 lines) and the chat-detail / chat-list siblings are already well-scoped, so the frontend pass is just the `AppContextMenu` split.

## Documentation and rule drift

### 14. Update `README.md` "Project layout"

Per `project-layout.mdc` and `comments-style.mdc`, layout changes must be reflected in the README in the same change. Update the three lists:

- `cursor_view/chat_index` becomes a subpackage description (schema + fingerprint + rebuild + rows + index).
- `cursor_view/extraction/passes/` is mentioned alongside `core.py`.
- `cursor_view/projects/` enumerates the new submodules (`name`, `uris`, `workspace_json`, `workspace_sources`, `workspace_identifier`, `composer_uris`, `pane_view`, `inference`, `git`).
- `cursor_view/cache/diff/` and `cursor_view/cache/delta/` replace the single-file descriptions of `source_diff.py` / `apply_delta.py`.
- `cursor_view/sources/` enumerates `sqlite_util`, `bubbles`, `composer_data`, `item_table`.
- The frontend "hooks" list gains `useSavedSelection`; the "utils" list gains `dom`.

### 15. Review and refresh `.cursor/rules/`

The [.cursor/rules/comments-style.mdc](.cursor/rules/comments-style.mdc) "rule drift" clause requires that any refactor that materially changes a convention captured in a rule updates that rule in the same change. Walk every rule file once and apply the edits below. The split-plus-citation examples in each rule are what keep the rule grounded; they must point at files that still exist and sizes that still apply.

#### 15a. [.cursor/rules/project-layout.mdc](.cursor/rules/project-layout.mdc) (always apply)

Updates required after the splits:

- The "Canonical subpackages" list currently reads `extraction/`, `export/`, `projects/`, `sources/`, `desktop/`. Add `cache/diff/`, `cache/delta/`, `chat_index/` (upgraded from a single module), and note that `extraction/` now contains a `passes/` subpackage. The list stays alphabetical.
- Add a new bullet under "Repository layout": **"Tests live under `tests/` at the repo root and use stdlib `unittest`. Any new behavior that touches the chat-index refresh path must land with a synthetic-Cursor-DB regression test in `tests/test_chat_index_incremental.py` or a new sibling."** The current rule omits `tests/` entirely, which is why the incremental-refresh plan had to add test guidance in its own plan file instead of deferring to the rule.
- The "Thin shims at the repo root" bullet still references `terminal.py`, `desktop.py`, `cursor_view_main.py`. No edit here, but the bug #12 fix (when it lands in the follow-up) will want to double-check that `cursor_view/terminal.py` is itself shim-shaped (no import-time work).

#### 15b. [.cursor/rules/python-standards.mdc](.cursor/rules/python-standards.mdc) (`**/*.py`)

Updates required:

- Refresh motivating examples. The current text cites "the original 377-line `cursor_view/extraction.py` and 547-line `cursor_view/export_html.py`". Replace with the new, post-refactor offenders this plan addresses: the 819-line pre-split `cursor_view/chat_index.py` that became `cursor_view/chat_index/`, the 716-line pre-split `cursor_view/extraction/core.py` that became `cursor_view/extraction/passes/`, and the 629-line pre-split `cursor_view/cache/source_diff.py` that became `cursor_view/cache/diff/`. The older examples can be retained as historical citations in a single trailing line, since git history is the archive.
- Refresh the function-size motivating example. Current text cites `extract_chats` post-refactor; after this plan it's still valid but `extract_project_name_from_path` (93 lines today, being decomposed in step 3) is a better contemporary example of "break a function that is starting to crowd the 100-line limit".
- Add a new short clause under a new **"Cross-package imports"** subheading:

  > Do not import underscore-prefixed helpers across package boundaries. If a helper is needed by another subpackage, drop the leading underscore and re-export it through its owning package's `__init__.py`. Motivating example: `cursor_view/extraction/core.py` used to import `_project_from_folder_uri_list`, `_project_from_global_composer_files`, `_project_from_uri_list`, and `_project_from_workspace_identifier` from `cursor_view/projects/inference.py`; step 3 of the structure-cleanup plan renamed those to public aliases and re-exported them from `cursor_view.projects`.

- Add a new short clause under a new **"Import-time side effects"** subheading:

  > Module-load must be free of external side effects — no filesystem sweeps, no network, no Flask app construction, no cache-directory mutation. Side-effecting work belongs inside a `main()` / `run_*()` function that the CLI or test harness calls explicitly. Motivating example: the pre-refactor `cursor_view/terminal.py` ran `cleanup_orphan_temp_files()` and `app = create_app()` at module top-level, so merely importing the module triggered cache-dir writes and Flask construction (see bug #12 in the structure-cleanup plan's Bugs section).

#### 15c. [.cursor/rules/sqlite-cursor-db.mdc](.cursor/rules/sqlite-cursor-db.mdc) (`**/*.py`)

No updates required for the structural splits themselves — the cache tables and row-hash invariants are unchanged. But the bug-inventory in this plan identifies two caching invariants the rule does not yet mention. When the follow-up bug-fix plan lands, these two clauses should be added here (tracked via the rule-drift clause):

- A note under "Invalidation: hash rows, don't stat files" that the **coarse fingerprint must include the `workspace.json` sidecar** the fine diff reads, since the coarse gate short-circuits everything else (bug #4).
- A note under "Cache tables" that **`tool_call_parent` entries must be cleared whenever their originating bubble row is deleted**, not only when the parent composer is deleted (bug #5). This belongs in the rule because it is a correctness invariant on the cache's steady state, not just an implementation detail.

These additions are NOT part of this refactor-only plan — they land with the follow-up fixes. The review step notes them here so the rule-drift check is complete.

#### 15d. [.cursor/rules/known-bugs.mdc](.cursor/rules/known-bugs.mdc) (always apply)

No content edits. The `TODO(bug):` convention is still correct and this plan adds 13 new candidates to the inventory (see "Bugs to document" above). The follow-up fix plan will be the one that removes markers as fixes land, matching the previous cycle.

#### 15e. [.cursor/rules/react-components.mdc](.cursor/rules/react-components.mdc) (`frontend/src/**/*.{js,jsx}`)

Updates required:

- The ~250-line motivating example currently cites only `ChatList.js` at 670 lines (pre-refactor). Add `AppContextMenu.js` at 268 lines as the contemporary example, and note that its split produced a new `hooks/useSavedSelection.js` and `utils/dom.js`.
- Rename the current "Shared logic and helpers" bullet that lists `useChatSummaries`, `useExportFlow`, `useExportWarningPreference` to also include the new `useSavedSelection`.

#### 15f. [.cursor/rules/comments-style.mdc](.cursor/rules/comments-style.mdc) (always apply)

No content edits. The rule's two clauses (intent-only comments + rule drift) are exactly what this plan is applying; the rule itself already captures them correctly.

#### 15g. New rule: `.cursor/rules/frontend-hooks.mdc` (`frontend/src/hooks/**/*.{js,jsx}`)

The `react-components.mdc` rule covers *components* but does not enumerate the discipline expected of the code inside `hooks/`. The `useChatSummaries.refresh()` bug (#11 in this plan's Bugs section) is a rule-shaped failure — a hook that is known to need cancellation doesn't have it, and a helper callback that is passed to memoized children is not wrapped in `useCallback`. Author a new focused rule so the next hook author has explicit guidance.

Frontmatter:

```yaml
---
description: Discipline for custom hooks under frontend/src/hooks/
globs: frontend/src/hooks/**/*.{js,jsx}
alwaysApply: false
---
```

Body (~30 lines) covering:

- **Cancellation on every awaited effect.** Any hook with a `useEffect` that `await`s a network request (or any promise that races with the hook's inputs) must respect a local `cancelled` flag after each `await` boundary and ignore the result when cancelled. The dual of `useEffect`'s cancellation — a manual-trigger action like `refresh()` — must participate in the same flag (typically via a ref to the latest request id) so a slow response from a stale call cannot overwrite fresh state. Motivating example: `useChatSummaries.refresh` was patched to share a latest-request-id ref with its effect after the initial split missed this.
- **Stable callback references.** Any callback a hook returns that is likely to be passed to a memoized child or used in another hook's dependency list must be wrapped in `useCallback` with an accurate dependency list. Returning a fresh closure every render defeats memoization and silently inflates re-renders. Motivating example: `useChatSummaries` originally returned a plain `async function refresh()` and a typo in the deps list would have gone undetected because there was no `useCallback` shape to enforce the rule.
- **One concern per hook.** Hooks that combine unrelated concerns (e.g. both "fetch data" and "drive a multi-step dialog machine") must be split — the existing `useExportFlow` + `useExportWarningPreference` split is the canonical shape. A hook whose return object has more than ~8 keys is usually doing too much and should be decomposed.
- **Expose minimal state.** Prefer narrow return shapes (`{ data, loading, error, refresh }`) over returning internal refs or raw setter functions. The setter belongs to the hook; the consumer gets a named action.

Cite `useChatSummaries`, `useExportFlow`, and `useExportWarningPreference` as the three canonical hooks the rule applies to, with `useChatSummaries` as the "not-quite-right-yet" example (bug #11 fixed in the follow-up) once that landed.

#### 15h. Cross-check and prune

After editing each rule, verify every bullet can still be anchored to a real file path in the post-refactor tree (the `project-layout.mdc` authoring notes already require this). Drop any motivating example whose referenced file no longer exists in its old shape — better to cite nothing than to cite a stale file.

## Out of scope

- One behavior change is in scope: the bubble-ordering fix documented in the "Behavior fix in scope" section above (`fix_bubble_ordering` todo). `INDEX_SCHEMA_VERSION` stays at `2` because the scrambled caches were never shipped to users; any developer running an affected cache can delete `chat-index.sqlite3` manually or hit the UI's Refresh button to force a rebuild.
- No other behavior changes, no SQL changes, no new public API, no new HTTP routes.
- No performance changes beyond the single-pass de-duplication in step 9 and the per-cid `composerData` read that the ordering fix requires (amortized by the existing cid-scoped `iter_composer_data_for_cids` path).
- No frontend behavior changes; `AppContextMenu`'s selection behavior is refactored, not altered.
- The bugs catalogued in the next section are **documented only**; fixing them belongs in a follow-up plan modeled on [.cursor/plans/fix_documented_bugs_2848bfcb.plan.md](.cursor/plans/fix_documented_bugs_2848bfcb.plan.md). Each will be annotated with `# TODO(bug):` per [.cursor/rules/known-bugs.mdc](.cursor/rules/known-bugs.mdc) at the site where it lives (alongside the refactor edit that touches that site); no behavior change for those lands in this plan.

## Behavior fix in scope: scrambled message order (bug #0)

This fix is the one behavior change this plan permits, because it is user-visible, severe, and cannot reasonably wait for the follow-up bug-fix plan: the chat-detail view shows messages in the wrong order, with unrelated user prompts silently merged into single bubbles, and the message count in the UI is a small fraction of the real transcript. It was discovered during the plan review; the reproducer is session `393dba99-0a5e-48a6-8ae3-abcfc6c028fc`, whose real transcript has 8 distinct user prompts ("Execute todo 5...", "Execute todo 6...", ..., "Commit these changes...") and 199 total bubbles, but the cache shows only 12 messages, with the user prompts in the order `todo 8, 9, 7, 5, [commit + todo 6 merged], "entirely implemented"`.

### How Cursor actually stores bubble order

Modern Cursor builds store each bubble as a separate row keyed `bubbleId:<cid>:<bubbleId>` in `cursorDiskKV`, and record the canonical chronological order separately on the composer itself:

```
composerData:<cid>.fullConversationHeadersOnly = [
  {"bubbleId": "9529d6c7-...", "type": 1},
  {"bubbleId": "0cbf18c3-...", "type": 2, "grouping": {...}},
  {"bubbleId": "a98473b7-...", "type": 2, "grouping": {..., "toolCallId": "toolu_..."}},
  ...
]
```

Verified on the reproducer composer:

- `len(fullConversationHeadersOnly) == 199` matches `SELECT COUNT(*) FROM cursorDiskKV WHERE key LIKE 'bubbleId:393dba99-...:%'`.
- The 8 entries whose `type == 1` are exactly the 8 user prompts in `todo 5 → 6 → 7 → 8 → 9 → 10 → "entirely implemented" → commit` order.
- There is no legacy `conversation` key on this composer (modern Cursor deprecated it), so Pass 3's `_collect_global_composers` contributes zero messages here.

### Where the current code goes wrong

The extraction pipeline never reads `fullConversationHeadersOnly`. Three concrete defects:

1. [cursor_view/sources/sqlite_data.py](cursor_view/sources/sqlite_data.py) `iter_bubbles_from_disk_kv` runs `SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'` with no `ORDER BY`. SQLite therefore returns the rows in the implicit primary-key (key-string) order. Cursor's bubbleIds are UUIDv4, so sorting by bubbleId is essentially a random permutation of chronological order.

2. [cursor_view/sources/sqlite_data.py](cursor_view/sources/sqlite_data.py) `iter_bubbles_for_cids` has the same issue — its per-cid range scan `WHERE key > 'bubbleId:<cid>:' AND key < 'bubbleId:<cid>;'` also returns rows in PK order (the `_for_cids` helper only narrows the set, it does not reorder). So the incremental refresh inherits the same scrambling.

3. [cursor_view/extraction/core.py](cursor_view/extraction/core.py) `_collect_global_bubbles` (Pass 2) appends every bubble's text into `sessions[cid]["messages"].append(...)` in the order the iterator yields them. Nothing downstream reorders. `_collect_global_composers` (Pass 3) uses `data.get("conversation", [])` which is empty on modern composers, so it contributes no re-ordering signal either. `_finalize_sessions` (Pass 8) sorts *sessions* by recency; it never sorts a session's *messages*.

The scrambled order then feeds `coalesce_consecutive_messages_by_role`, which merges *consecutive same-role* entries. The coalescer is correct per its contract, but when the bubble order is random, "consecutive" stops meaning "adjacent in the real transcript" and starts meaning "alphabetically adjacent bubbleIds that happen to share a role." That is exactly why `position 9` in the reproducer cache contains the text `"Commit these changes for me with a descriptive commit message. Execute todo 6 in @.cursor/plans/..."` — two real user prompts that are chronologically six turns apart happened to land alphabetically adjacent with no other user bubbleId between them in the key-sorted output.

### Why the preview looks right more often than the detail

`_preview_from_messages` iterates the coalesced list and breaks on the first entry with `role == "user"`. In the scrambled order the "first user message encountered" is the user bubble with the alphabetically-smallest bubbleId — which is not the chronologically-first prompt, just the one whose UUID sorts first. In many cases this happens to be a meaningful-looking user message (because all user prompts are real prompts), so the preview can look plausible even when the detail view is gibberish. The preview is equally wrong per the spec; its wrongness is just less obvious than "messages in rewound order."

### Secondary consequence: many bubbles vanish from the cache

199 raw bubbles produce only 12 coalesced cache messages on the reproducer because `iter_bubbles_from_disk_kv` filters out bubbles with no text, no URIs, and no tool call (`if not txt and not file_uris and not folder_uris and tool_call is None: continue`). That filter is correct — assistant tool-call result bubbles are not user-facing — but it means the resulting "message" count is a coalesce of a much smaller alternating stream. Fixing the order does not recover those dropped bubbles; it fixes *what the surviving messages mean*. Recovering dropped assistant content would be a separate policy change (render tool-call payloads as assistant blocks), and is out of scope here.

### Fix

The fix is mechanically small and localized to extraction + one cache column. Correctness requires that the ordering is established *before* coalescing runs, not as a post-hoc sort of the already-coalesced output.

1. **Read the order map up front.** In [cursor_view/sources/sqlite_data.py](cursor_view/sources/sqlite_data.py), add a new helper `iter_bubble_order_for_cids(db, cids) -> Iterable[tuple[str, dict[str, int]]]` that reads `composerData:<cid>` for each cid and returns `(cid, {bubbleId -> ordinal})`. The ordinal is the index into `fullConversationHeadersOnly`. Composers that lack the field (very old Cursor builds) return `{}`, and the caller falls back to current behavior for those.

2. **Restructure Pass 2 so bubbles are ordered.** In [cursor_view/extraction/core.py](cursor_view/extraction/core.py) `_collect_global_bubbles` and `_collect_global_composers`, change the flow to:
   - Pass 3 moves *before* Pass 2 (or a dedicated pre-pass reads only the composers we need and caches the order map).
   - Pass 2 becomes order-aware: it still streams bubbles from `iter_bubbles_for_cids` / `iter_bubbles_from_disk_kv`, but appends each message into a *per-cid dict keyed by ordinal* rather than a list. When the ordinal is missing (composer has no `fullConversationHeadersOnly`), fall through to the current "append in encountered order" behavior so behavior is no worse on old data.
   - At the end of Pass 2 (or inside Pass 8 `_finalize_sessions`, before the empty-session drop), replace each cid's `sessions[cid]["messages"]` with a list of `ordinal -> message` sorted by ordinal. Missing ordinals pack together at the end in encountered order.
   - `coalesce_consecutive_messages_by_role` now sees messages in true chronological order, and its consecutive-same-role merge does what it claims.

3. **Thread an `ordinal` through to the cache write path.** The cache's `chat_message` PK is `(session_id, position)` and `get_chat` orders by `position ASC`. `_insert_chat` currently uses `enumerate(messages)` to populate `position`, which is fine once the upstream list is ordered; no schema change required for the fix itself. But for safety during the incremental apply path (where a partial re-extract of one composer could otherwise produce a position collision with stale rows), `_delete_cid_rows` already deletes all rows by `session_id` before `_insert_chat` runs, so re-numbering from 0 on each re-insert is correct. Document this invariant as a docstring on `_insert_chat` in [cursor_view/chat_index/rows.py](cursor_view/chat_index/rows.py) (post-step-1) so a future contributor doesn't try to make position globally stable.

4. **No schema-version bump needed.** The scrambled caches never shipped to users, so no automatic on-first-launch rebuild is required. `INDEX_SCHEMA_VERSION` stays at `2`. Developers who happen to have an affected local `chat-index.sqlite3` can either delete the cache file or hit the UI's Refresh button (which calls `ensure_current(force=True)`) to force a rebuild with the corrected ordering. Leaving the version pinned also keeps the incremental refresh path usable for everyone else immediately — no one-time full rebuild is paid at the first post-fix startup.

5. **Test.** Extend `tests/test_chat_index_incremental.py` with a new test `test_bubble_order_uses_headers_array`:
   - Synthetic composer has three bubbles with bubbleIds whose alphabetical order is `b_zzz`, `b_mmm`, `b_aaa`.
   - `composerData.fullConversationHeadersOnly` records them in the reverse order `[b_aaa (user), b_mmm (asst), b_zzz (user)]`.
   - Assert that after a full rebuild, `SELECT role, content FROM chat_message WHERE session_id=? ORDER BY position ASC` returns rows in the `fullConversationHeadersOnly` order, not the alphabetical order.
   - Assert that after a subsequent bubble mutation refresh (incremental path), the order is preserved.

### Why this is a behavior change the refactor plan should absorb, and why it goes first

This plan is otherwise "structural only, no behavior changes." Including this fix, and sequencing it ahead of every split, is justified on three grounds:

- The bug is actively harmful to the tool's primary use case (reading old chats) in a way that users can see, unlike the more subtle race and leak bugs documented in the next section. Every day the refactor takes is another day of gibberish chat histories if the fix trails it.
- The fix is localized: one new helper in `cursor_view/sources/sqlite_data.py`, one re-ordering change in `cursor_view/extraction/core.py`, and one new test in `tests/test_chat_index_incremental.py`. It touches only files that later split steps will move, so the sequencing is "fix in place first, then split the files" — no structural todo blocks the fix, and no fix-site disappears before the fix lands.
- The later split steps (`split_sources`, `split_extraction_core`) pick up the two edits as ordinary content when they relocate those files. The move is mechanical: the new ordering helper lands in `cursor_view/sources/bubbles.py` (post-`split_sources`) and the re-ordering becomes part of whichever pass module owns Pass 2 in `cursor_view/extraction/passes/` (post-`split_extraction_core`). No step needs to re-do the fix; each split step just carries it to its new home.

All other bugs discovered in the review stay documentation-only below.

## Bugs to document (NOT fix as part of this refactor)

Discovered during a deliberate bug-hunt over the caching system (which had the most churn since the last review) and the extraction / frontend paths that feed it. Each item will get an inline `# TODO(bug):` (Python) or `// TODO(bug):` (JS) marker at the cited site during whichever split touches that file; they are listed here so the follow-up plan has a single source of truth.

### Connection-leak / SQLite-hygiene bugs

1. [cursor_view/extraction/core.py](cursor_view/extraction/core.py) `_collect_global_item_table_chats` (lines ~512-543) is the same "open-outside-try" shape that the previous bugs-plan already fixed in [cursor_view/sources/sqlite_data.py](cursor_view/sources/sqlite_data.py). `con = sqlite3.connect(...)` runs on the first line of the `try`; if any subsequent statement raises, control jumps to `except Exception as e: logger.debug(...)` without ever calling `con.close()`. The broad `except Exception` also swallows real errors at `debug` level, the same anti-pattern that was fixed in diagnostics. Plan step 7 (`move_legacy_chatdata_sql`) naturally relocates this logic into `sources/item_table.py` where the same `con = None` + outer `try/finally` pattern applies; mark `TODO(bug):` on the relocated site until the follow-up plan lands.

2. [cursor_view/projects/git.py](cursor_view/projects/git.py) `extract_project_from_git_repos` (lines ~34-105) has the same shape: `con = sqlite3.connect(...)` at the top of `try`, multiple `con.close()` calls on each early-return branch, and an `except Exception as e:` at the bottom that does NOT call `con.close()`. Any exception between `connect` and one of the early-return paths leaks the connection. Follow `.cursor/rules/sqlite-cursor-db.mdc`'s `con = None` + `try/finally` pattern in the fix.

3. [cursor_view/projects/git.py](cursor_view/projects/git.py) `extract_project_from_git_repos` is wrapped in `@lru_cache(maxsize=512)`, so `None` results are cached permanently per `workspace_id`. If a workspace's `scm:view:visibleRepositories` is populated after the first call (e.g. the user initializes a repo during the session), the cached `None` hides the new value until the process restarts. Either drop the cache, give it a TTL, or invalidate on the same fingerprint flips that drive the chat-index refresh.

### Caching / incremental-refresh bugs

4. [cursor_view/chat_index.py](cursor_view/chat_index.py) `_current_source_fingerprint` (lines ~364-405) hashes the `state.vscdb` file and its WAL sibling, but **not the workspace.json sidecar**. The fine-grained diff in [cursor_view/cache/source_diff.py](cursor_view/cache/source_diff.py) `_diff_workspace_json` DOES hash workspace.json, but the coarse fingerprint is the only gate that decides whether the fine diff runs at all. Result: if a user edits `workspace.json` (rare but possible — e.g. changing the workspace's root folder URI) without touching `state.vscdb`, the coarse fingerprint is unchanged, `ensure_current` returns cache-hit, and the workspace's project name goes stale until the next `state.vscdb` write. Fix by folding workspace.json's `(mtime_ns, size)` into `_source_entry` so the coarse fingerprint flips on sidecar edits.

5. [cursor_view/cache/source_diff.py](cursor_view/cache/source_diff.py) lines ~605-611 only emits `tool_call_parent_updates[tcid] = None` when the **parent composer itself** is in `deleted_cids`:

   ```python
   for tcid, parent in cached_tcp.items():
       if parent in dirty.deleted_cids:
           dirty.tool_call_parent_updates.setdefault(tcid, None)
   ```

   Nothing clears a tcid entry when the specific *bubble* that carried `toolFormerData.toolCallId` is deleted while the parent composer survives with other bubbles. The persisted `tool_call_parent` row stays forever and can incorrectly be resurrected by Pass 5 for any future `task-<tcid>` subagent. In practice Cursor reuses tcids rarely, so the odds of a misattribution are low — but the cleanup is logically missing. Fix by emitting `tool_call_parent_updates[tcid] = None` for every cached tcid whose originating `SourceKey(db, "cursorDiskKV", "bubbleId:<parent>:<bid>")` is absent from the fresh snapshot (track the source key alongside the persisted tcid, either via a new column on `tool_call_parent` or via a per-refresh side-map).

6. [cursor_view/cache/source_diff.py](cursor_view/cache/source_diff.py) + [cursor_view/cache/apply_delta.py](cursor_view/cache/apply_delta.py) interact across a TOCTOU window. `compute_source_diff` opens read-only connections to the source DBs, hashes rows into `source_row_snapshot`, and returns. Then `apply_delta._extract_modified_chats` re-opens the same source DBs to run scoped extraction. Between the two, Cursor can commit writes, so:

   - extraction may observe a bubble that was not in the diff's snapshot (the new bubble's row_hash is never written to `source_row`, so next refresh re-classifies the whole composer as modified and re-extracts); or
   - extraction may observe a bubble that DID change between the diff and the extract — the diff's hash is the old one, the extracted payload is the new one, and the cache ends up with correct data but a stale hash, causing one extra refresh cycle.

   Both cases self-heal after one or two more refreshes, but they do cause silent wasted work. Worth documenting; a fix would require either a single source-DB snapshot spanning diff + extract, or a post-apply re-hash of the rows the extraction actually consumed.

7. [cursor_view/cache/source_diff.py](cursor_view/cache/source_diff.py) `_diff_global_db` issues two independent SELECTs (`_diff_global_cursor_disk_kv` then `_diff_global_legacy_chatdata`) on the same connection, but Python's default `sqlite3` isolation commits between statements, so each SELECT observes its own snapshot of the global DB. A cursorDiskKV write + legacy-chatdata write racing between the two selects can produce a diff where tool-call upserts reference composers whose legacy-chatdata row is already stale (or vice versa). Fix by wrapping `_diff_global_db` in an explicit `BEGIN` (and the workspace-DB sibling too) so the per-DB read is transactional.

### Extraction / formatting bugs

8. [cursor_view/sources/sqlite_data.py](cursor_view/sources/sqlite_data.py) `iter_chat_from_item_table` (lines ~226-240) iterates `ItemTable` rows whose keys start with `aiService.prompts` or `aiService.generations`, then yields every `item["id"]` as a **composerId** with role=`user` / `assistant` depending on the prefix. Those ids are prompt / generation ids, not composer ids — extraction then builds fake single-message "chats" keyed by them that can pollute the chat list with one-turn entries whose text is an AI prompt or generation record. The legacy path probably predates the bubble-based storage and should either be removed or gated behind a diagnostic flag. Audit by counting sessions whose `session_id` does not match `^([0-9a-f-]{36}|task-.*)$` after a full rebuild.

9. [cursor_view/sources/sqlite_data.py](cursor_view/sources/sqlite_data.py) `iter_chat_from_item_table` (lines ~214-223) reads `composer.composerData.allComposers[*].messages` and yields messages with `role = msg.get("role", "unknown")`. Downstream `chat_format.coalesce_consecutive_messages_by_role` silently maps anything other than `"user"` to `"assistant"`, so a legacy `messages[]` entry without a role is invisibly attributed to the assistant. The `allComposers` array in modern Cursor builds doesn't carry a `messages` field at all, so this path is likely dead code; if it is, delete it rather than preserving a silently-lossy fallback.

10. [cursor_view/chat_format.py](cursor_view/chat_format.py) `format_chat_for_frontend` catches `Exception` (line 152) and returns a fallback dict with `session_id = str(uuid.uuid4())` instead of the composer's real id. That stub is fed straight into `ChatIndex._insert_chat` and inserted into `chat_summary` under a random primary key. Because `_delete_cid_rows` deletes by the real cid, the stub lingers forever (with a new random session id each refresh) and API calls by the real session id return 404. The exception handler should log and re-raise, or at least fall back to `chat["session"]["composerId"]` so subsequent refreshes can overwrite the bad row.

### Frontend bugs

11. [frontend/src/hooks/useChatSummaries.js](frontend/src/hooks/useChatSummaries.js) `refresh()` (lines ~67-83) has no cancellation flag and is not wrapped in `useCallback`, so:

    - A slow `refresh()` that resolves after a newer query-change effect has already updated state will overwrite the fresh result. The `useEffect` path correctly respects a `cancelled` flag, but the manual refresh button bypasses it.
    - The unstable function reference forces any memoized consumer (e.g. the `<Button onClick={refresh}>` in `ChatList`) to re-subscribe every render.

    Fix by sharing a single mutable "latest request id" ref between the effect and `refresh`, ignoring late responses whose id no longer matches; wrap `refresh` in `useCallback([query])`.

### Process / import-time side-effects

12. [cursor_view/terminal.py](cursor_view/terminal.py) line 21 calls `cleanup_orphan_temp_files()` **at module import time**, alongside `app = create_app()` at line 23. Importing `cursor_view.terminal` from anywhere — including places that merely want to read `run_server` as a function reference — triggers a cache-directory sweep and Flask app construction. Mirror [cursor_view/desktop/__init__.py](cursor_view/desktop/__init__.py)'s pattern by moving both calls inside `run_server` / `main`.

### Logging / privacy

13. [cursor_view/routes.py](cursor_view/routes.py) `get_chats` (lines ~50-55) logs the full raw user query string at `INFO` level (`logger.info("Returning %s chat summaries (query=%r total=%s)", ..., query, ...)`). For a local, privacy-focused tool whose whole premise is "no data leaves your machine", writing the user's search terms to a structured log file is a minor but surprising privacy footprint. Demote to `DEBUG` or log only the token count.

### Severity ranking (for the follow-up plan)

- High — #1, #2, #10 (correctness / leaks on the hot path): connection leaks in extraction's legacy chatdata scrape and in the SCM fallback, and the random-session-id formatting fallback.
- Medium — #4, #5, #11 (refresh correctness / UI race): missing workspace.json sidecar in the coarse fingerprint, stale `tool_call_parent` on bubble deletes, racey `refresh()` in the frontend hook.
- Low — #3, #6, #7, #12, #13 (self-healing or minor): lru_cache of None, TOCTOU between diff and extract, non-transactional per-DB reads, import-time side effects, query logging.
- Audit only — #8, #9 (likely dead code that needs confirmation before deletion): `aiService.*` fake-composer yields and `composer.composerData.messages` legacy path.

## Risk and verification

- Every Python split is a file move + re-export; `import`-time compatibility is guaranteed by the package `__init__.py` shims listed above. A single smoke-test is enough: `python -c "from cursor_view.chat_index import get_chat_index, INDEX_SCHEMA_VERSION; from cursor_view.cache import DirtySet, compute_source_diff, apply_delta, backfill_incremental_tables; from cursor_view.extraction import extract_chats, CachedExtractionState; from cursor_view.projects import workspace_info; from cursor_view.sources.bubbles import iter_bubbles_from_disk_kv, iter_bubbles_for_cids; from cursor_view.sources.composer_data import iter_composer_data, iter_composer_data_for_cids; from cursor_view.sources.item_table import iter_chat_from_item_table"`.
- `tests/test_chat_index_incremental.py` exercises the four behaviors the incremental path is specifically designed for — run it after the split to confirm refactored apply/diff modules still compose correctly. The new `test_bubble_order_uses_headers_array` case (see `fix_bubble_ordering` step) guards against regression on the ordering fix.
- Manual verification after the fix lands: open the reproducer at `http://127.0.0.1:5000/chat/393dba99-0a5e-48a6-8ae3-abcfc6c028fc`; the first user message should read `"Execute todo 5..."` (not `"Execute todo 8..."`), the last user message should read `"Commit these changes for me..."` (not mixed with `"Execute todo 6..."`), and no single rendered bubble should contain the phrase `"Execute todo"` more than once.
- `cd frontend && npm run build` must still succeed without new warnings after the `AppContextMenu` split.
