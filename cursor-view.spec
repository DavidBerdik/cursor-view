# -*- mode: python ; coding: utf-8 -*-
import sys

ICON = {
    "win32": "assets/icons/cursor-view.ico",
    "darwin": "assets/icons/cursor-view.icns",
}.get(sys.platform, "assets/icons/cursor-view.png")

a = Analysis(
    ['cursor_view_main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('frontend/build', 'frontend/build'),
        # Vendored mermaid.min.js read by cursor_view.export.mermaid via
        # importlib.resources at HTML export time. Must ship alongside the
        # binary so exports work without a Node toolchain or network access.
        ('cursor_view/export/vendor/mermaid.min.js', 'cursor_view/export/vendor'),
        ('cursor_view/export/vendor/VERSION.txt', 'cursor_view/export/vendor'),
    ],
    hiddenimports=[
        'webview.platforms.winforms',
        'webview.platforms.cocoa',
        'webview.platforms.qt',
        'webview.platforms.gtk',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

# Two thin EXE entry points share a single Analysis / PYZ / runtime tree.
# The split exists to fix the "this feels unprofessional" issue on Windows
# where the console-bearing binary (console=True) pops a console window
# even when --desktop is passed: the second windowless binary
# (console=False) is the one Windows users should launch for the desktop
# UI. exclude_binaries=True on each EXE moves the shared bootloader /
# Python runtime / `datas` / `binaries` into the single COLLECT() below
# instead of duplicating them per EXE, keeping dist/ at one runtime tree
# with two ~MB-scale launchers next to it. On macOS and Linux the
# `console` setting has no Windows-style "pops a console window" effect,
# but each platform's bootloader still differs slightly between the two
# variants -- the split is harmless on those platforms and lets the
# macOS BUNDLE below wrap the windowless variant verbatim.
exe_terminal = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='cursor-view',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon=ICON,
)

exe_desktop = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='cursor-view-desktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=ICON,
)

coll = COLLECT(
    exe_terminal,
    exe_desktop,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='cursor-view',
)

if sys.platform == 'darwin':
    # The macOS .app wraps the *windowless* cursor-view-desktop binary
    # (CFBundleExecutable below) so the bundle aligns with the binary that
    # is intended for double-click launches. Until Improvement 21 flips the
    # CLI default, cursor_view/__main__.py still defaults to terminal mode
    # on either binary, so double-clicking the .app today starts the Flask
    # server and opens the browser, exactly as before. The experimental
    # webview UI still requires --desktop, e.g.:
    #     open -a "Cursor View" --args --desktop
    # After Improvement 21, the same .app will default to the webview UI
    # without any spec change, because the bundled binary is already the
    # windowless variant.
    app = BUNDLE(
        coll,
        name='Cursor View.app',
        icon=ICON,
        bundle_identifier='dev.cursor-view.app',
        info_plist={
            'CFBundleExecutable': 'cursor-view-desktop',
            'CFBundleName': 'Cursor View',
            'CFBundleDisplayName': 'Cursor View',
            'CFBundleShortVersionString': '0.1.0',
            # Keep LSUIElement False so that --desktop mode (the only case
            # the .app shows a window) gets a proper Dock entry. In default
            # terminal mode the .app will briefly show a Dock icon for a
            # windowless process; flipping this to True would also hide
            # the desktop window from the Dock, which is worse.
            'LSUIElement': False,
            'NSHighResolutionCapable': True,
        },
    )
