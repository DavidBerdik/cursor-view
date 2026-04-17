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
    datas=[('frontend/build', 'frontend/build')],
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
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

if sys.platform == 'darwin':
    # The .app bundle is purely cosmetic packaging around the same
    # terminal-first ``cursor-view`` binary. Double-clicking the .app starts
    # the Flask server and opens the browser, mirroring how the Windows
    # .exe behaves. The experimental webview UI requires --desktop, e.g.:
    #     open -a "Cursor View" --args --desktop
    app = BUNDLE(
        exe,
        name='Cursor View.app',
        icon=ICON,
        bundle_identifier='dev.cursor-view.app',
        info_plist={
            'CFBundleExecutable': 'cursor-view',
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
