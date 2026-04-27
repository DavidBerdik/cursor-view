# Contributing to Cursor View

A contributor's map of where things live. The three scripts at the repo
root are thin shims; the bulk of the code lives inside the
`cursor_view/` Python package and the `frontend/src/` React app.

## Entry points

- `terminal.py` &mdash; starts the Flask server and opens the chat UI
  in your browser (the default mode).
- `desktop.py` &mdash; launches the same Flask server inside a native
  pywebview window.
- `cursor_view_main.py` &mdash; unified entry point used by PyInstaller;
  dispatches to terminal or desktop mode based on `--desktop`.
  Equivalent to `python3 -m cursor_view`.

## Backend (`cursor_view/`)

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
  normalization), `html.py` (standalone HTML assembler &mdash; imports
  `HTML_STYLE_TEMPLATE` from `html_styles.py` and substitutes theme
  tokens via `str.format_map`), `html_styles.py` (the large CSS skin
  that wraps every HTML export, split out of `html.py` so the
  rendering logic and the style sheet evolve independently),
  `mermaid.py` (fence-to-div rewrite + vendored JS loader + init-script
  builder for mermaid diagram support in HTML exports).
  Both `markdown.py` and `html.py` inline image attachments as
  `data:<mime>;base64,...` URIs so the exported file is self-contained.
  `export/vendor/` holds `mermaid.min.js` (committed third-party asset,
  not a build artifact &mdash; see "Updating vendored mermaid" below).
- `images/` &mdash; image attachment parsing and byte loading shared
  between extraction and the cache write path. `refs.py` owns the
  `ImageRef` dataclass and `parse_bubble_images` (walks both the
  modern `context.selectedImages` on-disk-path shape and the legacy
  top-level `images` inline-byte-dict shape, dedups by uuid with disk
  preferred). `transport.py` owns the `image_ref_to_transport_dict` /
  `image_ref_from_transport_dict` codec used to serialize `ImageRef`
  values across the extraction-pipeline / chat-index-writer boundary
  (split off from `refs.py` so both halves stay short and focused).
  `loading.py` owns `load_image_bytes` and `_sniff_mime` (stdlib-only
  magic-byte sniffing for PNG / JPEG / GIF / WEBP) with a graceful
  skip + lazy `%s` warning for missing or malformed sources.
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
  `chat_message`, `chat_search_text`, `chat_search_fts`, `chat_image`.
  Both the full rebuild and the per-cid delete-then-insert in
  `cache/delta/engine.py` go through
  `cursor_view.chat_index.rows._insert_chat`, so the row shape is
  identical between the rebuild and delta paths. `chat_summary`
  carries the per-session card-grid metadata (project / root path /
  date / workspace id / db path / message count / preview / sort
  key / `title`); the `title` column stores Cursor's
  `composerData.name` when present and an empty string when
  extraction's synthetic `(untitled)` / `Chat <8hex>` /
  `Global Chat <8hex>` placeholders have been classified out by
  `cursor_view.chat_format._real_chat_title`, so consumers can gate
  rendering with a plain truthiness check. `chat_image`
  materializes one BLOB row per attached image (keyed by
  `(session_id, position, image_index)`) so the chat-index is the
  single cache of record &mdash; Cursor's on-disk image files may be
  deleted without data loss once a composer has been indexed. Bytes
  flow to the browser through the dedicated
  `GET /api/chat/<session_id>/image/<image_uuid>` route (keeping the
  chat-detail JSON small) or, for exports, through
  `ChatIndex.get_chat(..., include_image_bytes=True)` which inlines
  `data:<mime>;base64,...` URIs.
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

## Running the tests

Stdlib `unittest` tests that exercise the incremental refresh path
against synthetic Cursor source DBs. Run with:

```
python -m unittest discover -s tests
```

`tests/test_chat_index_incremental.py` covers the four behaviors the
delta path is specifically designed for: single-bubble mutation,
workspace `treeViewState` churn, first-time `task_v2` subagent spawn,
and pane-view key promotion from `(global)` to a workspace.

The image-attachment coverage is split across three sibling test
modules plus a shared helper, all under `tests/`:

- `tests/_image_test_helpers.py` &mdash; shared fixtures
  (`_create_source_schema`, `_put_kv`, `_composer`, the four
  `_bubble_with_*` builders, `_export_chat_fixture`, `PNG_PREFIX`)
  and the `BaseChatIndexImageTest` harness with its four
  `cursor_root` patches. Leading-underscore name keeps it out of
  `unittest.discover`'s default `test_*.py` pattern so it is
  imported as a helper, not run as a test.
