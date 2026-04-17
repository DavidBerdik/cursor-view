---
name: refactor cursor-view structure
overview: "Reorganize the Cursor View codebase so it's easier to navigate and maintain: delete dead top-level scripts, fold the Python entry points into the `cursor_view` package (with thin compatibility shims at the repo root), split the two largest Python modules into focused submodules, break the monolithic React `ChatList.js` / `ChatDetail.js` / `App.js` files apart, deduplicate the shared export-dialog flow, normalize logging and trivial style inconsistencies, and refresh the README. Functionality stays identical; bugs are documented but not patched."
todos:
  - id: delete_dead_code
    content: Delete cursor_chat_finder.py, extract_cursor_chat.py, vscdb_to_sqlite.py, and cursor_chat_viewer/
    status: completed
  - id: py_entry_points
    content: Rename server.py -> terminal.py, move terminal.py / desktop.py / cursor_view_main.py impls into cursor_view/{terminal.py, desktop/, __main__.py}, replace originals with thin shims, and update README + cursor-view.spec to match
    status: completed
  - id: py_split_extraction
    content: Split cursor_view/extraction.py into extraction/{core.py, diagnostics.py} and break extract_chats into named per-pass helpers
    status: completed
  - id: py_split_export
    content: Split cursor_view/export_html.py into export/{themes.py, markdown.py, markdown_fences.py, html.py} and pull the inline HTML <style> block into a module-level template constant
    status: completed
  - id: py_move_modules
    content: Move project_inference.py, git_project.py into cursor_view/projects/ and sqlite_data.py into cursor_view/sources/, updating internal imports
    status: pending
  - id: py_style
    content: Standardize logging on lazy %-formatting, replace 'if con in locals()' cleanup with try/finally, add missing docstrings on ChatIndex helpers, add TODO(bug) markers for documented issues
    status: pending
  - id: fe_split_app
    content: Split frontend/src/App.js into theme/{colors,buildTheme,themeCookie}.js + contexts/{ColorContext,ThemeModeContext}.js, leaving App.js as composition only
    status: pending
  - id: fe_split_chatlist
    content: Decompose ChatList.js into chat-list/{ChatList,SearchBar,EmptyState,ProjectGroup,ChatCard}.js + hooks/useChatSummaries.js
    status: pending
  - id: fe_split_chatdetail
    content: Decompose ChatDetail.js into chat-detail/{ChatDetail,ChatMetaPanel,MessageList,MessageBubble}.js
    status: pending
  - id: fe_dedupe_export
    content: Extract ExportFormatDialog and ExportWarningDialog and centralize the format -> warning -> export pipeline in hooks/useExportFlow.js + hooks/useExportWarningPreference.js
    status: pending
  - id: fe_utils
    content: Add utils/formatDate.js, utils/dbPath.js, utils/cookies.js and replace the duplicated copies
    status: pending
  - id: fe_css
    content: Trim frontend/src/index.css of the dark-only code/pre/a overrides that are already handled by MUI / MessageMarkdown
    status: pending
  - id: docs_readme
    content: Add a 'Project layout' section to README.md describing the entry points, cursor_view subpackages, and frontend folders
    status: pending
  - id: create_standards_rules
    content: Author six focused Cursor rules under .cursor/rules/ (project-layout, python-standards, sqlite-cursor-db, known-bugs, react-components, comments-style) capturing the standards established by this refactor
    status: pending
isProject: false
---

## Goals & non-goals

- Reorganize layout, naming and module boundaries; remove confirmed dead code; standardize style; add missing comments where intent is non-obvious; refresh `README.md`.
- Keep behavior, public HTTP API, on-disk cache layout, CLI flags, and PyInstaller build identical. Any bugs found are listed in the "Bugs to document, not fix" section below and surfaced as inline `# TODO` notes only.

## Confirmed dead code to delete

These four are not referenced from any active code path (verified by grep across the repo, the spec file, and the workflow):

- [cursor_chat_finder.py](cursor_chat_finder.py)
- [extract_cursor_chat.py](extract_cursor_chat.py)
- [vscdb_to_sqlite.py](vscdb_to_sqlite.py)
- [cursor_chat_viewer/index.html](cursor_chat_viewer/index.html) (and its empty parent dir)

## Python: target layout

