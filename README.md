<div align="center">

# Cursor View

Cursor View is a local tool to view, search, and export all your Cursor AI chat histories in one place. It works by scanning your local Cursor application data directories and extracting chat data from the SQLite databases.

**Privacy Note**: All data processing happens locally on your machine. No data is sent to any external servers.

<img width="500" alt="cursor-view Dark Mode" src=".github/readme-imgs/screenshot-dark-mode.png" /> <img width="500" alt="cursor-view Light Mode" src=".github/readme-imgs/screenshot-light-mode.png" />

</div>


## Setup & Running

1. Clone this repository
2. Install Python dependencies:
   ```
   python3 -m pip install -r requirements.txt
   ```
3. Install frontend dependencies and build (optional, pre-built files included):
   ```
   cd frontend
   npm install
   npm run build
   ```
4. Start the server:
   ```
   python3 terminal.py
   ```
5. Open your browser to http://localhost:5000

## Project layout

A contributor's map of where things live. The three scripts at the repo
root are thin shims; the bulk of the code lives inside the
`cursor_view/` Python package and the `frontend/src/` React app.

### Entry points

- `terminal.py` &mdash; starts the Flask server and opens the chat UI
  in your browser (the default mode).
- `desktop.py` &mdash; launches the same Flask server inside a native
  pywebview window.
- `cursor_view_main.py` &mdash; unified entry point used by PyInstaller;
  dispatches to terminal or desktop mode based on `--desktop`.
  Equivalent to `python3 -m cursor_view`.

### Backend (`cursor_view/`)

Top-level modules:

- `app_factory.py`, `routes.py` &mdash; Flask app construction and the
  HTTP API.
- `chat_format.py` &mdash; shapes extracted chat data for the frontend.
- `terminal.py`, `__main__.py` &mdash; terminal-mode entry point and
  the `python -m cursor_view` dispatcher.
- `cleanup.py`, `paths.py`, `timestamps.py` &mdash; small cross-cutting
  utilities.

Subpackages:

- `chat_index/` &mdash; persistent SQLite cache of chat summaries plus
  FTS search, split by concern. `index.py` hosts the `ChatIndex`
  orchestrator (refresh routing, connection lifecycle, the
  stale-while-revalidate background worker). `schema.py` owns
  `INDEX_SCHEMA_VERSION` and the DDL. `fingerprint.py` produces the
  coarse `(mtime, size, wal_mtime, wal_size)` fingerprint that
  short-circuits idle reads. `rebuild.py` is the full-rebuild path
  (build-to-temp, atomic swap). `rows.py` holds the row-shaping
  helpers (`_insert_chat`, `_count_summaries`, `_fetch_summaries`,
  FTS / LIKE search, preview / search-blob derivation) shared by the
  rebuild and incremental paths. On a fingerprint miss, the cache
  runs a row-hash diff against the Cursor source DBs (see `cache/`
  below) and applies the resulting per-composer delta in a single
  transaction, falling back to a full rebuild only on
  `force_refresh`, schema drift, `DatabaseError`, or a missing cache
  file.
- `extraction/` &mdash; pipeline that scans Cursor's SQLite databases
  and produces chat sessions. `core.py` holds the `extract_chats`
  orchestrator, the `CachedExtractionState` helper dataclass, and
  `_merge_global_composer_into_meta`. The eight ordered passes live
  under `passes/` (`workspace_messages.py`, `global_bubbles.py`,
  `global_composers.py`, `uri_fallbacks.py`, `task_subagents.py`,
  `subagent_inheritance.py`, `item_table_chats.py`, `finalize.py`)
  so each pass reads as a unit. `diagnostics.py` holds the optional
  probe gated by the `CURSOR_CHAT_DIAGNOSTICS` environment variable.
  `extract_chats` also accepts an optional `cids` set so the cache's
  incremental refresh can re-extract only the composers whose source
  rows actually changed.
- `cache/` &mdash; incremental-refresh helpers invoked by
  `chat_index/`. Split into two subpackages:
  - `cache/diff/` &mdash; the read-only diff pass. `engine.py`
    orchestrates; `types.py` owns `DirtySet` / `SourceKey` /
    `SourceRowRecord`; `hashing.py` is the row-hash + JSON-peek
    helpers; `cache_state.py` snapshots the cache's own tables;
    `global_db.py` and `workspace_db.py` split the per-source-DB
    scans (`cursorDiskKV` / legacy chatdata vs. workspace
    `ItemTable` + `workspace.json`); `propagation.py` runs the
    post-hash classification (deletions, subagent-parent-chain
    propagation, observability trimming).
  - `cache/delta/` &mdash; the single-transaction write pass.
    `engine.py` holds the `apply_delta` orchestrator;
    `cached_state.py` seeds scoped extraction with ancestor +
    `tool_call_parent` state; `composer_rows.py` does per-composer
    delete / re-extract / upsert; `project_only.py` is the
    workspace-scoped project refresh for `workspace_project_dirty`
    entries; `metadata.py` reconciles `tool_call_parent`,
    `source_row`, and the `meta` book-keeping rows; `backfill.py`
    runs the one-shot full-rebuild backfill that populates the delta
    tables below.
