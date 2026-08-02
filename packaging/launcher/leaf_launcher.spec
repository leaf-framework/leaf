# -*- mode: python ; coding: utf-8 -*-
#
# Freezes ONLY packaging/launcher/bootstrap.py into a small native
# LEAF.exe / LEAF.app. It intentionally does NOT bundle leaf/nicegui/adapters
# -- those get pip-installed at first run into a real venv by bootstrap.py.
# See packaging/README.md for the full rationale.
#
# Build (run from repo root):
#   pyinstaller packaging/launcher/leaf_launcher.spec --distpath dist --workpath build/launcher
import sys
from pathlib import Path

repo_root = Path(SPECPATH).resolve().parents[1]

if sys.platform == "darwin":
    icon = str(repo_root / "leaf" / "ui" / "images" / "icon.icns")
elif sys.platform == "win32":
    icon = str(repo_root / "leaf" / "ui" / "images" / "icon.ico")
else:
    icon = None

a = Analysis(
    [str(repo_root / "packaging" / "launcher" / "bootstrap.py")],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["tkinter"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LEAF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LEAF",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="LEAF.app",
        icon=icon,
        bundle_identifier="nl.systemsbiology.leaf",
    )
