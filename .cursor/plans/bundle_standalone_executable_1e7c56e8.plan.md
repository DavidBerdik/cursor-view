---
name: Bundle Standalone Executable
overview: Bundle the Cursor View Flask+React application into a single standalone executable using PyInstaller, requiring modifications to `server.py` for frozen-environment path resolution, a PyInstaller spec file, and a build script to automate the process.
todos:
  - id: modify-server
    content: Modify `server.py` to resolve static folder path relative to `sys._MEIPASS` when running frozen
    status: completed
  - id: create-spec
    content: Create `cursor-view.spec` PyInstaller spec file with data files and onefile configuration
    status: completed
  - id: create-build-script
    content: Create build script(s) to automate frontend build + PyInstaller packaging
    status: completed
  - id: test-build
    content: Run the build and verify the standalone executable works
    status: completed
isProject: false
---

# Bundle Cursor View as a Standalone Executable

## Approach

Use **PyInstaller** to bundle the Python backend, all dependencies, and the pre-built React frontend into a single executable. PyInstaller embeds a Python interpreter, all imported packages, and any specified data files into one binary. The user runs the executable, which starts the Flask server, and then opens `localhost:5000` in a browser.

## Changes Required

### 1. Modify `server.py` to support frozen environments

When PyInstaller bundles an app, it extracts files to a temporary directory at runtime. The path to this directory is available via `sys._MEIPASS`. The static folder path must be resolved relative to this base path instead of the script's location.

In [server.py](server.py), change the Flask app initialization (line 27):

```python
# Current
app = Flask(__name__, static_folder='frontend/build')

# New
import sys

def _get_base_path():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

_BASE_PATH = _get_base_path()
app = Flask(__name__, static_folder=os.path.join(_BASE_PATH, 'frontend', 'build'))
```

`sys` is already imported in stdlib usage but needs to be added to the imports. The `getattr(sys, 'frozen', False)` check is the standard way to detect whether the app is running inside a PyInstaller bundle.

### 2. Add PyInstaller dependency

Add `pyinstaller` to a new dev/build dependency or document it as a build-time requirement. It does **not** need to be in `requirements.txt` (it is not a runtime dependency).

### 3. Create a PyInstaller spec file

Create a `cursor-view.spec` file at the project root for reproducible builds. The spec file will:

- Set `server.py` as the entry point
- Include `frontend/build/` as bundled data files (mapped to `frontend/build` inside the bundle)
- Use `--onefile` mode to produce a single executable
- Name the output `cursor-view` (or `cursor-view.exe` on Windows)

Key spec file configuration:

```python
a = Analysis(['server.py'], datas=[('frontend/build', 'frontend/build')])
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name='cursor-view', console=True, onefile=True)
```

### 4. Create a build script

Create a `build.sh` (and/or `build.ps1` for Windows) script that automates the full process:

1. Install frontend dependencies: `npm install` (in `frontend/`)
2. Build the React app: `npm run build` (in `frontend/`)
3. Run PyInstaller: `pyinstaller cursor-view.spec`
4. Output the executable to `dist/cursor-view`

### 5. Optional: Auto-open browser on startup

Currently the user must manually navigate to `localhost:5000`. For a standalone app, it would be a nice UX improvement to auto-open the default browser using `webbrowser.open()` after the Flask server starts. This is optional but worth considering.

## Platform Considerations

- PyInstaller produces a **platform-specific** binary. A Windows build creates a `.exe`, a macOS build creates a macOS binary, etc. Cross-compilation is not supported -- each platform must build its own executable.
- The `datas` path separator differs by OS: `;` on Windows, `:` on macOS/Linux. The `.spec` file approach avoids this issue since it uses Python tuples.
- The app already handles OS-specific Cursor data paths (lines 33-39 in `server.py`), so no changes are needed there.

## Output

The final executable (`dist/cursor-view` or `dist/cursor-view.exe`) will be fully self-contained. The user runs it, it starts a local Flask server, and they visit `http://localhost:5000` in their browser to use the app. No Python, Node.js, or any other runtime needs to be installed.