- `tests/test_chat_index_images_core.py` &mdash; the original
  end-to-end rebuild scenarios: modern-shape (on-disk) and
  legacy-shape (inline byte dict) rebuilds, image modification via
  incremental apply, and multiple images per message round-tripping
  through `chat_image` &rarr; `_fetch_images_for_session` &rarr;
  `ChatIndex.get_chat` / `get_image`; plus the two original
  coalescer unit cases (same-role image concatenation and the
  image-only-turn placeholder).
- `tests/test_chat_index_images_regressions.py` &mdash; the
  image-attachment post-impl regressions: graceful skip on a missing
  disk file (with an `assertLogs` on the missing-disk warning so
  silent `OSError` swallowing fails the test), image-only chat
  preview fallback, `include_image_bytes=True` base64 round-trip via
  `get_chat`, disk-preferred dedup when the same uuid appears in
  both storage shapes, non-dict bubble JSON handling, out-of-range
  `chat_image.position` dropped with a warning, and the post-loop
  clear of a `"Content unavailable"` seed when same-role image
  merging makes the record image-bearing.
- `tests/test_chat_index_images_exports.py` &mdash; Markdown
  export's blank-line separator between `<img>` and the trailing
  `---` thematic break, and the HTML export's
  `<a href=... target=_blank rel=noopener>` wrapper around every
  `<img>` with matching `.message-images a` / `a:hover` CSS. Also
  pins the chat-title export shape: a Markdown export with a real
  title promotes to `# {title}` and prepends a `- **Title:**`
  bullet (untitled exports keep the legacy
  `# Cursor Chat: {project_name}` heading byte-for-byte), and an
  HTML export with a real title swaps the head `<title>`, `<h1>`,
  and emits a new `Title:` info-strip row that is omitted entirely
  for untitled chats.

`tests/test_chat_index_titles.py` covers the `chat_summary.title`
column added under schema v3: a real `composerData.name`
round-trips end-to-end through `format_chat_for_frontend`,
`_insert_chat`, `list_summaries`, and `get_chat`; synthetic
extraction placeholders collapse to `""`; FTS and the LIKE
fallback both find a chat by a phrase from its title (exercising
the `title`-prepended `_search_blob`); and an in-place
`composerData.name` rename surfaces through the incremental
refresh path (exercising the `_composer_hash` payload that now
includes `title` for parity with the served shape).

`tests/test_chat_index_sort_order.py` pins the `createdAt`-first
priority of `chat_summary.sort_key_ms` (the column the home-page
`ORDER BY sort_key_ms DESC` query reads): a chat with a newer
`composerData.createdAt` sorts ahead of one with a newer
`lastUpdatedAt`, so the per-project card grid stays in the order
users see on the cards. Cursor bumps `lastUpdatedAt` on
navigation-only writes (see
[`.cursor/rules/sqlite-cursor-db.mdc`](../.cursor/rules/sqlite-cursor-db.mdc)
"Invalidation: hash rows, don't stat files"), which would
otherwise re-shuffle the list whenever a user idly clicked
through a chat. The module also pins the `lastUpdatedAt`
fallback so a legacy composer that lacks `createdAt` still
resolves a sensible position instead of sinking to
`sort_key_ms = 0`.

`tests/test_export_html_mermaid.py` covers the mermaid HTML export
path: fence-to-div rewrite, vendored JS inlining, HTML escaping of
special characters in diagram source, non-mermaid fence regression
guard, and dark/light theme selection.

`tests/test_known_bug_fixes.py` pins the contracts established by
the [`known-bugs.mdc`](../.cursor/rules/known-bugs.mdc) fix-pass:
`format_chat_for_frontend` raising on malformed input is contained
by the per-chat skip-with-log boundary in
`cursor_view/chat_index/rebuild.py` and
`cursor_view/cache/delta/engine.py` (no synthetic-UUID ghost row in
`chat_summary` on either the full rebuild path or the incremental
apply path), and `iter_global_legacy_chatdata` releases its SQLite
connection on the error path (driven by a missing `ItemTable` so
`j()` raises `sqlite3.OperationalError`, asserted by capturing the
connection and verifying a post-iter `execute` raises
`ProgrammingError`).

## Frontend (`frontend/src/`)

- `App.js`, `index.js`, `index.css`, `starry-night-theme.css` &mdash;
  root composition and global CSS.
- `theme/` &mdash; `colors.js` (palettes), `buildTheme.js` (MUI theme
  factory), `themeCookie.js` (dark/light cookie).
