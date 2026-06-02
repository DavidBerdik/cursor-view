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
  transaction. The home page Refresh button (`force_refresh=True`)
  routes through the same delta path as the SWR background worker
  via the shared `ChatIndex._run_synchronous_delta_or_rebuild`
  helper, so a manual refresh pays the diff cost rather than the
  full build-to-temp + atomic-swap cost. The helper falls back to a
  full rebuild only when the cache is missing, the `meta` table is
  unreadable (`DatabaseError`), `schema_version` does not match
  `INDEX_SCHEMA_VERSION`, or `compute_source_diff` / `apply_delta`
  themselves raise `DatabaseError`.
- `extraction/` &mdash; pipeline that scans Cursor's SQLite databases
  and produces chat sessions. `core.py` holds the `extract_chats`
  orchestrator, the `CachedExtractionState` helper dataclass, and
  `_merge_global_composer_into_meta`. The eight ordered passes live
  under `passes/` (`workspace_messages.py`, `global_bubbles.py`,
  `global_composers.py`, `uri_fallbacks.py`, `task_subagents.py`,
  `subagent_inheritance.py`, `item_table_chats.py`, `finalize.py`)
  so each pass reads as a unit. `diagnostics/` holds the optional
  probes: `workspace_dump.py` is the coarse "what tables / key
  prefixes does this Cursor install have?" log dump that the
  pipeline runs once at the top of `extract_chats` when
  `CURSOR_CHAT_DIAGNOSTICS` is set, and `trace.py` plus
  `probes.py` / `walker.py` back the per-cid resolution-trace CLI
  invoked via `python -m cursor_view.extraction.diagnostics --cid <id>`,
  which classifies a chat's `(unknown)` / `(global)` symptom into
  one of four documented root causes (orphan-filter drop,
  scoped-mode walk gap, dead-chain top, deleted parent).
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
    post-hash deletion classification, the
    `workspace_comp2ws_dirty` observability trim, and owns the
    reusable subagent-descendant BFS helper that the apply-time
    gate in `cache/delta/propagation.py` calls. The diff itself
    no longer walks the subagent-parent chain &mdash; that walk is
    deferred to apply time so it can be gated on real
    project-resolution shifts (or parent deletion / edge churn)
    instead of every parent that happened to have a row-hash flip.
  - `cache/delta/` &mdash; the single-transaction write pass.
    `engine.py` holds the `apply_delta` orchestrator;
    `cached_state.py` seeds scoped extraction with ancestor +
    `tool_call_parent` state (carrying both the merged Pass-5-ready
    map and a pre-merge raw snapshot the apply-time gate consumes
    for edge-churn detection); `composer_rows.py` does per-composer
    delete / re-extract / upsert plus the shared `_apply_chat_writes`
    delete-then-insert-then-upsert loop both apply phases use;
    `propagation.py` is the apply-time subagent-propagation gate
    (snapshot cached project, detect project shifts, build trigger
    set, walk descendants, augment cached state for the secondary
    extraction, write the propagated chats &mdash; all inside the same
    `BEGIN IMMEDIATE` transaction `engine.py` opened, mirroring the
    diff side's `engine`/`propagation` split); `project_only.py` is
    the workspace-scoped project refresh for
    `workspace_project_dirty` entries; `metadata.py` reconciles
    `tool_call_parent`, `source_row`, and the `meta` book-keeping
    rows; `backfill.py` runs the one-shot full-rebuild backfill
    that populates the delta tables below.
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
  `run_desktop`; `api.py` is the JS &harr; Python bridge (export save,
  external-link routing, plus the menu actions `toggle_theme` /
  `reload_window` / `quit_app` / debug-only `toggle_devtools`);
  `menu.py` builds the native File / Edit / View / Help menu tree
  (`build_menu(api)`) passed to `webview.start(menu=...)`, routing every
  cross-mode action through the `api.py` bridge and falling back to no
  menu on backends without menu support (see the "Native menu bar"
  invariant in
  [`.cursor/rules/desktop-mode.mdc`](../.cursor/rules/desktop-mode.mdc));
  `auth.py` is the desktop-only loopback-token gate &mdash;
  `generate_token()` mints a per-launch secret and `install_auth(app,
  token)` registers a `before_request` that 401s `/api/*` without the
  matching `X-Cursor-View-Token` header or `cursor-view-token` cookie
  plus an `after_request` that bootstraps that cookie on the SPA shell
  (installed only from `run_desktop`, so terminal mode and `routes.py`
  stay untouched; see the "Loopback-token auth in desktop mode"
  invariant in
  [`.cursor/rules/desktop-mode.mdc`](../.cursor/rules/desktop-mode.mdc));
  `logging_setup.py` adds desktop-mode file logging &mdash;
  `configure_desktop_logging()` attaches a 1&nbsp;MB-cap (3-backup)
  `RotatingFileHandler` writing to `cursor_view_log_dir()/desktop.log`
  (under the cache dir) alongside the stderr handler, and
  `redirect_stdio_to_logging()` routes stray stdout/stderr into the log
  in frozen builds only (the windowless Windows binary has no console);
  `window_state.py` persists window geometry across launches;
  `readiness.py` is the stdlib-only `wait_for_server` probe that polls
  `GET /` until the daemon Flask thread answers; `splash.py` provides
  the inline HTML splash (fed to `create_window(html=...)`, since
  Chromium backends block top-level `data:` navigation) the window
  shows while that probe runs; `error_window.py` renders a native
  startup-error window (`show_startup_error` for failures before the GUI
  loop starts, `build_error_html` for the readiness-timeout case that
  loads into the already-open splash window) with the message and
  traceback HTML-escaped; `single_instance.py` enforces one desktop
  instance via a `desktop.lock` (`{pid, port, started_at_ns}`) file in
  the cache dir — a second launch `notify_existing`s the running
  instance over a loopback `POST /__desktop_focus__` (registered only in
  desktop mode) and exits. Its PID-liveness probe is platform-split
  (`os.kill(pid, 0)` on POSIX, a read-only `ctypes` `OpenProcess` check
  on Windows, since `os.kill` on Windows routes through
  `TerminateProcess`).
  `run_desktop` opens the window on the splash and only navigates to the
  loopback URL once `wait_for_server` succeeds, so cold launches never
  flash the webview's native "site can't be reached" frame (see the
  "Wait before navigating" invariant in
  [`.cursor/rules/desktop-mode.mdc`](../.cursor/rules/desktop-mode.mdc)).

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
    every bubble in the global DB, and drives the apply-time gated
    propagation walk in `cursor_view/cache/delta/propagation.py`.
    The walk fires only when a directly-modified parent's
    post-extraction `chat_summary` triple
    (`workspace_id`, `project_name`, `project_root_path`) actually
    shifts versus the cached row, when the parent lands in
    `dirty.deleted_cids`, when the parent soft-deletes (it stays in
    `dirty.modified_cids` but its primary extraction returns no
    chat &mdash; every bubble pruned by the
    `composerData.fullConversationHeadersOnly` orphan invariant, a
    now-empty `conversation` array, etc. &mdash; so its
    `chat_summary` and `composer_state` rows are cleared without
    re-insert), or when a `tool_call_parent_updates` entry differs
    from the cached map (new edge / rewired parent / removed
    edge). A parent whose bubble JSON changed without shifting its
    project no longer drags every descendant subagent into the
    apply loop &mdash; that was the dominant source of the "23242
    modified (inserted 505, 22737 subagent-propagated)"-style
    refresh logs the gate exists to fix. Soft-deletion is bookkept
    under `modified_cids` rather than `deleted_cids` (the cid still
    has at least one source row, e.g. a workspace pane-view key)
    but is functionally identical from a descendant's perspective
    because the inheritance anchor is gone either way.

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

