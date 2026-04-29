---
name: Fix unknown subagent project
overview: Diagnose why the `task-toolu_01XvF39QpU8SG7TECB7EWnWg` ("Explore Bruno test collection") chat resolves to project `(unknown)` / workspace `(global)`, then implement the targeted fix the diagnostic reveals, with tests and rule/doc updates kept in lockstep per repository conventions.
todos:
  - id: explanation
    content: Write up the root-cause explanation (Causes 1-4) for the user before any code changes.
    status: pending
  - id: diagnostic
    content: Extend cursor_view/extraction/diagnostics.py with trace_project_resolution(cid) plus a python -m entry point, using read-only SQLite + lazy %-logging.
    status: pending
  - id: run-diagnostic
    content: Run the diagnostic against task-toolu_01XvF39QpU8SG7TECB7EWnWg and identify which of Causes 1-4 fires.
    status: pending
  - id: fix-targeted
    content: Implement the targeted fix for whichever cause was confirmed (orphan-filter relaxation, scoped Pass 6 cached-edge fallback, dead-chain accept, or orphan-task soft-delete).
    status: pending
  - id: regression-test
    content: Add a synthetic-Cursor-DB regression test in tests/test_chat_index_incremental.py covering the chosen cause; ensure python -m unittest discover -s tests stays green.
    status: pending
  - id: rule-review
    content: Review every .cursor/rules/*.mdc rule the change touches (sqlite-cursor-db, comments-style, known-bugs, project-layout, python-standards, chat-index-refresh) and update any that drifted.
    status: pending
  - id: docs-sync
    content: Update README.md (Troubleshooting section for the diagnostic CLI) and .github/CONTRIBUTING.md (Project layout) per project-layout.mdc Documentation sync, only where the change is user-visible or layout-affecting.
    status: pending
  - id: final-review
    content: "Final pass: re-read all touched files for sibling bugs (cycle handling, propagation gate triggers, chat_format fallback ladder, %-style logging, RO SQLite connections, no silent code-path deletions per known-bugs.mdc)."
    status: pending
isProject: false
---

## Background: how a chat earns a project

Project resolution lives in [cursor_view/extraction/core.py](cursor_view/extraction/core.py) as eight ordered passes; the pass-order docstring at lines 8 to 38 is canon. The relevant slice for `task-<toolCallId>` subagents:

- Pass 2 (`[cursor_view/extraction/passes/global_bubbles.py](cursor_view/extraction/passes/global_bubbles.py)`) creates `sessions[cid]` for every composer it sees in `cursorDiskKV`, sets `comp2ws[cid] = "(global)"` on first sight (line 134), and records `tool_call_parent[toolCallId] = parent_cid` for every bubble whose `toolFormerData.toolCallId` is set (lines 124-131).
- Pass 5 (`[cursor_view/extraction/passes/task_subagents.py](cursor_view/extraction/passes/task_subagents.py)`) walks `sessions.keys()` and for any `cid.startswith("task-")` looks up `merged_map[cid[5:]]` (live + cached `tool_call_parent`) to set `subagent_parent[cid] = parent_cid`.
- Pass 6 (`[cursor_view/extraction/passes/subagent_inheritance.py](cursor_view/extraction/passes/subagent_inheritance.py)`) walks the parent chain (cap 8 hops) and copies the first ancestor's `comp2ws` (if not `(global)`) or `_inferred_project` onto the child.
- Pass 8 (`[cursor_view/extraction/passes/finalize.py](cursor_view/extraction/passes/finalize.py)` lines 50-58) is where unresolved chats fall through to the literal sentinel `{"name": "(unknown)", "rootPath": "(unknown)"}` while keeping `workspace_id == "(global)"` — exactly what the screenshot shows.

The screenshot's signal triple (`Project: (unknown)`, `Path: (unknown)`, `Workspace: (global)`, `DB: state.vscdb`) means: Pass 2 saw the cid in `cursorDiskKV` (so `comp2ws == "(global)"` was seeded), but Passes 5+6 produced no resolved ancestor and Pass 4 found no bubble URIs.

## Likely root causes (must distinguish before fixing)

1. **Orphan-bubble drop on the parent.** [cursor_view/extraction/passes/global_bubbles.py](cursor_view/extraction/passes/global_bubbles.py) lines 108-117 drop the parent's tool-call bubble (no `tool_call_parent` upsert) when it is absent from the parent's `composerData.fullConversationHeadersOnly`. Pass 5 then has no edge to follow.
2. **Scoped-mode walk gap.** Pass 6 walks via `subagent_parent.get(ancestor)` (line 71). In scoped re-extraction `subagent_parent` is only built from `sessions.keys()` (Pass 5 line 54), which is the dirty set — so a non-dirty intermediate `task-*` ancestor never gets its `subagent_parent` rebuilt and the walk dies. [cursor_view/cache/delta/cached_state.py](cursor_view/cache/delta/cached_state.py) `_load_ancestor_state` only seeds `ancestor_comp2ws` / `ancestor_inferred_project`, not `ancestor_subagent_parent`.
3. **Dead chain at the top.** The ultimate ancestor is itself a global chat with no `workspaceIdentifier`, no `_inferred_project`, and no pane-view-key promotion. Walk reaches it and stops legitimately.
4. **Edge legitimately deleted.** Parent composer was deleted, but the `task-*` row remains. `tool_call_parent` row was cleaned up but the orphan child is still in `cursorDiskKV`.

These four require different fixes; we MUST diagnose first.

## Resolution flow

```mermaid
flowchart TD
    A[task-toolu_xxx in cursorDiskKV] --> B{Pass 2: bubble for tcid seen?}
    B -- no --> M[Cause 1 or 4]
    B -- yes --> C{tool_call_parent[tcid] set?}
    C -- no --> N[Cause 1 orphan filter]
    C -- yes --> D{Pass 5 set subagent_parent?}
    D -- no --> O[scoped sessions miss]
    D -- yes --> E{Pass 6 walk hits resolved ws_id?}
    E -- yes --> R[project resolved]
    E -- no --> F{ancestor is task-* with no subagent_parent?}
    F -- yes --> P[Cause 2 scoped gap]
    F -- no --> Q[Cause 3 dead chain]
```

---

## Step 1: Add a one-shot resolution-trace diagnostic

Goal: given a cid, log every decision Passes 2-8 made for it, so we can pin which of the four causes is firing for `task-toolu_01XvF39QpU8SG7TECB7EWnWg` without a guessed-fix loop.

Constraints from `[.cursor/rules/project-layout.mdc](.cursor/rules/project-layout.mdc)`:

- No new top-level Python file.
- New code lives in an existing subpackage.
- Tests under `tests/` using stdlib `unittest`.

Plan:

- Extend [cursor_view/extraction/diagnostics.py](cursor_view/extraction/diagnostics.py) with a new public `trace_project_resolution(cid: str) -> dict` that:
  - Opens both source DBs read-only (`sqlite3.connect(f"file:{db}?mode=ro", uri=True)` per [`.cursor/rules/sqlite-cursor-db.mdc`](.cursor/rules/sqlite-cursor-db.mdc), via `contextlib.closing`).
  - For the cid, reports: presence of a `composerData:<cid>` row; `subagentInfo` shape; whether the `bubbleId:<cid>:*` row count matches `fullConversationHeadersOnly`; and, when `cid.startswith("task-")`, whether `tool_call_parent[cid[5:]]` exists in the chat-index cache (`SELECT parent_composer_id FROM tool_call_parent WHERE tool_call_id = ?`) AND whether the parent's headers array contains a bubble with the matching `toolFormerData.toolCallId`.
  - Then walks `subagent_parent` recursively (using the cached `tool_call_parent` table to bridge non-dirty `task-*` hops), printing each ancestor's `composer_state.workspace_id` and `chat_summary.{project_name, project_root_path}` from the cache, so the operator sees exactly where the chain dies.
  - Returns a dict so a unit test can assert specific fields rather than scraping log text.
- Add a CLI seam: extend [`cursor_view/extraction/__main__.py`](cursor_view/extraction/__main__.py) (create only if it does not exist; otherwise add an `argparse` flag) with `python -m cursor_view.extraction.diagnostics --cid <session_id>`. No new top-level file.
- Use lazy `%`-style logging per `[.cursor/rules/python-standards.mdc](.cursor/rules/python-standards.mdc)`.
- Keep the helper name `trace_project_resolution` un-underscored because callers outside the module (the `__main__` glue, the test) need it; do NOT cross underscore-prefix boundaries (rule).

## Step 2: Run the diagnostic, branch the implementation

Run `python -m cursor_view.extraction.diagnostics --cid task-toolu_01XvF39QpU8SG7TECB7EWnWg`. The output's "where the chain died" line picks the fix:

- **Cause 1 (orphan filter dropped the parent's tool-call bubble):** in [cursor_view/extraction/passes/global_bubbles.py](cursor_view/extraction/passes/global_bubbles.py) at lines 108-117 the orphan filter must continue to drop messages and URIs but MUST still record `tool_call_parent[tcid] = cid` if the orphaned bubble carries a real `toolFormerData.toolCallId`. The headers-array invariant in `[.cursor/rules/sqlite-cursor-db.mdc](.cursor/rules/sqlite-cursor-db.mdc)` ("no message, no URIs into project inference, no `tool_call_parent` upsert") would then be **wrong** in the `tool_call_parent` clause and must be amended in the same PR per the "Rule drift" section of `[.cursor/rules/comments-style.mdc](.cursor/rules/comments-style.mdc)`. Also amend the persisted-side comment in [cursor_view/cache/diff/global_db.py](cursor_view/cache/diff/global_db.py) (`_diff_global_cursor_disk_kv`) so the `tool_call_parent_updates` staging mirrors the relaxed rule.
- **Cause 2 (scoped Pass 6 gap on a non-dirty `task-*` ancestor):** extend [cursor_view/cache/delta/cached_state.py](cursor_view/cache/delta/cached_state.py) `_compose_cached_state` to also produce an `ancestor_subagent_parent: dict[str, str]` derived from the persisted `tool_call_parent` table (one row per non-dirty `task-<tcid>` cid where `tcid` resolves in the table). Thread it through `[cursor_view/extraction/__init__.py](cursor_view/extraction/__init__.py)` and `CachedExtractionState` (new field, additive default `field(default_factory=dict)`), and consume it in [cursor_view/extraction/passes/subagent_inheritance.py](cursor_view/extraction/passes/subagent_inheritance.py) at line 71: when `subagent_parent.get(ancestor)` is `None` and `ancestor.startswith("task-")`, fall back to `ancestor_subagent_parent.get(ancestor)`. The walk's `_MAX_PARENT_DEPTH` cap and `visited` set already protect against cycles. Update `[.cursor/rules/sqlite-cursor-db.mdc](.cursor/rules/sqlite-cursor-db.mdc)`'s description of the `tool_call_parent` table's role (it now backs both Pass 5 reconstruction AND the Pass 6 walk's non-dirty-ancestor hop) per the rule-drift requirement.
- **Cause 3 (dead chain — top of the chain is a genuinely workspace-less chat):** extend Pass 4 to also harvest URIs from a configurable extra signal that the ancestor still exposes (e.g. the parent composer's `composerData.context.fileSelections` if present), but if the chain truly has no signal, accept that this single chat will stay `(global)` / `(unknown)` and the fix is documentation-only — explain in the diagnostic's output and cite [cursor_view/extraction/passes/finalize.py](cursor_view/extraction/passes/finalize.py) lines 30-37 ("steady trickle of these is expected"). No code change beyond the diagnostic itself.
- **Cause 4 (parent composer was deleted):** the right behaviour is to soft-delete the orphan `task-*` row from the cache during the next refresh. Add a check in [cursor_view/cache/delta/propagation.py](cursor_view/cache/delta/propagation.py) that, when a `task-<tcid>` cid's `tool_call_parent[tcid]` resolves to a parent that is absent from `composer_state` AND absent from the dirty set, registers the child for deletion. Mirror this with a regression test alongside the existing `test_chat_index_propagation_gating.py::test_soft_deleted_parent_propagates_to_subagent` so the soft-delete invariant the `[.cursor/rules/known-bugs.mdc](.cursor/rules/known-bugs.mdc)` history references stays sound.

For each branch, commit to ONE of these targeted changes — do not implement all four. The final code-review step (Step 6) verifies no other path silently suppresses the same edge.

## Step 3: Cache layout and refresh routing implications

Only Cause 2 touches cache-write paths. If Cause 2 is selected:

- No new cache columns are needed; we are only changing how an existing column (`tool_call_parent.parent_composer_id`) is consumed at extraction time. **Do NOT bump `INDEX_SCHEMA_VERSION`** in [cursor_view/chat_index/schema.py](cursor_view/chat_index/schema.py) — row shape is unchanged. Per `[.cursor/rules/chat-index-refresh.mdc](.cursor/rules/chat-index-refresh.mdc)` this is "freshness drift", not "shape drift", so the SWR path is the right router.
- Verify by re-reading [cursor_view/chat_index/index.py](cursor_view/chat_index/index.py) `ensure_current` after the change that no new branch was introduced that routes to the synchronous path on cache-hit.

For Causes 1 / 3 / 4 no `INDEX_SCHEMA_VERSION` bump is required either; the existing column shapes carry the new content as-is.

## Step 4: Regression test

In `tests/test_chat_index_incremental.py` (the canonical home per `[.cursor/rules/project-layout.mdc](.cursor/rules/project-layout.mdc)`) add a synthetic-Cursor-DB test that reproduces the failing scenario for the chosen cause:

- **Cause 1:** seed `composerData:parent` with a `fullConversationHeadersOnly` array that EXCLUDES the tool-call bubble; seed the orphan `bubbleId:parent:<orphan>` with a real `toolFormerData.toolCallId == "toolu_X"`; seed `composerData:task-toolu_X` with a `name`. Assert that after a full rebuild, the `task-toolu_X` chat's `chat_summary.workspace_id` equals the parent's resolved workspace.
- **Cause 2:** two-phase test: (1) initial refresh dirties parent + grandparent + leaf and resolves the leaf correctly; (2) re-refresh with only the leaf in the dirty set (parent / grandparent unchanged) — assert the leaf's `chat_summary.workspace_id` still matches the original. The current code regresses because `subagent_parent` is empty for the non-dirty parent.
- **Cause 4:** seed parent + leaf, refresh, then delete parent rows from the synthetic DB and refresh again. Assert leaf is removed from `chat_summary`.

Run `python -m unittest discover -s tests` and verify it stays green per `[.cursor/rules/project-layout.mdc](.cursor/rules/project-layout.mdc)`.

## Step 5: Rule and documentation sync

Per `[.cursor/rules/comments-style.mdc](.cursor/rules/comments-style.mdc)` "Rule drift" and `[.cursor/rules/project-layout.mdc](.cursor/rules/project-layout.mdc)` "Documentation sync":

- If Cause 1: amend the "Canonical bubble order" section of `[.cursor/rules/sqlite-cursor-db.mdc](.cursor/rules/sqlite-cursor-db.mdc)` (it currently says "no `tool_call_parent` upsert" for orphans — which would no longer be true).
- If Cause 2: amend the `tool_call_parent` description in the same rule's "Cache tables" section to mention that the table now also serves the Pass 6 walk's non-dirty-ancestor hop, and update the docstring on `CachedExtractionState` in [cursor_view/extraction/core.py](cursor_view/extraction/core.py) (the `ancestor_*` field block) to list the new field.
- If Cause 4: amend `[.cursor/rules/known-bugs.mdc](.cursor/rules/known-bugs.mdc)` to retire any related `TODO(bug):` if introduced, or extend the "retired examples" list.
- README + CONTRIBUTING: review whether the change is user-visible. Adding diagnostics CLI is — add a one-paragraph "Troubleshooting unknown projects" section to `README.md` documenting `python -m cursor_view.extraction.diagnostics --cid <id>`, and a one-line pointer in the "Project layout" section of `.github/CONTRIBUTING.md` if a new module was added under `cursor_view/extraction/`.
- Add a docstring-level comment at any new code seam following `[.cursor/rules/comments-style.mdc](.cursor/rules/comments-style.mdc)`: explain the invariant, NOT the mechanics, and NEVER explain "the change you are making" in a code comment.

## Step 6: Final code-review pass

Re-read the touched files looking for sibling bugs:

- [cursor_view/extraction/passes/subagent_inheritance.py](cursor_view/extraction/passes/subagent_inheritance.py): does the walk handle a cycle through the new cached-edge fallback? `visited` already covers it; verify by inspection.
- [cursor_view/cache/delta/propagation.py](cursor_view/cache/delta/propagation.py): does the gated apply path still fire when the new resolution path changes a child's project? The `parent's chat_summary triple shifts` gate at lines 95-170 should still trigger. Confirm by re-reading.
- [cursor_view/chat_format.py](cursor_view/chat_format.py) lines 146-196: ensure the username / `(unknown)` / `Root` / git-fallback ladder still applies cleanly to the freshly resolved project (a real `rootPath` should not get re-rewritten by the workspace-id fallback at lines 179-184, which only fires for empty / `/` / `/Users` rootPaths).
- [cursor_view/chat_index/rows.py](cursor_view/chat_index/rows.py) `_insert_chat`: confirm no stray `Unknown Project` defaults shadow the new resolved project (current behaviour at lines 157-158 only fires when `project.name` is missing entirely).
- Lazy `%`-style logging at every new log site; no f-strings inside `logger.*`.
- Read-only SQLite connections wherever the diagnostic touches `state.vscdb` or `globalStorage/state.vscdb`, with `contextlib.closing` rather than the `if "con" in locals()` antipattern that `[.cursor/rules/sqlite-cursor-db.mdc](.cursor/rules/sqlite-cursor-db.mdc)` calls out.
- Per `[.cursor/rules/known-bugs.mdc](.cursor/rules/known-bugs.mdc)`: if anything looks wrong but is out of scope, add a `TODO(bug):` marker with the symptom + suspected cause rather than silently rewriting it.

Final sanity gate before declaring done: `python -m unittest discover -s tests` is green AND the chat-detail UI for `/chat/task-toolu_01XvF39QpU8SG7TECB7EWnWg` no longer shows `(unknown)` / `(global)`.