#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Installing Python build dependencies ==="
pip install pyinstaller

echo "=== Installing frontend dependencies ==="
cd frontend
npm install

echo "=== Building React frontend ==="
npm run build
cd "$SCRIPT_DIR"

echo "=== Packaging with PyInstaller ==="
pyinstaller --clean --noconfirm cursor-view.spec

echo ""
echo "=== Build complete ==="
echo "Executable: dist/cursor-view"