`tests/test_chat_index_propagation_gating.py` pins the five
invariants the apply-time subagent-propagation gate in
`cursor_view/cache/delta/propagation.py` was introduced to
enforce: (1) a parent bubble append without project shift does
NOT propagate (the subagent's `chat_message` rowids stay
byte-for-byte identical, witnessing that the gate skipped the
descendant entirely); (2) a parent project promotion (e.g. via a
new pane-view key) DOES propagate so the `task-*` child
re-inherits the new workspace; (3) a parent deletion propagates
and the child's Pass 6 walk falls through to `(global)` because
`cached_state.ancestor_comp2ws` deliberately excludes deleted
cids; (4) a new `tool_call_parent` edge propagates only the
targeted `task-<tcid>` child and leaves the unchanged sibling
subagent untouched, which is the surgical-trigger guarantee that
distinguishes the new gating from the pre-implementation "every
parent's `task-*` descendants" walk; and (5) a soft-deleted
parent (in `dirty.modified_cids` but its primary extraction
returns no chat because every bubble was orphan-filtered out of
`composerData.fullConversationHeadersOnly`) propagates exactly
like a hard deletion &mdash; the descendant rides the secondary
scoped extraction (witnessed by changed `chat_message` rowids)
even though the cid never lands in `dirty.deleted_cids`.

