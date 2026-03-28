# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for HeroQuest.
Run from the repo root:  pyinstaller hq.spec
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH)  # repo root

a = Analysis(
    [str(ROOT / "src" / "main.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        # (source, dest-folder-inside-bundle)
        (str(ROOT / "assets"),  "assets"),
        (str(ROOT / "data"),    "data"),
        (str(ROOT / "src" / "config.json"), "."),
    ],
    hiddenimports=["pygame"],
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
    name="HeroQuest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # no console window
    # icon="assets/graphics/ui/icon.ico",   # uncomment if you have an .ico
    onefile=True,
)