```
cursor_view/
  __init__.py
  __main__.py                  # was cursor_view_main.py
  terminal.py                  # was server.py (impl); renamed to match what it actually launches (terminal/server mode)
  desktop/
    __init__.py                # was desktop.py: run_desktop()
    api.py                     # DesktopApi (JS bridge)
    window_state.py            # _load/_save_window_state, _centered_position, _free_port
  app_factory.py               # unchanged
  cleanup.py                   # unchanged
  routes.py                    # unchanged
  paths.py                     # unchanged
  timestamps.py                # unchanged
  chat_index.py                # minor: lazy-% logging, drop dead branches
  chat_format.py               # minor: lazy-% logging, mark legacy paths
  extraction/
    __init__.py                # re-exports extract_chats
    core.py                    # the orchestration loop
    diagnostics.py             # the CURSOR_CHAT_DIAGNOSTICS env block
  sources/
    __init__.py
    sqlite_data.py             # moved as-is
  projects/
    __init__.py
    inference.py               # was project_inference.py
    git.py                     # was git_project.py
  export/
    __init__.py                # re-exports generate_markdown, generate_standalone_html, resolve_export_theme
    themes.py                  # EXPORT_HTML_THEMES + resolve_export_theme
    markdown.py                # generate_markdown
    markdown_fences.py         # normalize_markdown_for_html_export, infer_language_from_filename
    html.py                    # generate_standalone_html
```

Top-level shims (kept so `python3 desktop.py`, `python3 cursor_view_main.py`, and `pyinstaller cursor-view.spec` keep working). The old [server.py](server.py) is renamed to `terminal.py` per the user's request, and the README's `python3 server.py` instruction will be updated to `python3 terminal.py` to match the file's actual purpose:

```python
# terminal.py (new name; replaces server.py)
from cursor_view.terminal import main

if __name__ == "__main__":
    main()
```

Same shim shape for `desktop.py` and `cursor_view_main.py`. The PyInstaller `Analysis(['cursor_view_main.py'], ...)` therefore continues to work unchanged.

## Python: file-by-file changes

