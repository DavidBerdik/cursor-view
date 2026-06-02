<div align="center">

# Cursor View

Cursor View is a local tool to view, search, and export all your Cursor AI chat histories in one place. It works by scanning your local Cursor application data directories and extracting chat data from the SQLite databases.

**Privacy Note**: All data processing happens locally on your machine. No data is sent to any external servers.

<img width="500" alt="cursor-view Dark Mode" src=".github/readme-imgs/screenshot-dark-mode.png" /> <img width="500" alt="cursor-view Light Mode" src=".github/readme-imgs/screenshot-light-mode.png" />

</div>

_Contributing to Cursor View? See [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) for the project layout map, the build-from-source PyInstaller instructions, and how to run the test suite._

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

## Standalone binary

Cursor View can also be packaged as a standalone binary so it can be run
without a Python toolchain. By default the binary behaves the same way as
`python3 terminal.py`: it starts a local Flask server and opens the chat UI
in your default browser. Passing `--desktop` opts into an experimental
mode where the UI is rendered inside a native OS webview window (WebView2
on Windows, WKWebView on macOS, WebKitGTK/Qt on Linux) via
[pywebview](https://pywebview.flowrl.com/).

**Local-process security boundary.** In `--desktop` mode the local API is
protected by a per-launch secret token: the webview sends it on every
request, and any other process on your machine that connects to the
loopback port without it gets a `401`. This narrows the exposure of your
chat data to the desktop window itself. Terminal/browser mode is
unchanged &mdash; it serves the API to your browser without this token,
exactly as before, so treat the terminal-mode server as accessible to any
local process (the same as any local dev server).

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

### Running the binary

The build ships two executables side-by-side in `dist/cursor-view/` that
share a single bundled Python runtime:

- `cursor-view` &mdash; the original console-bearing binary. On Windows,
  launching it always shows a Windows console window for stdout, even
  with `--desktop`.
- `cursor-view-desktop` &mdash; a windowless variant intended for
  desktop-mode launches. On Windows it never shows the console window,
  which is the only practical difference; on macOS and Linux the
  `console` setting has no user-visible effect, so the two binaries
  behave identically there.

Both binaries accept the same flags (`__main__.py` still defaults to
terminal mode for either binary; you opt into the webview UI by passing
`--desktop`):

```
cursor-view                          # terminal/server mode + auto-open browser
cursor-view --no-browser             # server only; open the browser yourself
cursor-view --port 8080              # use a different port
cursor-view --desktop                # webview UI (Windows: console window shows up)
cursor-view-desktop --desktop        # webview UI with no Windows console window
```

In `--desktop` mode the window carries a native File / Edit / View / Help
menu bar (Reload, Quit, clipboard edit commands, Toggle Theme, plus
Documentation / GitHub links that open in your default browser). On
backends without native menu support (notably some Linux WebKitGTK
builds) the menu is omitted and every action remains reachable from the
in-app UI.

On macOS the `.app` bundle wraps the windowless `cursor-view-desktop`
binary (the two binaries are functionally identical on macOS), so
double-clicking `Cursor View.app` in Finder still starts the Flask
server and opens the browser today. Finder shows it under the
"Developer Tools" category, and in desktop mode its window chrome
follows the system light/dark appearance. To launch the experimental
desktop mode from Finder, pass the flag explicitly:

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

Desktop mode also writes a rotating log file to `logs/desktop.log`
(1&nbsp;MB cap, 3 backups) in the same `cursor-view` cache directory
(e.g. `%LOCALAPPDATA%\cursor-view\logs\desktop.log` on Windows,
`~/Library/Caches/cursor-view/logs/desktop.log` on macOS,
`$XDG_CACHE_HOME/cursor-view/logs/desktop.log` on Linux). This is the
first place to look &mdash; and the file to attach to a bug report
&mdash; when the desktop app misbehaves, since the windowless Windows
binary has no console to print to.

Desktop mode is single-instance: launching `--desktop` while it is
already running focuses the existing window instead of opening a second
one. It tracks the running instance with a `desktop.lock` file in the
same cache directory (next to `webview-storage/`); the file is removed
on exit and a stale lock left by a crash is reclaimed automatically on
the next launch.

## Features

- Browse all Cursor chat sessions
- Search through chat history (queries also match Cursor-assigned chat titles)
- Export chats as HTML, JSON, or Markdown
- Organize chats by project
- View timestamps of conversations
- View Cursor-assigned chat titles inline in the card grid, the chat-detail header, and the Markdown / HTML / JSON exports; untitled chats fall back to the existing project-based heading
- Render mermaid diagrams inline in the chat view, with a full-size modal on click of the diagram body or the expand icon (initial fit-to-viewport, drag-to-pan, wheel/button zoom, reset-to-fit, close button + ESC / backdrop dismissal); HTML exports also render the diagrams inline
- View image attachments inline in the chat, with a full-size modal on click (prev/next chevrons + keyboard navigation when a message has multiple images); HTML exports keep the same images clickable and open them in a new browser tab
- Smooth dark/light theme fade across the entire UI (page background, cards, chat bubbles, code blocks, mermaid diagrams) instead of a single-frame flash on toggle
- Respects the system-wide `prefers-reduced-motion` accessibility preference: when set, theme toggles, hover transitions, and the mermaid diagram cross-fade all become instant

## Troubleshooting

### A chat shows up under "(unknown)" / "(global)"

The home page groups chats by project. Most chats inherit a project
from the workspace they were started in, but the occasional chat
&mdash; usually a `task-<toolCallId>` subagent spawned by another
chat &mdash; can land on the literal sentinel triple `Project:
(unknown)`, `Path: (unknown)`, `Workspace: (global)`. There are
four distinct root causes, and a built-in CLI diagnostic classifies
which one is firing for any specific chat. Run it against the
chat's session id (visible in the chat-detail URL after `/chat/`):

```
python3 -m cursor_view.extraction.diagnostics --cid task-toolu_xxxxxxxxxxxxxxxxxxxx
```

The diagnostic opens your Cursor source databases and the local
chat-index cache **read-only** (it never modifies any file) and
prints a one-line classification mapping the symptom to one of
four documented causes (orphan-filter drop, scoped-mode walk gap,
dead-chain top, deleted parent). After running a refresh through
the Refresh button or with `cursor-view --no-browser` and reopening
the chat, the same diagnostic is the fastest way to confirm the
fix took effect. Pass `--json` to get the raw trace dict if you
need to file an issue with the full evidence trail.

_Originally built by [Sahar Mor](https://www.linkedin.com/in/sahar-mor/)._
