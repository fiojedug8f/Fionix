"""Tiny per-user Fionix installer used to build Fionix_Setup.exe.

The launcher executable is embedded as a PyInstaller data file; no admin rights
are required, and no absolute developer paths are used.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog


def desktop_dir() -> Path:
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0, None, 0, buf)
    return Path(buf.value) if buf.value else Path.home() / "Desktop"


def install() -> Path | None:
    app = QApplication(sys.argv)
    answer = QMessageBox.question(
        None,
        "Fionix Setup",
        "Установить Fionix для текущего пользователя?\n\n"
        "Права администратора не требуются.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Yes,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return None
    bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "Fionix.exe"
    if not bundled.is_file():
        QMessageBox.critical(None, "Fionix Setup", "Fionix.exe не найден в установщике.")
        return None
    local = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / "Fionix"
    local.mkdir(parents=True, exist_ok=True)
    target = local / "Fionix.exe"
    progress = QProgressDialog("Установка Fionix…", None, 0, 0)
    progress.setWindowTitle("Fionix Setup")
    progress.show()
    app.processEvents()
    try:
        shutil.copy2(bundled, target)
        app_name = "Fionix"
        desktop = desktop_dir() / f"{app_name}.lnk"
        start_menu = (
            Path(os.environ["APPDATA"])
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Fionix"
        )
        start_menu.mkdir(parents=True, exist_ok=True)
        start_link = start_menu / "Fionix.lnk"
        script = (
            "$w=New-Object -ComObject WScript.Shell;"
            f"$s=$w.CreateShortcut('{desktop}');$s.TargetPath='{target}';$s.Save();"
            f"$s=$w.CreateShortcut('{start_link}');$s.TargetPath='{target}';$s.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        progress.close()
        QMessageBox.critical(None, "Fionix Setup", f"Не удалось установить Fionix:\n{exc}")
        return None
    progress.close()
    QMessageBox.information(
        None,
        "Fionix Setup",
        "Fionix установлен.\nЯрлык создан на рабочем столе.",
    )
    subprocess.Popen([str(target)], close_fds=True)
    return target


if __name__ == "__main__":
    install()
