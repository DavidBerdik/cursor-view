# -*- mode: python ; coding: utf-8 -*-
import sys

ICON = {
    "win32": "assets/icons/cursor-view.ico",
    "darwin": "assets/icons/cursor-view.icns",
}.get(sys.platform, "assets/icons/cursor-view.png")

a = Analysis(
    ['desktop.py'],
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
    name='Cursor View',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=ICON,
)

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='Cursor View.app',
        icon=ICON,
        bundle_identifier='dev.cursor-view.app',
        info_plist={
            'LSUIElement': False,
            'NSHighResolutionCapable': True,
            'CFBundleShortVersionString': '0.1.0',
        },
    )
