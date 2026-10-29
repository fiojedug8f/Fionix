# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a portable one-file Fionix build.

    pip install -r requirements.txt pyinstaller
    pyinstaller Fionix.spec
    .\\dist\\Fionix.exe

Optional bits are picked up automatically when present:

* ``.deps/`` — a local ``pip install --target .deps`` bundle (offline builds);
* ``curl_cffi`` / ``keyboard`` / ``pywin32`` — bundled when installed;
* ``assets/fionix.manifest`` — Windows DPI/manifest, added when the file exists.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)
DEPS = ROOT / ".deps"

datas = [("assets", "assets")]
binaries = []
hiddenimports = []

# Local dependency bundle (offline builds): .deps/<package>
for name, target in (
    ("curl_cffi.libs", "curl_cffi.libs"),
    ("win32", "win32"),
    ("pywin32_system32", "pywin32_system32"),
):
    folder = DEPS / name
    if folder.is_dir():
        datas.append((str(folder), target))

pathex = []
if (DEPS / "win32").is_dir():
    pathex = [str(DEPS / "win32"), str(DEPS / "win32" / "lib")]
    hiddenimports += ["win32gui", "win32con", "win32process"]

for package in ("curl_cffi", "keyboard"):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception:  # package is optional
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

manifest = ROOT / "assets" / "fionix.manifest"

a = Analysis(
    ["main.py"],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name="Fionix",
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