- `export/` &mdash; chat export generators: `themes.py` (palette),
  `markdown.py` (`.md`), `markdown_fences.py` (Cursor fence
  normalization), `html.py` (standalone HTML + inline CSS template).
- `projects/` &mdash; project-name resolution, split by heuristic.
  `inference.py` is the slim `workspace_info` orchestrator.
  `name.py` derives a display name from a resolved root path.
  `uris.py` decodes file / vscode-remote URIs and normalizes paths.
  `workspace_json.py` reads the `workspaceStorage/<id>/workspace.json`
  sidecar. `workspace_sources.py` pulls project roots from the
  `treeViewState` and `history.entries` keys. `workspace_identifier.py`
  resolves a composer's `workspaceIdentifier` block.
  `composer_uris.py` mines composerData for file/folder URIs.
  `pane_view.py` is the single home for `aichat.view.<cid>` key
  parsing (shared with the cache's row-hash pass). `git.py` is the
  SCM (git repo) fallback. Public helpers are re-exported from the
  package `__init__.py` so cross-package callers don't reach for
  underscore-prefixed names.
- `sources/` &mdash; raw access to Cursor's on-disk data, split by
  source table. `sqlite_util.py` holds the `j()` JSON loader and the
  `_connect_cursor_disk_kv` open-and-probe helper. `bubbles.py` owns
  `iter_bubbles_from_disk_kv` and the cid-scoped
  `iter_bubbles_for_cids` (range-scans a single composer's rows
  without touching the rest of the corpus). `composer_data.py` owns
  `iter_composer_data`, `iter_composer_data_for_cids`, and
  `build_bubble_order_map` (reads each composer's
  `fullConversationHeadersOnly` so extraction can sort bubbles into
  Cursor's canonical turn order instead of the alphabetical
  bubbleId order SQLite returns). `item_table.py` owns
  `iter_chat_from_item_table` and `iter_global_legacy_chatdata`.
- `desktop/` &mdash; pywebview launcher. `__init__.py` hosts
  `run_desktop`; `api.py` is the JS &harr; Python bridge;
  `window_state.py` persists window geometry across launches.

The cache SQLite layout has two kinds of tables, owned by
`cursor_view/chat_index/schema.py`:

- **Content tables** serve the HTTP API: `chat_summary`,
  `chat_message`, `chat_search_text`, `chat_search_fts`. Both the
  full rebuild and the per-cid delete-then-insert in
  `cache/delta/engine.py` go through
  `cursor_view.chat_index.rows._insert_chat`, so the row shape is
  identical between the rebuild and delta paths.
- **Delta tables** exist only to support the row-hash diff and are
  never read by the API:
  - `composer_state` &mdash; per-composer watermark
    (`workspace_id`, `db_path`, `last_updated_ms`, `composer_hash`,
    `bubble_count`). Used for ancestor lookups when a scoped
    re-extraction walks the subagent parent chain into a composer
    that wasn't in the dirty set, and to seed the diff's
    per-workspace cid buckets.
  - `source_row` &mdash; row-level content hashes keyed by
    `(db_path, table_name, key)`. A composer flips into the dirty
    set only when one of its rows' hashes actually changes, so
    mtime-only churn (e.g. Cursor bumping `lastUpdatedAt` on a
    navigation-only write) never triggers a rebuild.
  - `tool_call_parent` &mdash; persisted
    `toolCallId -> parent_composer_id` map. Lets the refresh
    resolve `task-<toolCallId>` subagent parents without scanning
    every bubble in the global DB, and drives the
    dirtiness-propagation walk that flags subagent descendants of a
    modified parent.

### Tests (`tests/`)

Stdlib `unittest` tests that exercise the incremental refresh path
against synthetic Cursor source DBs. Run with:

```
python -m unittest discover -s tests
```

`tests/test_chat_index_incremental.py` covers the four behaviors the
delta path is specifically designed for: single-bubble mutation,
workspace `treeViewState` churn, first-time `task_v2` subagent spawn,
and pane-view key promotion from `(global)` to a workspace.

### Frontend (`frontend/src/`)

- `App.js`, `index.js`, `index.css`, `starry-night-theme.css` &mdash;
  root composition and global CSS.
- `theme/` &mdash; `colors.js` (palettes), `buildTheme.js` (MUI theme
  factory), `themeCookie.js` (dark/light cookie).
- `contexts/` &mdash; `ColorContext.js` and `ThemeModeContext.js`, one
  React context per file.
- `hooks/` &mdash; shared custom hooks: `useChatSummaries`,
  `useExportFlow`, `useExportWarningPreference`, `useSavedSelection`
  (captures + restores the user's text selection across the
  context-menu open cycle).
- `utils/` &mdash; pure helpers: `formatDate`, `dbPath`, `cookies`,
  `exportChat`, `dom` (`isEditableElement` / `findSelectionContainer`,
  consumed by `AppContextMenu`).
- `markdown/` &mdash; the unified/remark/rehype pipeline that
  pre-renders chat messages to HTML.
- `components/`
  - `Header.js`, `AppContextMenu.js`, `MessageMarkdown.js` &mdash;
    global UI.
  - `chat-list/` &mdash; the list page split into `ChatList`,
    `SearchBar`, `EmptyState`, `ProjectGroup`, `ChatCard`.
  - `chat-detail/` &mdash; the detail page split into `ChatDetail`,
    `ChatMetaPanel`, `MessageList`, `MessageBubble`.
  - `export/` &mdash; shared `ExportFormatDialog` and
    `ExportWarningDialog` used by both pages.

### Assets and configuration

- `cursor-view.spec` &mdash; PyInstaller spec that bundles
  `cursor_view_main.py` and `frontend/build/` into the standalone
  binary.
- `assets/icons/` &mdash; multi-platform app icons plus the
  `_generate_icons.py` regeneration script.
- `.github/workflows/desktop-build.yml` &mdash; CI that builds the
  standalone binary on Windows, macOS, and Linux.
- `requirements.txt`, `frontend/package.json` &mdash; Python and JS
  dependencies, respectively.

## Standalone binary

Cursor View can also be packaged as a standalone binary so it can be run
without a Python toolchain. By default the binary behaves the same way as
`python3 terminal.py`: it starts a local Flask server and opens the chat UI
in your default browser. Passing `--desktop` opts into an experimental
mode where the UI is rendered inside a native OS webview window (WebView2
on Windows, WKWebView on macOS, WebKitGTK/Qt on Linux) via
[pywebview](https://pywebview.flowrl.com/).

### Run from source (desktop mode)

```
python3 -m pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
python3 desktop.py
```

On Linux you may also need system webview libraries, e.g. on Debian/Ubuntu:

```
sudo apt install libwebkit2gtk-4.1-0
```

(Alternatively, `pywebview[qt]` is installed by default on Linux via
`requirements.txt`, which uses QtWebEngine.)

### Build a standalone binary

Icons live under `assets/icons/`. If you replace `frontend/public/logo512.png`
and want to regenerate them, run:

```
python3 assets/icons/_generate_icons.py
```

Then build with PyInstaller using the included spec:

```
pyinstaller cursor-view.spec
```

This produces a console binary in `dist/`:

- Windows: `dist/cursor-view/cursor-view.exe`
- macOS:   `dist/cursor-view/cursor-view` (plus `dist/Cursor View.app` wrapping the same binary)
- Linux:   `dist/cursor-view/cursor-view`

On macOS, unsigned local builds may be quarantined by Gatekeeper. To run
without code signing:

```
xattr -dr com.apple.quarantine "dist/Cursor View.app"
```

### Running the binary

By default the binary starts the Flask server and opens the browser:

```
cursor-view                 # default: terminal/server mode + auto-open browser
cursor-view --no-browser    # server only; open the browser yourself
cursor-view --port 8080     # use a different port
cursor-view --desktop       # experimental webview UI instead of the browser
```

On macOS the `.app` bundle is purely cosmetic packaging around the same
`cursor-view` binary, so double-clicking `Cursor View.app` in Finder
behaves like double-clicking the Windows `.exe`: it starts the server and
opens the browser. To launch the experimental desktop mode from Finder,
pass the flag explicitly:

```
open -a "Cursor View" --args --desktop
```

### User preferences / webview profile

When using `--desktop`, the app persists UI preferences (theme, export
warning opt-out) in a per-user webview profile directory:

- Windows: `%LOCALAPPDATA%\cursor-view\webview-storage`
- macOS:   `~/Library/Caches/cursor-view/webview-storage`
- Linux:   `$XDG_CACHE_HOME/cursor-view/webview-storage` (falls back to
  `~/.cache/cursor-view/webview-storage`)

Delete that folder to reset preferences.

## Features

- Browse all Cursor chat sessions
- Search through chat history
- Export chats as HTML, JSON, or Markdown
- Organize chats by project
- View timestamps of conversations

_Originally built by [Sahar Mor](https://www.linkedin.com/in/sahar-mor/)._
