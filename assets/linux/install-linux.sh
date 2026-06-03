#!/usr/bin/env bash
#
# Installs the Cursor View .desktop launcher and icon into the current
# user's XDG data dir so the desktop-mode binary shows up in the
# application menu. This is a per-user install (no root required); it
# writes only under $XDG_DATA_HOME (default ~/.local/share).
#
# Usage:
#   assets/linux/install-linux.sh [PATH_TO_cursor-view-desktop]
#
# With no argument the script looks for the binary the PyInstaller spec
# produces. On Linux that is the self-contained --onefile binary at
# <repo>/dist/cursor-view-desktop. Pass an explicit path if you installed
# the binary elsewhere.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

BINARY="${1:-$REPO_ROOT/dist/cursor-view-desktop}"

if [ ! -x "$BINARY" ]; then
    echo "error: cursor-view-desktop binary not found or not executable:" >&2
    echo "  $BINARY" >&2
    echo >&2
    echo "Build it first with 'pyinstaller cursor-view.spec', or pass the" >&2
    echo "path to the binary explicitly:" >&2
    echo "  $0 /path/to/cursor-view-desktop" >&2
    exit 1
fi

# Normalize to an absolute path so the .desktop Exec= line works no
# matter which directory the launcher is invoked from.
BINARY="$(cd "$(dirname "$BINARY")" && pwd)/$(basename "$BINARY")"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/512x512/apps"

mkdir -p "$APP_DIR" "$ICON_DIR"

install -m 644 "$REPO_ROOT/assets/icons/cursor-view.png" \
    "$ICON_DIR/cursor-view.png"

# Substitute the resolved binary path into the template. '|' is the sed
# delimiter because filesystem paths never contain it but routinely
# contain '/'.
DESKTOP_DEST="$APP_DIR/cursor-view.desktop"
sed "s|@EXEC@|$BINARY|g" "$SCRIPT_DIR/cursor-view.desktop" > "$DESKTOP_DEST"
chmod 644 "$DESKTOP_DEST"

# Refresh the menu and icon caches when the tools are present; both are
# best-effort, so a missing tool or a cache-rebuild hiccup must not fail
# an otherwise-successful install.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Installed Cursor View desktop integration:"
echo "  launcher: $DESKTOP_DEST"
echo "  icon:     $ICON_DIR/cursor-view.png"
echo "  exec:     $BINARY --desktop"
echo
echo "Cursor View should now appear in your application menu. If it does"
echo "not, log out and back in (or restart your desktop shell) to pick up"
echo "the new entry."