`tests/test_export_html_mermaid.py` covers the mermaid HTML export
path: fence-to-div rewrite, vendored JS inlining, HTML escaping of
special characters in diagram source, non-mermaid fence regression
guard, and dark/light theme selection.

`tests/test_known_bug_fixes.py` pins the contracts established by
the [`known-bugs.mdc`](../.cursor/rules/known-bugs.mdc) fix-pass:
`format_chat_for_frontend` raising on malformed input is contained
by the per-chat skip-with-log boundary in
`cursor_view/chat_index/rebuild.py` and
`cursor_view/cache/delta/composer_rows.py::_apply_chat_writes`
(shared by both apply phases, so the boundary covers the
incremental delta path the same way the rebuild path covers the
full re-index; no synthetic-UUID ghost row in `chat_summary`
either way), and `iter_global_legacy_chatdata` releases its
SQLite connection on the error path (driven by a missing
`ItemTable` so `j()` raises `sqlite3.OperationalError`, asserted
by capturing the connection and verifying a post-iter `execute`
raises `ProgrammingError`).

## Frontend (`frontend/src/`)

- `App.js`, `index.js`, `index.css`, `starry-night-theme.css` &mdash;
  root composition and global CSS.
- `theme/` &mdash; `colors.js` (palette source of truth, consumed
  only by `buildTheme.js`'s `paletteFromColors` helper to produce
  `colorSchemes.light.palette` and `colorSchemes.dark.palette`),
  `buildTheme.js` (single static MUI theme via
  `createTheme({ cssVariables: { colorSchemeSelector:
  'data-mui-color-scheme' }, colorSchemes: { light, dark } })`;
  MUI's CSS-variables-aware `<ThemeProvider>` emits `--mui-palette-*`
  CSS variables for both schemes and flips `data-mui-color-scheme`
  on toggle, so consumers reference `var(--mui-palette-X)` in `sx`
  and the dark/light flip becomes a CSS-only operation with no
  React re-render of palette consumers), `themeCookie.js` (dark/light
  cookie, paired with MUI's automatic localStorage `mui-mode` key
  for cross-tab sync), `transitions.js` (the `PALETTE_TRANSITION`
  token plus its constituent `PALETTE_TRANSITION_DURATION` /
  `PALETTE_TRANSITION_CURVE` / `PALETTE_TRANSITION_PROPERTIES`
  exports, wired through `buildTheme.js`'s `styleOverrides` and
  inline `sx` on raw `<Box>` elements as the per-element fallback
  for browsers without View Transitions support and for non-toggle
  palette changes; the property list narrows the transition's blast
  radius from `'all'` for compositor-cost reasons documented in
  [`theme-transitions.mdc`](../.cursor/rules/theme-transitions.mdc)).
- `contexts/` &mdash; `ThemeModeContext.js` only (was paired with
  `ColorContext.js` until the CSS-variables migration deleted the
  latter). The provider lives in `App.js::ThemeModeBridge` and
  derives `darkMode` from MUI's `useColorScheme().mode === 'dark'`
  and `toggleDarkMode` from `setMode(...)` wrapped in
  `document.startViewTransition` + `flushSync` plus the
  `themeCookie.js` write, exposing a stable
  `{ darkMode: boolean, toggleDarkMode: () => void }` interface to
  the small set of consumers that genuinely need a JS boolean rather
  than a CSS value: mermaid's
  `mermaid.initialize({ theme: darkMode ? 'dark' : 'default' })`
  selection, per-scheme alpha picks where the alpha *value* differs
  by scheme, `useExportFlow`'s mode argument. Palette consumers no
  longer read from React context at all; they reference
  `var(--mui-palette-*)` directly &mdash; see "CSS variables
  palette" in
  [`theme-transitions.mdc`](../.cursor/rules/theme-transitions.mdc).
