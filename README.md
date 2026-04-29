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
- Search through chat history (queries also match Cursor-assigned chat titles)
- Export chats as HTML, JSON, or Markdown
- Organize chats by project
- View timestamps of conversations
- View Cursor-assigned chat titles inline in the card grid, the chat-detail header, and the Markdown / HTML / JSON exports; untitled chats fall back to the existing project-based heading
- Render mermaid diagrams inline in the chat view and in HTML exports
- View image attachments inline in the chat, with a full-size modal on click (prev/next chevrons + keyboard navigation when a message has multiple images); HTML exports keep the same images clickable and open them in a new browser tab

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