- `contexts/` &mdash; `ColorContext.js` and `ThemeModeContext.js`, one
  React context per file.
- `hooks/` &mdash; shared custom hooks: `useChatSummaries`
  (fetch + `latestRef` + `AbortController` so a stale prefix is
  cancelled on the wire, not just ignored on the client),
  `useDebouncedValue` (coalesces a high-churn input value before it
  reaches a fetching hook's dep array; `ChatList` pairs it with
  `useChatSummaries` so typing into the search bar fires one
  `/api/chats` request per pause instead of one per keystroke),
  `useExportFlow`, `useExportWarningPreference`, `useSavedSelection`
  (captures + restores the user's text selection across the
  context-menu open cycle), `useMermaid` (bootstraps the mermaid
  singleton and keeps its theme in sync with `ThemeModeContext`).
- `utils/` &mdash; pure helpers: `formatDate`, `dbPath`, `cookies`,
  `exportChat`, `dom` (`isEditableElement` / `findSelectionContainer`,
  consumed by `AppContextMenu`), `mode` (`isDesktopMode()` &mdash;
  shared pywebview-runtime detection consumed by both `exportChat.js`
  and `AppContextMenu.js`).
- `markdown/` &mdash; the unified/remark/rehype pipeline that
  pre-renders chat messages to HTML.
- `components/`
  - `Header.js`, `AppContextMenu.js`, `MessageMarkdown.js`,
    `MermaidBlock.js` &mdash; global UI. `MermaidBlock` renders a
    mermaid fenced code block as a live diagram (default) or raw source,
    with a per-block toggle and a parse-error fallback.
  - `chat-list/` &mdash; the list page split into `ChatList`,
    `SearchBar`, `EmptyState`, `ProjectGroup`, `ChatCard`.
  - `chat-detail/` &mdash; the detail page split into `ChatDetail`,
    `ChatMetaPanel`, `MessageList`, `MessageBubble`,
    `MessageImageGallery` (renders attached-image thumbnails via
    `GET /api/chat/:id/image/:uuid`), and its sibling
    `ImageLightboxModal` (the full-size modal the gallery opens on
    thumbnail click, with prev/next chevrons, counter, thumbnail
    strip, and keyboard navigation).
  - `export/` &mdash; shared `ExportFormatDialog` and
    `ExportWarningDialog` used by both pages.

## Assets and configuration

- `cursor-view.spec` &mdash; PyInstaller spec that bundles
  `cursor_view_main.py` and `frontend/build/` into the standalone
  binary.
- `assets/icons/` &mdash; multi-platform app icons plus the
  `_generate_icons.py` regeneration script.
- `.github/workflows/desktop-build.yml` &mdash; CI that builds the
  standalone binary on Windows, macOS, and Linux.
- `requirements.txt`, `frontend/package.json` &mdash; Python and JS
  dependencies, respectively.

## Build a standalone binary

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

## Updating vendored mermaid

The HTML export embeds `cursor_view/export/vendor/mermaid.min.js` so
exported files are fully self-contained (no network required at view
time). This file is a committed third-party asset, not a generated
artifact. To upgrade the mermaid version:

1. Update `"mermaid"` in `frontend/package.json` to the new version and
   run:
   ```
   cd frontend
   npm install
   ```
2. Copy the updated UMD build into the vendor directory:
   ```
   cp frontend/node_modules/mermaid/dist/mermaid.min.js \
      cursor_view/export/vendor/mermaid.min.js
   ```
3. Update the version record:
   ```
   echo -n "X.Y.Z" > cursor_view/export/vendor/VERSION.txt
   ```
4. Commit `frontend/package.json`, `frontend/package-lock.json`,
   `cursor_view/export/vendor/mermaid.min.js`, and
   `cursor_view/export/vendor/VERSION.txt` together.

The npm package (used by the React chat view) and the vendored UMD build
(used by HTML exports) must track the **same major version** to avoid
diagram-syntax drift between the two rendering paths.

## Project conventions

Persistent coding conventions live under [`.cursor/rules/`](../.cursor/rules/).
Each `.mdc` file is a focused rule with a short rationale, canonical
examples, and motivating sources from the codebase. Currently maintained
rules cover comment style, Python standards, React component shape,
custom-hook discipline, image-attachment handling, mermaid rendering,
chat-index refresh routing, SQLite / Cursor-DB access patterns, known-bug
marker conventions, and this repository's layout policy. When a rule
conflicts with an in-flight change, update the rule in the same PR
&mdash; a stale rule is worse than no rule.
