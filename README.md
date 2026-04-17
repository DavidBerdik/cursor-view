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
- `chat_index.py` &mdash; persistent SQLite cache of chat summaries
  plus FTS search.
- `chat_format.py` &mdash; shapes extracted chat data for the frontend.
- `terminal.py`, `__main__.py` &mdash; terminal-mode entry point and
  the `python -m cursor_view` dispatcher.
- `cleanup.py`, `paths.py`, `timestamps.py` &mdash; small cross-cutting
  utilities.

Subpackages:

- `extraction/` &mdash; pipeline that scans Cursor's SQLite databases
  and produces chat sessions. `core.py` holds the orchestrator and the
  per-pass helpers; `diagnostics.py` holds the optional probe gated by
  the `CURSOR_CHAT_DIAGNOSTICS` environment variable.
- `export/` &mdash; chat export generators: `themes.py` (palette),
  `markdown.py` (`.md`), `markdown_fences.py` (Cursor fence
  normalization), `html.py` (standalone HTML + inline CSS template).
- `projects/` &mdash; project-name resolution. `inference.py` walks
  workspace storage, tree view state, and history entries;
  `git.py` is the SCM (git repo) fallback.
- `sources/` &mdash; raw access to Cursor's on-disk data.
  `sqlite_data.py` holds the iterators over `cursorDiskKV` and
  `ItemTable`.
- `desktop/` &mdash; pywebview launcher. `__init__.py` hosts
  `run_desktop`; `api.py` is the JS &harr; Python bridge;
  `window_state.py` persists window geometry across launches.

### Frontend (`frontend/src/`)

- `App.js`, `index.js`, `index.css`, `starry-night-theme.css` &mdash;
  root composition and global CSS.
- `theme/` &mdash; `colors.js` (palettes), `buildTheme.js` (MUI theme
  factory), `themeCookie.js` (dark/light cookie).
- `contexts/` &mdash; `ColorContext.js` and `ThemeModeContext.js`, one
  React context per file.
- `hooks/` &mdash; shared custom hooks: `useChatSummaries`,
  `useExportFlow`, `useExportWarningPreference`.
- `utils/` &mdash; pure helpers: `formatDate`, `dbPath`, `cookies`,
  `exportChat`.
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
