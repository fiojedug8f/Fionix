# -*- mode: python ; coding: utf-8 -*-
"""Per-user installer: wraps the built Fionix.exe (no admin rights required).

    pyinstaller Fionix.spec --distpath release-onefile
    pyinstaller Fionix_Setup.spec --distpath release-installer

``release-onefile/Fionix.exe`` must exist beforehand — the stub copies it into
``%LOCALAPPDATA%\\Programs\\Fionix`` and creates the desktop/start-menu
shortcuts (see ``tools/installer_stub.py``).
"""

from pathlib import Path

ROOT = Path(SPECPATH)
payload = ROOT / "release-onefile" / "Fionix.exe"
if not payload.is_file():
    raise SystemExit(
        "Сначала соберите release-onefile/Fionix.exe (pyinstaller Fionix.spec)."
    )

manifest = ROOT / "assets" / "fionix.manifest"

a = Analysis(
    ["tools/installer_stub.py"],
    pathex=[],
    binaries=[],
    datas=[(str(payload), ".")],
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name="Fionix_Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/icons/fionix.ico"],
    **({"manifest": str(manifest)} if manifest.is_file() else {}),
)
