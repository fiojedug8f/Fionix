"""Offscreen integration smoke test for the Fionix UI.

It does not touch the network: version and progress dialogs are opened in
preview mode and the game process is replaced by a short Python sleep.  Real
Minecraft installation and Java download logic are covered by the core tests
and the live developer check documented in the README.
"""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("FIONIX_SKIP_WELCOME", "1")
os.environ.setdefault("FIONIX_SKIP_UPDATE", "1")
if sys.platform == "win32":
    windows_dir = os.environ.get("WINDIR", r"C:\Windows")
    os.environ.setdefault("QT_QPA_FONTDIR", str(Path(windows_dir) / "Fonts"))

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

from src.app import create_application  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402

from src.core.accounts import create_guest  # noqa: E402
from src.core.config_manager import ConfigManager  # noqa: E402
from src.core.launcher import GameSession, Instance, JavaRuntime  # noqa: E402
from src.core.theme import build_stylesheet, current_theme, set_theme  # noqa: E402
from src.ui.crash_dialog import CrashDialog  # noqa: E402
from src.ui.instance_dialogs import (  # noqa: E402
    ContentManagerDialog,
    InstanceSettingsDialog,
)
from src.ui.launch_dialogs import CreateInstanceDialog, InstallProgressDialog  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402


def settle(milliseconds: int = 250) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def main() -> int:
    temp_root = ROOT / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_dir = temp_root / f"smoke-{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        app = create_application(["fionix-smoke"])
        app.setStyleSheet(build_stylesheet(set_theme("dark")))
        config = ConfigManager(temp_dir)

        instance_dir = config.instances_dir / "Vanilla_1.20.1"
        instance_dir.mkdir(parents=True)
        instance = Instance(
            path=instance_dir,
            version="1.20.1",
            name="Vanilla 1.20.1",
            created_at="2026-10-20T14:20:00",
            java_major=17,
            playtime_seconds=3600,
            last_played_at="2026-10-23T21:15:00",
        )
        instance.save()

        fabric_dir = config.instances_dir / "Fabric_1.20.1"
        fabric_dir.mkdir(parents=True)
        for folder in ("mods", "config", "resourcepacks", "shaderpacks", "saves"):
            (fabric_dir / folder).mkdir()
        (fabric_dir / "mods" / "cool-mod.jar").write_bytes(b"x" * 512)
        fabric_instance = Instance(
            path=fabric_dir,
            version="1.20.1",
            name="Fabric 1.20.1",
            created_at="2026-10-21T14:20:00",
            java_major=17,
            playtime_seconds=120,
            loader="fabric",
            loader_version="0.16.14",
            launch_version="fabric-loader-0.16.14-1.20.1",
            memory_mb=6144,
        )
        fabric_instance.save()

        window = MainWindow(config)
        window.resize(1440, 900)
        window.show()
        settle(400)

        # Instance cards and sidebar list.
        assert len(window._instances) == 2
        assert window.sidebar.count_label.text() == "2"
        assert window.home_page.section_count.text() == "2"

        # Navigation + page fade.
        for page in ("settings", "home"):
            window.navigate(page, persist=False, animate=True)
            settle(260)
        window.store_page._loaded = True
        window.navigate("store", persist=False, animate=False)
        settle(120)
        assert window.stack.currentWidget() is window.store_page

        # F11 clears rounded corners and restores them on exit.
        window._toggle_fullscreen()
        settle(150)
        assert window.isFullScreen()
        assert window.shell._radius == 0
        window._toggle_fullscreen()
        settle(150)
        assert not window.isFullScreen()
        assert window.shell._radius == 20

        # Theme switch through the real settings control.
        window.navigate("settings", persist=False, animate=False)
        settle(120)
        midnight_index = window.settings_page.theme_combo.findData("midnight")
        window.settings_page.theme_combo.setCurrentIndex(midnight_index)
        settle(250)
        assert config.theme == "midnight", "theme was not persisted"
        assert current_theme().key == "midnight", "theme was not applied"

        # Persisted controls: debounced RAM slider + proxy toggle.
        window.settings_page.memory_slider.setValue(6144)
        settle(500)
        assert config.memory_mb == 6144, "memory setting was not persisted"
        window.settings_page.proxy_toggle.click()
        settle(300)
        assert config.get("proxy")["enabled"] is True, "proxy toggle was not persisted"

        # Hover animations must actually advance their custom properties.
        window.home_page.create_button._animate_hover(1.0)
        settle(240)
        assert window.home_page.create_button.hoverProgress > 0.9

        dark_index = window.settings_page.theme_combo.findData("dark")
        window.settings_page.theme_combo.setCurrentIndex(dark_index)
        window.navigate("home", persist=False, animate=False)
        settle(250)

        # Open the instance and return to the library.
        window._open_instance(instance)
        settle(250)
        assert window._current_instance is not None
        assert window.instance_page.title_label.text() == "Vanilla 1.20.1"
        window.instance_page.back_requested.emit()
        settle(220)

        # Content manager: toggle a mod and verify the rename + live count.
        window._open_instance(fabric_instance)
        settle(220)
        assert window.instance_page.title_label.text() == "Fabric 1.20.1"
        assert window.instance_page.content_tiles["mods"].count_label.text() == "1"
        content_dialog = ContentManagerDialog(
            window.launcher, fabric_instance, "mods", window
        )
        content_dialog.show()
        settle(180)
        assert len(content_dialog._rows) == 1
        content_dialog._rows[0].toggle.click()
        settle(180)
        assert (fabric_dir / "mods" / "cool-mod.jar.disabled").is_file()
        content_dialog._rows[0].toggle.click()
        settle(180)
        assert (fabric_dir / "mods" / "cool-mod.jar").is_file()
        content_dialog.reject()
        settle(100)

        # Per-instance settings persist RAM and are applied to the page.
        settings_dialog = InstanceSettingsDialog(
            window.launcher, fabric_instance, config.memory_mb, window
        )
        settings_dialog.show()
        settle(120)
        settings_dialog.memory_slider.setValue(8192)
        settings_dialog._save()
        settle(120)
        assert Instance.load(fabric_dir).memory_mb == 8192
        window._open_instance(Instance.load(fabric_dir), animate=False)
        settle(100)
        assert "8 ГБ" in window.instance_page.memory_chip.value_label.text()

        # Create dialog offers all six cores and the optimization checkbox.
        create_dialog = CreateInstanceDialog(window.launcher, window, auto_fetch=False)
        create_dialog.show()
        settle(150)
        assert set(create_dialog._core_tiles) == {
            "vanilla",
            "forge",
            "neoforge",
            "fabric",
            "quilt",
            "optifine",
        }
        create_dialog._core_tiles["fabric"].setChecked(True)
        create_dialog._on_core_clicked("fabric")
        assert create_dialog.optimize_checkbox.isEnabled()
        create_dialog.optimize_checkbox.setChecked(True)
        create_dialog._core_tiles["optifine"].setChecked(True)
        create_dialog._on_core_clicked("optifine")
        assert not create_dialog.create_button.isEnabled()
        create_dialog.reject()
        settle(100)

        # Multi-account switching and the first-run guest account.
        assert len(window.accounts.accounts) >= 1
        second = window.accounts.add(create_guest("Alex"))
        window._refresh_accounts_ui()
        assert window.sidebar.account_combo.count() == 2
        window._switch_account(second.id)
        assert window.accounts.current.username == "Alex"
        window._switch_account(window.accounts.accounts[0].id)
        settle(120)

        # Accent colour, custom image background and the QMediaPlayer popover.
        config.update({"accent": "#22c55e"})
        window._on_accent_changed("#22c55e")
        assert current_theme().accent.name() == "#22c55e"
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor("#221144"))
        bg_path = temp_dir / "custom-background.png"
        image.save(str(bg_path))
        config.update({"background": {"mode": "image", "path": str(bg_path)}})
        window._apply_background()
        settle(120)

        # Market page and its CurseForge key placeholder.
        window._open_instance(fabric_instance)
        window._open_market()
        settle(200)
        assert window.stack.currentWidget() is window.market_page
        assert window.market_page.source_combo.findData("curseforge") == -1
        window.market_page._popular_loaded = True
        window.market_page.market_tab.click()
        settle(80)
        assert window.stack.currentWidget() is window.market_page
        window._back_from_market()
        settle(120)

        # Update badge and manual-check presentation.
        from src.core.updater import UpdateInfo

        window._on_update_checked(
            UpdateInfo(True, "1.0.0", "1.2.0", "https://example.invalid"), manual=False
        )
        assert window.title_bar.update_button.isVisible()
        window.title_bar.clear_update()

        # Crash dialog renders the log and exposes the AI helper.
        crash_log = temp_dir / "crash.log"
        crash_log.write_text("java.lang.RuntimeException: boom", encoding="utf-8")
        crash = CrashDialog(
            window,
            title="Minecraft завершился с ошибкой",
            log_path=crash_log,
            exit_code=1,
        )
        assert "boom" in crash.log.toPlainText()
        crash.reject()
        crash.deleteLater()
        settle(80)

        # Progress dialog preview.
        progress = InstallProgressDialog(
            window.launcher, "1.20.1", window, auto_start=False
        )
        progress.show()
        progress.set_preview(57, "Скачивание ресурсов игры", "assets · 12 340 / 21 500")
        settle(160)
        progress.reject()
        settle(100)

        # Music popover.
        window._toggle_music_popover()
        settle(240)
        popover = window._music_popover
        assert popover is not None and popover.isVisible(), "music popover did not open"
        popover.close()
        settle(120)

        # Play flow: replace the real Java/Minecraft process with a short sleep.
        window._open_instance(instance)
        settle(150)
        window._notice = lambda title, message: print(f"NOTICE: {title}: {message}")
        fake_java = JavaRuntime(path=Path("C:/fake/javaw.exe"), major=17, source="Temurin")
        # Force the Java preparation dialog + worker path, but without network.
        window.launcher.managed_java = lambda major: None  # type: ignore[method-assign]

        def fake_ensure_java(major, progress=None, cancel_event=None):
            if progress is not None:
                progress(100, "Java готова", "Eclipse Temurin")
            return fake_java

        window.launcher.ensure_java = fake_ensure_java  # type: ignore[method-assign]

        def fake_session(
            target: Instance, java: JavaRuntime, account=None
        ) -> GameSession:
            return GameSession(
                target,
                [sys.executable, "-c", "import time; time.sleep(2)"],
                java,
                target.path / "logs" / "game-smoke.log",
            )

        window.launcher.create_game_session = fake_session  # type: ignore[method-assign]
        window._play_current()
        assert window._game_session is not None, "game session was not created"
        assert window._hidden_for_game, "launcher was not hidden for the game"
        settle(5000)
        assert window._game_session is None, "game session was not cleaned up"
        assert not window._hidden_for_game, "launcher was not restored"
        saved = Instance.load(instance_dir)
        assert saved.playtime_seconds >= 3602, saved.playtime_seconds
        assert window.isVisible(), "launcher is not visible after game exit"

        assert window.settings_page.theme_combo.currentData() == "dark"
        window.close()
        settle(100)
        print(
            "Smoke test passed: six cores, optimization checkbox, accounts, "
            "market, store, accent/background, crash dialog, music, playtime, restore."
        )
        return 0
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
