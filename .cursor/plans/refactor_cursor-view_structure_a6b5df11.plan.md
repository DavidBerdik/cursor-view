---
name: refactor cursor-view structure
overview: "Reorganize the Cursor View codebase so it's easier to navigate and maintain: delete dead top-level scripts, fold the Python entry points into the `cursor_view` package (with thin compatibility shims at the repo root), split the two largest Python modules into focused submodules, break the monolithic React `ChatList.js` / `ChatDetail.js` / `App.js` files apart, deduplicate the shared export-dialog flow, normalize logging and trivial style inconsistencies, and refresh the README. Functionality stays identical; bugs are documented but not patched."
todos:
  - id: delete_dead_code
    content: Delete cursor_chat_finder.py, extract_cursor_chat.py, vscdb_to_sqlite.py, and cursor_chat_viewer/
    status: completed
  - id: py_entry_points
    content: Rename server.py -> terminal.py, move terminal.py / desktop.py / cursor_view_main.py impls into cursor_view/{terminal.py, desktop/, __main__.py}, replace originals with thin shims, and update README + cursor-view.spec to match
    status: pending
  - id: py_split_extraction
    content: Split cursor_view/extraction.py into extraction/{core.py, diagnostics.py} and break extract_chats into named per-pass helpers
    status: pending
  - id: py_split_export
    content: Split cursor_view/export_html.py into export/{themes.py, markdown.py, markdown_fences.py, html.py} and pull the inline HTML <style> block into a module-level template constant
    status: pending
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