- `hooks/` &mdash; shared custom hooks: `useChatSummaries`
  (fetch + `latestRef` + `AbortController` so a stale prefix is
  cancelled on the wire, not just ignored on the client),
  `useDebouncedValue` (coalesces a high-churn input value before it
  reaches a fetching hook's dep array; `ChatList` pairs it with
  `useChatSummaries` so typing into the search bar fires one
  `/api/chats` request per pause instead of one per keystroke),
  `useExportFlow`, `useExportWarningPreference`, `useDesktopMenuEvents`
  (bridges native desktop-menu actions into React state by listening
  for the window `CustomEvent`s the Python menu dispatches &mdash; see
  `utils/desktopEvents.js` for the names; called once from
  `App.js::ThemeModeBridge` and a no-op in terminal mode),
  `useDesktopExternalLinks` (global capture-phase `click`/`auxclick`
  interceptor, called once from `App.js::ThemeModeBridge`, that routes
  external non-same-origin `<a>`/`<area>` clicks to
  `pywebview.api.open_url_in_browser` in desktop mode &mdash; so the
  Header GitHub button, chat-content links, and the image lightbox open
  in the OS browser instead of the embedded webview; preserves native
  behavior for same-origin links, `download`, non-http(s) schemes, and
  all of terminal mode),
  `useDesktopReady` (reactive desktop-runtime readiness boolean: seeds
  from the synchronous `isDesktopMode()` then flips on pywebview's
  `pywebviewready` event &mdash; necessary because pywebview's
  WebView2 backend injects `window.pywebview` from
  `NavigationCompleted`, *after* React has already mounted, so a
  render-time `isDesktopMode()` is racy and a memo gated on it would
  stay stuck on cold launch; consumed by the shortcut-map `useMemo` in
  `App.js` and the `(Ctrl+T)` / `(\u2318T)` tooltip hint in
  `Header.js`),
  `useGlobalKeyboardShortcuts` (registers one global `keydown` listener
  that dispatches to a caller-supplied `{ 'mod+t': () => ... }` map &mdash;
  combo parsing and the platform `mod` resolution live in
  `utils/keyboardShortcuts.js`; `App.js` populates the map only when
  `useDesktopReady` is true so Reload / Quit / Toggle Theme bind once
  pywebview is live, since the native menu's accelerators are
  display-only),
  `useInView`
  (IntersectionObserver visibility for a `ref`'d element, with
  default-`true` fallback when the API is unavailable; consumed by
  `MermaidDiagramSurface` to skip the cross-fade overlay for
  off-screen diagrams), `useReducedMotion`
  (`prefers-reduced-motion: reduce` matchMedia with a live `change`
  listener so an OS-setting flip during the session updates the
  return without a reload; consumed at the JS-side gate in
  `MermaidDiagramSurface` where the global CSS opt-out in
  `index.css` is not enough on its own &mdash; the CSS rule disables
  the keyframe animation but the doubled-DOM cross-fade layer would
  still mount and stick at `opacity: 1`), `useSavedSelection`
  (captures + restores the user's text selection across the
  context-menu open cycle), `useMermaid` (bootstraps the mermaid
  singleton and keeps its theme in sync with `ThemeModeContext`),
  `useMermaidRender` (per-block parse + render machine for mermaid
  sources &mdash; owns `svg` / `renderError` state, the `latestRef`
  cancellation pattern, the theme-tagged `skipFirstRenderRef`
  prerender suppression, and the cache + queue routing; consumed
  by `MermaidBlock` so the component itself stays focused on the
  diagram/source toggle, the lightbox modal state, and the auto-
  close-on-error effect), `useMermaidBlockHeight`
  (`ResizeObserver`-driven recorder that observes
  `MermaidBlock`'s outer `<Box>` and persists each block's
  rendered height into `mermaidHeightCache` for use as
  `containIntrinsicSize` on the next refresh; returns
  `{ ref, persistedHeight }` with `persistedHeight` read once
  via a lazy `useState` initializer so the placeholder size
  stays stable for the block's lifetime; consumer-side
  counterpart of the height cache, and the primary determinism
  mechanism for `useChatScrollAnchor`'s scroll restore on
  diagram-heavy chats &mdash; see "Two CSS containment hints"
  in [`theme-transitions.mdc`](../.cursor/rules/theme-transitions.mdc)),
  `useSvgCrossFade` (cross-fade state
  machine for a string-typed imperative-DOM payload &mdash; owns
  the outgoing-layer state, the keyframe constant, the visibility
  / reduced-motion / concurrent-fade-cap gate triple, the
  `onAnimationEnd` cleanup, AND a manually-attached
  `animationcancel` listener (wired via the consumer's
  `outgoingRef` because React JSX has no `onAnimationCancel`
  shorthand) that catches the case where the OS-level
  reduced-motion preference flips during an in-flight fade and
  the global CSS rule rewrites the running keyframe to
  `animation: none !important`, firing `animationcancel` instead
  of `animationend`; consumed by `MermaidDiagramSurface` to keep
  the surface focused on the layered JSX, the per-scheme alpha
  tint, and the `contain` containment hint),
  `useSvgPanZoom` (modal-local transform state, pointer drag,
  wheel/button zoom, and identity-reset for prop-fed SVG surfaces;
  the anchor-preserving zoom math lives in pure helpers in
  `utils/svgPanZoomModel.js`, and the consumer's CSS centers the
  SVG at identity transform so the hook does not measure a
  per-diagram fit baseline itself), and `useChatScrollAnchor`
  (chat-detail scroll save/restore &mdash; owns the
  `useLayoutEffect` that parses the saved `sessionStorage` entry
  for the current `sessionId`, restores via `window.scrollTo`,
  runs a `requestAnimationFrame`-driven re-scroll loop with
  stable-frames-based convergence (exit after the position is
  stable for 2 consecutive frames, with a 30-frame safety
  ceiling) that catches `content-visibility: auto`
  materialization shifts in the residual unmeasured-block case
  &mdash; the rAF loop is the safety net, the primary
  determinism mechanism is `useMermaidBlockHeight` +
  `mermaidHeightCache` populating accurate
  `containIntrinsicSize` so the layout above the anchor is
  deterministic before the first `scrollTo` &mdash; and
  registers the debounced scroll listener that saves the
  anchor-based `{ msgIdx, offset }` JSON back to
  `sessionStorage`; consumed by `ChatDetail` so the page
  component stays focused on the fetch-and-prepare pipeline and
  the layout JSX).