### 1. Move + split entry points
- New `cursor_view/terminal.py`: contents of [server.py](server.py), unchanged except for an updated module docstring (the existing one still says "API server"; reword to "Terminal/server mode entry point: starts the Flask app on a fixed port and opens the user's browser.").
- New `cursor_view/desktop/__init__.py`: keeps `run_desktop()` and the public `main()` alias.
- New `cursor_view/desktop/api.py`: lifts `DesktopApi` and the `_EXTENSIONS` table out of [desktop.py](desktop.py).
- New `cursor_view/desktop/window_state.py`: lifts `_DEFAULT_*` / `_MIN_*` constants, `_free_port`, `_webview_storage_path`, `_primary_screen`, `_centered_position`, `_window_state_path`, `_load_window_state`, `_save_window_state` out of [desktop.py](desktop.py).
- New `cursor_view/__main__.py`: contents of [cursor_view_main.py](cursor_view_main.py), with the local `from desktop import run_desktop` / `from server import run_server` rewritten to `from cursor_view.desktop import run_desktop` / `from cursor_view.terminal import run_server`. (The function name `run_server` stays as-is inside the module so there's no change to its public Python API surface.)
- Top-level files: [server.py](server.py) is **deleted** and a new `terminal.py` shim takes its place; [desktop.py](desktop.py) and [cursor_view_main.py](cursor_view_main.py) are replaced with one-line shims that import and call the package's `main`.
- Update [cursor-view.spec](cursor-view.spec): the `Analysis(['cursor_view_main.py'], ...)` line stays the same (the shim still exists), but it's worth bumping the spec's existing comment about CLI behavior to reference `terminal.py` rather than `server.py` if the comment ever needs editing — no functional change required.
- Update [README.md](README.md): replace every `python3 server.py` occurrence with `python3 terminal.py` (lines 27-30 and the "Run from source" section). The shim makes the rename source-compatible at the package level too (`from cursor_view.terminal import run_server`).

### 2. Split [cursor_view/extraction.py](cursor_view/extraction.py) (377 lines, mixed concerns)
- `cursor_view/extraction/diagnostics.py`: lift the entire `if os.environ.get("CURSOR_CHAT_DIAGNOSTICS")` block (lines ~57-111 of [cursor_view/extraction.py](cursor_view/extraction.py)) into a single `dump_workspace_diagnostics(root)` function.
- `cursor_view/extraction/core.py`: the rest of `extract_chats`, slimmed by replacing the diagnostics block with one call. While there, factor the four already-distinct passes into private helpers (`_collect_workspace_messages`, `_collect_global_bubbles`, `_collect_global_composers`, `_apply_uri_fallbacks`, `_apply_subagent_inheritance`, `_finalize_sessions`) so the top-level `extract_chats` reads as a sequence of named steps. No semantics change; structure only.
- `cursor_view/extraction/__init__.py` re-exports `extract_chats` so `from cursor_view.extraction import extract_chats` continues to work.

### 3. Split [cursor_view/export_html.py](cursor_view/export_html.py) (547 lines)
- `cursor_view/export/themes.py`: `EXPORT_HTML_THEMES` dict + `resolve_export_theme`.
- `cursor_view/export/markdown_fences.py`: `infer_language_from_filename`, `normalize_markdown_for_html_export` (and the `cursor_metadata_pattern` constant promoted to module level).
- `cursor_view/export/markdown.py`: `generate_markdown`.
- `cursor_view/export/html.py`: `generate_standalone_html`. Pull the giant inline `<style>` block out of the f-string into a module-level `_HTML_STYLE_TEMPLATE` constant so the function body becomes readable; keep the rendered output byte-for-byte identical.
- `cursor_view/export/__init__.py`: re-exports `generate_markdown`, `generate_standalone_html`, `resolve_export_theme` so [cursor_view/routes.py](cursor_view/routes.py) doesn't need to change its import target name.

### 4. Move (rename only, no behavior change)
- [cursor_view/project_inference.py](cursor_view/project_inference.py) -> `cursor_view/projects/inference.py`
- [cursor_view/git_project.py](cursor_view/git_project.py) -> `cursor_view/projects/git.py`
- [cursor_view/sqlite_data.py](cursor_view/sqlite_data.py) -> `cursor_view/sources/sqlite_data.py`
- Update the small set of internal imports accordingly. External callers (none outside the package) are unaffected.

### 5. Style normalization (low-risk, mechanical)
- Standardize logging on lazy `%`-formatting (current style mixes f-strings and `%s` even within the same module, e.g. [cursor_view/chat_format.py](cursor_view/chat_format.py) lines 111, 159 vs [cursor_view/routes.py](cursor_view/routes.py) lines 50-55).
- Replace fragile `if "con" in locals(): con.close()` cleanup in [cursor_view/sources/sqlite_data.py](cursor_view/sources/sqlite_data.py) (`iter_chat_from_item_table`) and [cursor_view/projects/inference.py](cursor_view/projects/inference.py) (`workspace_info`) with `con = None` + `try/finally` so connections are always released without inspecting the local namespace.
- Add docstring on `ChatIndex` private helpers that currently have none (`_count_summaries`, `_fetch_summaries`, `_summary_row_to_api`, etc. in [cursor_view/chat_index.py](cursor_view/chat_index.py)) explaining the FTS-vs-LIKE branching.

### 6. Repo hygiene
- Delete the four dead files listed above.
- Add `dist/`, `build/`, `__pycache__/` are already in [.gitignore](.gitignore); verify the loose `__pycache__/` directory at the repo root and the stale `build/` and `dist/` directories aren't tracked. (No commits required; just confirm.)
- `.vscode/launch.json` / `.vscode/settings.json` left as-is.

## Frontend: target layout

The two big files own most of the mess:

- [frontend/src/components/ChatList.js](frontend/src/components/ChatList.js): 670 lines, contains the page, search bar, project group rendering, chat card, two duplicate dialogs, and ad-hoc cookie code.
- [frontend/src/components/ChatDetail.js](frontend/src/components/ChatDetail.js): 480 lines, with the same two dialogs and the same cookie code duplicated verbatim.
- [frontend/src/App.js](frontend/src/App.js): mixes color tables, MUI theme builder, two contexts, cookie helpers, and the actual `App` component.

Target tree:

```
frontend/src/
  App.js                       # slim: just <App/> + provider wiring
  index.js                     # unchanged
  index.css                    # drop the dark-only `code`/`pre` overrides
  starry-night-theme.css       # unchanged
  theme/
    colors.js                  # sharedColors, darkColors, lightColors
    buildTheme.js              # buildTheme(c, mode)
    themeCookie.js             # readThemeCookie / writeThemeCookie
  contexts/
    ColorContext.js
    ThemeModeContext.js
  hooks/
    useChatSummaries.js        # lifts the loading/refresh effect from ChatList
    useExportFlow.js           # owns the format-dialog -> warning-dialog -> export pipeline
    useExportWarningPreference.js  # cookie read/write for dontShowExportWarning
  utils/
    exportChat.js              # unchanged
    formatDate.js              # the duplicated formatDate
    dbPath.js                  # the duplicated getDbPathLabel
    cookies.js                 # tiny getCookie/setCookie helpers
  markdown/                    # unchanged
  components/
    Header.js                  # unchanged
    AppContextMenu.js          # unchanged
    MessageMarkdown.js         # unchanged
    chat-list/
      ChatList.js              # page composition only
      SearchBar.js
      EmptyState.js
      ProjectGroup.js
      ChatCard.js
    chat-detail/
      ChatDetail.js            # page composition only
      ChatMetaPanel.js         # the FolderIcon + chips + path/db row
      MessageList.js
      MessageBubble.js
    export/
      ExportFormatDialog.js
      ExportWarningDialog.js
      ExportDialogs.js         # combo wrapper that hosts the useExportFlow state machine
```

## Frontend: file-by-file changes

### 1. Split [frontend/src/App.js](frontend/src/App.js)
- `theme/colors.js`: extract `sharedColors`, `darkColors`, `lightColors`.
- `theme/buildTheme.js`: extract `buildTheme(c, mode)`.
- `theme/themeCookie.js`: extract `readThemeCookie`, `writeThemeCookie`.
- `contexts/ColorContext.js`, `contexts/ThemeModeContext.js`: one context per file (currently both live at the bottom of [frontend/src/App.js](frontend/src/App.js) and are imported by `Header`, `ChatList`, `ChatDetail`, `MessageMarkdown`).
- New `App.js` becomes ~40 lines: state, providers, `<Router>`, routes.
- Update existing `import { ColorContext, ThemeModeContext } from '../App'` sites in [frontend/src/components/Header.js](frontend/src/components/Header.js), [frontend/src/components/ChatList.js](frontend/src/components/ChatList.js), [frontend/src/components/ChatDetail.js](frontend/src/components/ChatDetail.js), [frontend/src/components/MessageMarkdown.js](frontend/src/components/MessageMarkdown.js).

### 2. Decompose [frontend/src/components/ChatList.js](frontend/src/components/ChatList.js)
- `chat-list/SearchBar.js`: receives `value` + `onChange` + `onClear`.
- `chat-list/EmptyState.js`: the Paper with the InfoIcon and either the "no results" or "no chats" copy.
- `chat-list/ProjectGroup.js`: the Paper header + Collapse + grid of `ChatCard`s for one project.
- `chat-list/ChatCard.js`: the per-chat `Card` (date, message count, db path, preview, export button).
- `hooks/useChatSummaries.js`: owns `chatData`, `loading`, `error`, the cancellable `useEffect`, and `refresh()`.
- `chat-list/ChatList.js`: down to ~80 lines of composition.

### 3. Decompose [frontend/src/components/ChatDetail.js](frontend/src/components/ChatDetail.js)
- `chat-detail/ChatMetaPanel.js`: project name chip + path / workspace / db row.
- `chat-detail/MessageBubble.js`: avatar + role label + Paper with markdown.
- `chat-detail/MessageList.js`: maps messages to `MessageBubble`s.
- `chat-detail/ChatDetail.js`: page composition + the markdown pre-rendering effect (kept here because it's specific to this page).

### 4. Deduplicate the export flow
- `export/ExportFormatDialog.js`: HTML/JSON/Markdown radio dialog (currently lines 307-341 of [frontend/src/components/ChatList.js](frontend/src/components/ChatList.js) and lines 219-253 of [frontend/src/components/ChatDetail.js](frontend/src/components/ChatDetail.js), nearly identical).
- `export/ExportWarningDialog.js`: the "check for sensitive data" dialog (currently lines 343-375 of `ChatList.js` and lines 255-287 of `ChatDetail.js`).
- `hooks/useExportFlow.js`: returns `{ requestExport(sessionId), formatDialogProps, warningDialogProps }`. Encapsulates the format -> warning -> `exportChat()` state machine that is currently copy-pasted across the two pages, including the alert-on-error / alert-with-saved-path behavior.
- `hooks/useExportWarningPreference.js`: reads / writes the `dontShowExportWarning` cookie.

### 5. Small utilities
- `utils/formatDate.js`, `utils/dbPath.js`: the two helper functions currently duplicated at the top of both pages.
- `utils/cookies.js`: tiny `getCookie(name)` / `setCookie(name, value, opts)` so the four ad-hoc `document.cookie.split('; ').find(...)` blocks across the codebase share an implementation.

### 6. CSS cleanup
- [frontend/src/index.css](frontend/src/index.css): the `code`, `pre`, and `a` rules hardcode dark-mode colors (`#2D2D2D`, `#6E2CF4`) and only happen to look OK because MUI repaints most surfaces. The file's own comment ("Background is now managed by Material UI theme") confirms this block is leftover. Plan: keep only the `body` font, the scrollbar variables, and the `::-webkit-scrollbar*` rules (which are theme-aware via the CSS vars). Delete the global `code`/`pre`/`a` rules — they are already overridden by `MessageMarkdown.js` for chat content and unused elsewhere.

## Documentation

- [README.md](README.md): add a short "Project layout" section after "Setup & Running" that lists the entry points, the `cursor_view/` package, and the frontend layout, so a new contributor doesn't have to grep. Also rewrite the existing `python3 server.py` invocations to `python3 terminal.py` to match the renamed entry point.
- No new files outside README/code are needed.

## Cursor rules under `.cursor/rules/`

Instead of one monolithic rule, create six focused rule files that each cover a single concern. This matches the create-rule skill's guidance ("one concern per rule", "under ~50 lines where possible") and means the model only pays the context cost of the rules that apply to the file(s) it's editing. Each rule cites a concrete example from this refactor so the "why" is preserved alongside the "what".

### Rule 1: `.cursor/rules/project-layout.mdc` (always apply)

Frontmatter:

```yaml
---
description: Cursor View repository layout and dead-code hygiene
alwaysApply: true
---
```

Body (~25 lines) covering:

- New Python code lives inside the `cursor_view/` package. The repo root only holds **thin shims** ([terminal.py](terminal.py), [desktop.py](desktop.py), [cursor_view_main.py](cursor_view_main.py)) that import and call `main()` from their package counterpart. The old `server.py` was a full implementation at the root; that's exactly what this rule exists to prevent.
- Organize by concern using subpackages, not by file type. Canonical subpackages (extend, don't replace): `cursor_view/extraction/`, `cursor_view/export/`, `cursor_view/projects/`, `cursor_view/sources/`, `cursor_view/desktop/`.
- Do not create a new top-level Python file unless it is a shim for an existing package entry point. Ad-hoc utilities (e.g. the deleted `vscdb_to_sqlite.py`) belong inside a subpackage with a real caller, or nowhere.
- Frontend source lives under `frontend/src/` with this fixed structure: `theme/`, `contexts/`, `hooks/`, `utils/`, `markdown/`, `components/<feature>/`.
- Files with no caller anywhere in the active codebase (Python imports, spec files, workflow files, frontend imports) must be removed in the same change that orphans them. Git history is the archive.
- Compiled or generated artifacts (`__pycache__/`, `dist/`, `build/`, `frontend/node_modules/`, `frontend/build/`) must stay gitignored. Do not commit them to "fix" a build.
- Static HTML prototypes / UI mockups do not belong in the repo (motivating example: the deleted `cursor_chat_viewer/index.html`).
- Any change that alters the repository layout must update the "Project layout" section of [README.md](README.md) in the same change.

### Rule 2: `.cursor/rules/python-standards.mdc` (Python-only)

Frontmatter:

```yaml
---
description: Python module size, docstrings, typing, and logging conventions
globs: **/*.py
alwaysApply: false
---
```

Body (~30 lines) covering:

- Soft limit: any single Python module over ~400 lines must be split into a subpackage. Motivating examples: the original 377-line [cursor_view/extraction.py](cursor_view/extraction/core.py) and 547-line `export_html.py`, both of which became subpackages with a slim `__init__.py` re-export.
- Soft limit: no function longer than ~100 lines. Break long functions into private `_named_helper` functions, keeping the top-level function as a short recipe (see `extract_chats` post-refactor in [cursor_view/extraction/core.py](cursor_view/extraction/core.py)).
- Every module starts with a one-line docstring describing its role. Every public function has a docstring that explains **why**, not what each statement does.
- Prefer typed signatures (`dict[str, Any]`, `list[str]`, `pathlib.Path`) over bare `dict`/`list`. `Any` is acceptable for heterogeneous JSON pass-through.
- Use lazy `%`-style logging, not f-strings, inside `logger.debug/info/warning/error`:

  ```python
  # Wrong
  logger.info(f"Loaded {count} chats")
  # Right
  logger.info("Loaded %s chats", count)
  ```

  Rationale: f-strings are evaluated even when the log level is disabled.

### Rule 3: `.cursor/rules/sqlite-cursor-db.mdc` (Python-only, DB conventions)

Frontmatter:

```yaml
---
description: SQLite resource handling and Cursor-DB access conventions
globs: **/*.py
alwaysApply: false
---
```

Body (~15 lines) covering:

- Acquire SQLite connections inside `try/finally` or a `with contextlib.closing(...)` block. Never write `if "con" in locals(): con.close()`. If you need conditional cleanup, initialize `con = None` first and check that. Motivating example: the pre-refactor `iter_chat_from_item_table` and `workspace_info` used the locals() check and were both candidates to leak connections under error paths.
- When opening an existing Cursor DB for reads, always use `sqlite3.connect(f"file:{db}?mode=ro", uri=True)`. The read-only URI is required — these databases are actively used by the Cursor IDE.
- Include a concrete Wrong/Right snippet of the `try/finally` vs `if "con" in locals()` pattern.

### Rule 4: `.cursor/rules/known-bugs.mdc` (always apply)

Frontmatter:

```yaml
---
description: Handling suspected bugs during refactors without fixing them
alwaysApply: true
---
```

Body (~10 lines) covering:

- Never silently delete code paths that appear dead. If a path looks wrong, add a `# TODO(bug):` comment describing the symptom and suspected cause, and leave the behavior unchanged unless explicitly asked to fix the bug. Motivating example: [cursor_view/chat_format.py](cursor_view/chat_format.py) hard-codes a developer's username in a project-name fallback; it is annotated but not removed.
- User-specific hardcoded paths, usernames, or project lists are **always** a bug. If you must add one temporarily, flag it with `# TODO(bug):`.
- The `TODO(bug):` prefix is reserved for known-broken behavior we have chosen not to fix yet. Do not use it for generic "clean this up later" notes; use plain `TODO:` for those.

### Rule 5: `.cursor/rules/react-components.mdc` (frontend-only)

Frontmatter:

```yaml
---
description: React component decomposition, shared logic, and theme ownership
globs: frontend/src/**/*.{js,jsx}
alwaysApply: false
---
```

Body (~35 lines) covering:

- One React component per file. Components that exceed ~250 lines must be decomposed into feature-folder siblings. Motivating example: `ChatList.js` was 670 lines and now lives in `components/chat-list/` split into `ChatList`, `SearchBar`, `EmptyState`, `ProjectGroup`, `ChatCard`.
- Duplicated UI across pages (dialogs, toolbars, cards) is extracted into `components/<shared-area>/`. The export format + warning dialogs lived twice in the codebase before this refactor and must never again.
- Duplicated logic across pages (fetch + cancel effects, cookie read/write, event state machines) lives in `src/hooks/` (e.g. `useChatSummaries`, `useExportFlow`, `useExportWarningPreference`).
- Pure helpers (`formatDate`, `getDbPathLabel`, cookie parsing) live in `src/utils/`. A helper may not be copied into two components — promote it on sight:

  ```jsx
  // Wrong: duplicated at the top of ChatList.js and ChatDetail.js
  function formatDate(date) { /* ... */ }

  // Right
  import { formatDate } from '../../utils/formatDate';
  ```

- MUI theme tokens (`palette`, `sx`) own the visual language. CSS files in `src/` must not hard-code colors that the theme already controls. Keep global CSS limited to font stacks, CSS-variable-driven scrollbars, and purely structural concerns. Motivating example: [frontend/src/index.css](frontend/src/index.css) previously hard-coded `#2D2D2D` for `pre` and `code` even in light mode.
- Contexts (`ColorContext`, `ThemeModeContext`) are defined in `src/contexts/`, one per file. Do not re-export contexts from `App.js`; import them from their defining file.
- Use a cancellation flag (`let cancelled = false; ... return () => { cancelled = true; };`) for every `useEffect` that awaits a network request, and respect it after every `await` boundary.
- Reuse the `useExportFlow` hook for any new "export to file" UI rather than copying the format-dialog -> warning-dialog -> `exportChat()` state machine again.

### Rule 6: `.cursor/rules/comments-style.mdc` (always apply)

Frontmatter:

```yaml
---
description: Comment intent rules for all languages in the repo
alwaysApply: true
---
```

Body (~15 lines) covering:

- Comments explain intent, trade-offs, invariants, or non-obvious platform behavior. Do not write comments that re-narrate what the code literally says:

  ```python
  # Wrong
  # Increment the counter
  counter += 1

  # Right
  # Bubbles without text still carry URIs we need for project inference,
  # so we count them separately from message-carrying bubbles.
  counter += 1
  ```

- When a refactor materially changes a convention captured in any rule under `.cursor/rules/`, update that rule in the same PR. Rules must not drift from reality.

### Summary table

- `project-layout.mdc` — always apply — repo structure + dead-code hygiene + README sync.
- `python-standards.mdc` — `**/*.py` — module/function size, docstrings, typing, logging.
- `sqlite-cursor-db.mdc` — `**/*.py` — SQLite cleanup + Cursor-DB read-only convention.
- `known-bugs.mdc` — always apply — `TODO(bug):` convention, no silent dead-code deletion.
- `react-components.mdc` — `frontend/src/**/*.{js,jsx}` — component decomposition, shared logic, theme ownership, effects.
- `comments-style.mdc` — always apply — intent-only comments, rule drift.

### Authoring notes for the step

- Write the rules in the order listed; each rule is independent, so there's no cross-file dependency.
- Use concrete file links (`[cursor_view/extraction/core.py](cursor_view/extraction/core.py)` etc.) so a future agent can inspect the canonical example alongside the rule.
- Keep each rule under ~50 lines of body content where possible. The React-components rule is expected to be the largest; the SQLite and known-bugs rules will be the smallest.
- Do not use emojis anywhere (matches the repo-wide convention).
- After writing all six rules, cross-check that every standard traces back to something this refactor actually changed in todos 1-12. Any standard that cannot be anchored to a concrete change must be cut rather than left speculative.

## Bugs to document (NOT fix as part of this refactor)

These will be added as inline `# TODO(bug):` comments where they live, and listed in a short "Known issues" section at the bottom of the refactor PR description for follow-up:

1. [cursor_view/chat_format.py](cursor_view/chat_format.py) lines 113-120: hard-coded `/Users/saharmor/Documents/codebase/...` special case + `project["name"] = "cursor-view"` fallback. Personalized to one developer; effectively dead for everyone else.
2. [cursor_view/projects/inference.py](cursor_view/project_inference.py) line 58: hard-coded `known_projects` list (`genaisf`, `cursor-view`, `cursor-apps`, `universal-github`, `inquiry`, ...). Same provenance.
3. [frontend/src/components/ChatList.js](frontend/src/components/ChatList.js) `handleExportWarningClose` and the matching block in [frontend/src/components/ChatDetail.js](frontend/src/components/ChatDetail.js): the `dontShowExportWarning` cookie is written even when the user closes the dialog with **Cancel**, which is almost certainly not the intent.
4. [cursor_view/sources/sqlite_data.py](cursor_view/sqlite_data.py) `iter_bubbles_from_disk_kv` / `iter_composer_data`: when `sqlite3.DatabaseError` fires after `sqlite3.connect` but before `con.close()`, the connection leaks. (The `try/finally` cleanup in the refactor section addresses the symptom, but the original control flow is independently buggy.)
5. [cursor_view/extraction/diagnostics.py](cursor_view/extraction.py) (after extraction): the diagnostic SQLite connection is never closed if `cur.execute` throws, and the broad `except Exception` swallows real errors at debug level.

## Risk & verification

- All Python imports are renamed in the same change as their target files, so a single `python -c "import cursor_view; from cursor_view import terminal, desktop; from cursor_view.desktop import run_desktop; from cursor_view.terminal import run_server"` smoke-test catches breakage.
- The PyInstaller build is unchanged because [cursor-view.spec](cursor-view.spec) still points at `cursor_view_main.py` (now a shim).
- The frontend split touches only intra-`src/` imports; the build output, public asset list, and HTTP API are untouched. `cd frontend && npm run build` should succeed without warnings beyond the existing baseline.
- No DB schema, on-disk cache format, cookie name, or HTTP route changes — the backend cache (`chat-index.sqlite3`) and the `themeMode` / `dontShowExportWarning` cookies remain valid.