- `utils/` &mdash; pure helpers: `formatDate`, `dbPath`, `cookies`,
  `exportChat`, `dom` (`isEditableElement` / `findSelectionContainer`,
  consumed by `AppContextMenu`),   `mode` (`isDesktopMode()` &mdash;
  shared pywebview-runtime detection consumed by both `exportChat.js`
  and `AppContextMenu.js`),   `desktopEvents` (the `CustomEvent` name
  constants the native desktop menu dispatches into the React app,
  kept byte-for-byte in sync with `cursor_view/desktop/api.py` and
  consumed by `useDesktopMenuEvents`), `keyboardShortcuts`
  (`isMac` / `formatShortcut` / `eventMatchesCombo` &mdash; the
  combo-string parser and platform `mod`-modifier resolution shared by
  `useGlobalKeyboardShortcuts` and the `Header.js` shortcut hint, with
  the display format matching the accelerator hints
  `cursor_view/desktop/menu.py` appends to the native menu titles),
  `mermaidRenderCache` (session-scoped
  `Map<key, svg>` keyed by `(source, darkMode)` so repeat dark/light
  toggles short-circuit at the cache layer instead of re-running
  `mermaid.parse + mermaid.render`; the bomb-graphic invariant from
  [`mermaid-rendering.mdc`](../.cursor/rules/mermaid-rendering.mdc)
  "Parse before render" stays satisfied by construction because
  cache writes only happen on the render success path),
  `mermaidRenderQueue` (FIFO promise-chain queue with concurrency 1
  so a theme toggle on a chat with N uncached diagrams runs the
  renders one at a time instead of racing all of them on the JS
  thread; consulted only on cache miss, see
  [`mermaid-rendering.mdc`](../.cursor/rules/mermaid-rendering.mdc)
  "Render cache and queue" for the wire-up invariants), and
  `mermaidHeightCache` (layout-axis sibling of
  `mermaidRenderCache`; session-scoped `sessionStorage`-backed
  source-keyed `Map<source, height>` populated by
  `useMermaidBlockHeight`'s `ResizeObserver` and read by the
  same hook's lazy `useState` initializer so `MermaidBlock` can
  set `containIntrinsicSize: \`0 ${persistedHeight ?? 400}px\``
  on its outer `<Box>`; this is what makes
  `useChatScrollAnchor`'s scroll restore deterministic on
  refresh of diagram-heavy chats by ensuring the layout above
  the saved anchor matches the layout at save time before the
  first `scrollTo` runs; the cache wraps every `sessionStorage`
  access in `try`/`catch` so privacy-mode / quota-exceeded
  silently degrades to "no persisted heights" rather than
  throwing into the chat view, see
  [`mermaid-rendering.mdc`](../.cursor/rules/mermaid-rendering.mdc)
  "Render cache and queue" → "`mermaidHeightCache`").
- `markdown/` &mdash; the unified/remark/rehype pipeline that
  pre-renders chat messages to HTML.
- `components/`
  - `Header.js`, `AppContextMenu.js`, `MessageMarkdown.js`,
    `MermaidBlock.js`, `MermaidDiagramSurface.js`, `MermaidToolbar.js`,
    `MermaidLightboxModal.js`, `MermaidZoomControls.js`,
    `MermaidLightboxFallback.js` &mdash; global UI. `MermaidBlock`
    renders a mermaid fenced code block as a live diagram (default)
    or raw source, with a per-block toggle and a parse-error
    fallback. Its sibling `MermaidToolbar` holds the
    absolute-positioned diagram/source toggle and expand-into-modal
    icon (extracted to keep `MermaidBlock` under the 250-line
    decomposition cap from
    [`react-components.mdc`](../.cursor/rules/react-components.mdc)).
    `MermaidDiagramSurface` owns the diagram-mode click surface and
    the cross-fade between the previous and current SVG strings on
    dark/light toggle: mermaid emits a fresh tree of inline-styled
    DOM nodes per render that share no element identity with the
    previous SVG, so a CSS `transition` on the surrounding chrome
    cannot bridge the two states &mdash; the fix layers an
    absolutely-positioned `aria-hidden` outgoing copy on top of the
    incoming SVG and runs a CSS keyframe animation to fade the
    outgoing layer. The cross-fade is gated on `useInView` and
    `useReducedMotion` so off-screen diagrams skip the doubled-DOM
    cost entirely and reduced-motion users see instant swaps; the
    outgoing layer carries `willChange: 'opacity'` for GPU
    compositor promotion during the bounded fade window. See
    [`theme-transitions.mdc`](../.cursor/rules/theme-transitions.mdc)
    "SVG content cross-fade".
    `MermaidLightboxModal` is the full-size modal opened on click of
    the diagram body or the expand icon: it consumes the SVG already
    in `MermaidBlock`'s state via props (no second `mermaid.render`
    call, per [`mermaid-rendering.mdc`](../.cursor/rules/mermaid-rendering.mdc)),
    applies transform-based pan/zoom interactions over that prop-fed
    SVG, and exposes a toolbar row with zoom out / reset / zoom in
    plus close. `MermaidZoomControls` keeps those zoom actions
    presentational so the modal remains layout-focused, while the
    interaction state machine lives in `useSvgPanZoom`.
    `MermaidLightboxFallback` renders the defensive parse-error and
    source-code panel for the modal's non-`hasDiagram` branch,
    mirroring the inline fallback shape so the "graceful source
    fallback" invariant from `mermaid-rendering.mdc` holds across
    both presentation surfaces; the extraction also keeps
    `MermaidLightboxModal` itself under the 250-line decomposition
    cap.
  - `chat-list/` &mdash; the list page split into `ChatList`,
    `SearchBar`, `EmptyState`, `ProjectGroup`, `ChatCard`.
  - `chat-detail/` &mdash; the detail page split into `ChatDetail`,
    `ChatMetaPanel`, `MessageList`, `MessageBubble`,
    `MessageImageGallery` (renders attached-image thumbnails via
    `GET /api/chat/:id/image/:uuid`), and its sibling
    `ImageLightboxModal` (the full-size modal the gallery opens on
    thumbnail click, with prev/next chevrons, counter, thumbnail
    strip, and keyboard navigation). The mermaid `MermaidLightboxModal`
    above follows the same lightbox pattern (viewport-fixed Paper,
    toolbar actions, theme-token styling) for diagram embeds inside
    these bubbles. `ChatDetail` delegates its scroll save/restore
    to `useChatScrollAnchor` (under `hooks/`), which persists an
    anchor-based `{ msgIdx, offset }` JSON entry to
    `sessionStorage` keyed off the topmost in-viewport bubble's
    `data-msg-idx` attribute (set by `MessageList.map`'s
    `(message, index)` enumeration on `MessageBubble`'s outermost
    `<Box>`). Three load-bearing pieces make the restore precise
    on diagram-heavy chats: the `data-msg-idx` SAVE that anchors
    to a specific bubble (raw `window.scrollY` would be layout-
    dependent and drift the moment any layout-shifting placeholder
    lands above the anchor between save and restore); the
    persisted-height layer (`useMermaidBlockHeight` +
    `mermaidHeightCache`) that gives every off-screen
    `MermaidBlock` an accurate `containIntrinsicSize` so the
    layout above the anchor is deterministic before the first
    `scrollTo` runs; and the rAF chase loop with stable-frames
    convergence as the safety net for the residual unmeasured-
    block case. The persisted-height layer is the primary
    determinism mechanism &mdash; without it, the rAF loop is
    racing the browser's `content-visibility: auto` evaluator
    between paints on every refresh of a diagram-heavy chat, a
    cascade that frequently exceeded the original 5-frame cap
    and produced the "sometimes lands exact, sometimes off"
    symptom retired in
    [`known-bugs.mdc`](../.cursor/rules/known-bugs.mdc). See the
    "Two CSS containment hints" subsection of
    [`theme-transitions.mdc`](../.cursor/rules/theme-transitions.mdc)
    for the SAVE side (the `data-msg-idx` bullet), the persisted-
    `containIntrinsicSize` bullet, and the stable-frames RESTORE
    paragraph.
  - `export/` &mdash; shared `ExportFormatDialog` and
    `ExportWarningDialog` used by both pages.

## Assets and configuration

- `cursor-view.spec` &mdash; PyInstaller spec that bundles
  `cursor_view_main.py` and `frontend/build/` into two side-by-side
  binaries (`cursor-view`, `console=True`; `cursor-view-desktop`,
  `console=False`) sharing one `Analysis` / `PYZ` / `COLLECT` runtime
  tree. The split exists so Windows desktop-mode launches do not pop
  a console window for stdout; on macOS and Linux the `console`
  setting has no user-visible effect.
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

This produces a single `dist/cursor-view/` tree containing two
side-by-side binaries that share one bundled Python runtime:

- `cursor-view` &mdash; original console-bearing binary (`console=True`
  in the spec). On Windows, launching it always shows a console window
  for stdout, even with `--desktop`.
- `cursor-view-desktop` &mdash; windowless variant (`console=False`).
  On Windows this is the binary desktop-mode users should launch
  because it never pops a console window. On macOS and Linux the
  `console` setting has no user-visible effect, so the two binaries
  are functionally identical there.

The macOS `BUNDLE` block wraps `cursor-view-desktop`
(`CFBundleExecutable: 'cursor-view-desktop'` in the spec's
`info_plist`), so the `.app` ships the windowless variant by default.

Per-OS output:

- Windows: `dist/cursor-view/cursor-view.exe`,
  `dist/cursor-view/cursor-view-desktop.exe`
- macOS:   `dist/cursor-view/cursor-view`,
  `dist/cursor-view/cursor-view-desktop`,
  plus `dist/Cursor View.app` wrapping `cursor-view-desktop`
- Linux:   `dist/cursor-view/cursor-view`,
  `dist/cursor-view/cursor-view-desktop`

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
