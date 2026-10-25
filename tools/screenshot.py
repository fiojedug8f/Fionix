"""Render deterministic screenshots of the UI without opening a desktop window.

Usage::

    python tools/screenshot.py

Writes PNG files to ``docs/``.  A temporary data directory and mock instances
are used so the developer's real ``%APPDATA%/Fionix`` is untouched.  The tool
does not need network access: the market cards are mocked.
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
# The offscreen platform plugin does not use the Windows font database, so
# point Qt at the system fonts explicitly (otherwise text renders as boxes).
if sys.platform == "win32":
    windows_dir = os.environ.get("WINDIR", r"C:\Windows")
    os.environ.setdefault("QT_QPA_FONTDIR", str(Path(windows_dir) / "Fonts"))

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from src.app import create_application  # noqa: E402
from src.core.config_manager import ConfigManager  # noqa: E402
from src.core.launcher import Instance  # noqa: E402
from src.core.market_api import MarketProject  # noqa: E402
from src.core.theme import build_stylesheet, set_accent_color, set_theme  # noqa: E402
from src.ui.accounts_ui import AccountWelcomeDialog  # noqa: E402
from src.ui.crash_dialog import CrashDialog  # noqa: E402
from src.ui.instance_dialogs import InstanceSettingsDialog  # noqa: E402
from src.ui.launch_dialogs import CreateInstanceDialog, InstallProgressDialog  # noqa: E402
from src.ui.main_window import MainWindow  # noqa: E402
from src.ui.profile_dialog import ProfileDialog  # noqa: E402
from src.ui.skin_viewer import SkinViewerDialog  # noqa: E402


def settle(milliseconds: int = 300) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def composite(background: Path, overlay: Path, target: Path) -> None:
    from PIL import Image

    with Image.open(background) as base, Image.open(overlay) as layer:
        merged = Image.alpha_composite(base.convert("RGBA"), layer.convert("RGBA"))
        merged.convert("RGB").save(target)


def fake_projects() -> list[MarketProject]:
    return [
        MarketProject("AANobbMI", "sodium", "Sodium", "jellysquid3",
                      "A modern rendering engine that greatly improves frame rates.",
                      "", 252_857_104, "modrinth", game_versions=("1.20.1",)),
        MarketProject("PtjYWJkn", "sodium-extra", "Sodium Extra", "FlashyReese",
                      "Features that shouldn't be in Sodium, without changing its style.",
                      "", 106_474_033, "modrinth", game_versions=("1.20.1",)),
        MarketProject("Bh37bMuy", "reeses-sodium-options", "Reese's Sodium Options",
                      "FlashyReese", "Alternative options menu for Sodium.",
                      "", 88_493_776, "modrinth", game_versions=("1.20.1",)),
        MarketProject("P7dR8mSH", "fabric-api", "Fabric API", "modmuss50",
                      "Lightweight and modular API providing common hooks and interoperability.",
                      "", 700_000_000, "modrinth", game_versions=("1.20.1",)),
    ]


def fake_modpacks() -> list[MarketProject]:
    return [
        MarketProject(
            "1KVo5zza", "fabulously-optimized", "Fabulously Optimized",
            "robotkoer", "Beautiful graphics, speedy performance and familiar features.",
            "", 19_267_062, "modrinth", game_versions=("1.20.1",),
        ),
        MarketProject(
            "BMC2", "better-mc-fabric-bmc2", "Better MC [FABRIC] — BMC2",
            "SHXRKIE", "A Proper Vanilla+ Modpack! Don't play Vanilla, play this!",
            "", 3_721_403, "modrinth", game_versions=("1.20.1",),
        ),
        MarketProject(
            "COBBLEVERSE", "cobbleverse", "COBBLEVERSE — Pokemon Adventure",
            "LUMYVERSE", "A true Pokemon adventure with Cobblemon 1.7.3.",
            "", 7_286_422, "modrinth", game_versions=("1.20.1",),
        ),
        MarketProject(
            "VANILLA", "vanilla-perfected", "Vanilla Perfected",
            "demonjoeTV", "A compilation of Vanilla Plus mods & packs.",
            "", 1_021_505, "modrinth", game_versions=("1.20.1",),
        ),
    ]


def main() -> int:
    docs = ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    temp_root = ROOT / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_dir = temp_root / f"shot-{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        config = ConfigManager(temp_dir)
        app = create_application(["fionix-screenshot"])
        set_theme(config.theme)
        set_accent_color(config.accent)
        app.setStyleSheet(build_stylesheet())

        instance_dir = config.data_dir / "instances" / "Fabric_1.20.1"
        instance_dir.mkdir(parents=True)
        for folder in ("mods", "config", "resourcepacks", "shaderpacks", "saves"):
            (instance_dir / folder).mkdir()
        (instance_dir / "mods" / "sodium-fabric-0.5.13+mc1.20.1.jar").write_bytes(
            b"\0" * 971552
        )
        (instance_dir / "mods" / "ferritecore-6.0.1-fabric.jar").write_bytes(
            b"\0" * 120_000
        )
        (instance_dir / "mods" / "old-mod.jar.disabled").write_bytes(b"\0" * 500)
        (instance_dir / "config" / "fabric.cfg").write_text("fps=260", encoding="utf-8")

        instance = Instance(
            path=instance_dir,
            version="1.20.1",
            name="Fabric 1.20.1",
            created_at="2026-10-20T14:20:00",
            java_major=17,
            playtime_seconds=2 * 3600 + 3 * 60,
            last_played_at="2026-10-23T21:15:00",
            loader="fabric",
            loader_version="0.16.14",
            launch_version="fabric-loader-0.16.14-1.20.1",
            memory_mb=6144,
        )
        instance.save()

        window = MainWindow(config)
        window.resize(1440, 900)
        window.show()
        settle(500)

        # A deterministic demo skin so the avatar/profile screenshots show the
        # nearest-neighbour head crop instead of the guest silhouette.
        demo = QImage(64, 64, QImage.Format.Format_ARGB32)
        demo.fill(QColor(0, 0, 0, 0))
        paint = QPainter(demo)
        paint.fillRect(8, 8, 8, 8, QColor("#C89B76"))
        paint.fillRect(9, 11, 2, 2, QColor("#2E2430"))
        paint.fillRect(13, 11, 2, 2, QColor("#2E2430"))
        paint.fillRect(11, 15, 2, 1, QColor("#7C4B3A"))
        paint.fillRect(40, 8, 8, 8, QColor(80, 100, 200, 110))
        paint.fillRect(20, 20, 8, 12, QColor("#2C6C9E"))
        paint.fillRect(20, 36, 8, 12, QColor(20, 40, 80, 120))
        paint.fillRect(44, 20, 4, 12, QColor("#C89B76"))
        paint.fillRect(36, 52, 4, 12, QColor("#C89B76"))
        paint.fillRect(4, 20, 4, 12, QColor("#394B87"))
        paint.fillRect(20, 52, 4, 12, QColor("#394B87"))
        paint.end()
        demo_path = temp_dir / "demo-skin.png"
        demo.save(str(demo_path))
        if window.accounts.current is not None:
            window.accounts.update_skin(window.accounts.current.id, str(demo_path))
            window._refresh_accounts_ui()
            settle(400)

        for key, filename in (
            ("home", "screenshot.png"),
            ("settings", "screenshot-settings.png"),
        ):
            window.navigate(key, persist=False, animate=False)
            settle(280)
            window.grab().save(str(docs / filename), "PNG")
            print(f"Wrote {filename}")

        window._open_instance(instance)
        settle(300)
        window.grab().save(str(docs / "screenshot-instance.png"), "PNG")
        print("Wrote screenshot-instance.png")

        base_path = docs / "_base.png"

        # Create dialog with all six cores and the optimization checkbox.
        window.navigate("home", persist=False, animate=False)
        settle(120)
        window.grab().save(str(base_path), "PNG")
        create_dialog = CreateInstanceDialog(window.launcher, window, auto_fetch=False)
        create_dialog._core_tiles["fabric"].setChecked(True)
        create_dialog._on_core_clicked("fabric")
        create_dialog.optimize_checkbox.setChecked(True)
        create_dialog.versions_combo.setCurrentIndex(
            max(0, create_dialog.versions_combo.findData("1.21.4"))
        )
        create_dialog.show()
        settle(220)
        raw = docs / "_create-raw.png"
        create_dialog.grab().save(str(raw), "PNG")
        create_dialog.reject()
        settle(100)
        composite(base_path, raw, docs / "screenshot-create.png")
        raw.unlink(missing_ok=True)

        # First-run provider chooser.
        welcome = AccountWelcomeDialog(window, first_run=True)
        welcome.show()
        settle(220)
        raw = docs / "_welcome-raw.png"
        welcome.grab().save(str(raw), "PNG")
        welcome.reject()
        settle(100)
        composite(base_path, raw, docs / "screenshot-welcome.png")
        raw.unlink(missing_ok=True)

        # Installed mods and the mock market page.
        window._open_instance(instance)
        settle(180)
        window._open_market()
        settle(220)
        window.grab().save(str(docs / "screenshot-content.png"), "PNG")
        window.market_page._popular_loaded = True
        window.market_page.market_tab.click()
        window.market_page._on_results(fake_projects(), "search")
        window.market_page.market_status.setText("Найдено: 4")
        window.market_page.search_edit.setText("sodium")
        if window.market_page._projects:
            window.market_page._cards[window.market_page._projects[0].id].set_installing(42)
        settle(180)
        window.grab().save(str(docs / "screenshot-market.png"), "PNG")
        window._back_from_market()
        settle(120)

        # Per-instance settings.
        window.grab().save(str(base_path), "PNG")
        settings_dialog = InstanceSettingsDialog(
            window.launcher, instance, config.memory_mb, window
        )
        settings_dialog.show()
        settle(220)
        raw = docs / "_instance-settings-raw.png"
        settings_dialog.grab().save(str(raw), "PNG")
        settings_dialog.reject()
        settle(100)
        composite(base_path, raw, docs / "screenshot-instance-settings.png")
        raw.unlink(missing_ok=True)

        # Bottom part of the settings screen (accounts were captured at top).
        window.navigate("settings", persist=False, animate=False)
        settle(160)
        bar = window.settings_page.verticalScrollBar()
        bar.setValue(bar.maximum())
        settle(180)
        window.grab().save(str(docs / "screenshot-settings-bottom.png"), "PNG")

        # Install progress over the library.
        window.navigate("home", persist=False, animate=False)
        settle(120)
        window.grab().save(str(base_path), "PNG")
        progress = InstallProgressDialog(
            window.launcher, "1.20.1", window, loader="fabric", optimize=True,
            auto_start=False,
        )
        progress.show()
        progress.set_preview(
            57, "Скачивание ресурсов игры", "assets · 12 340 из 21 500"
        )
        settle(180)
        raw = docs / "_progress-raw.png"
        progress.grab().save(str(raw), "PNG")
        progress.reject()
        settle(100)
        composite(base_path, raw, docs / "screenshot-progress.png")
        raw.unlink(missing_ok=True)
        base_path.unlink(missing_ok=True)

        # Crash dialog.
        crash_log = temp_dir / "game-crash.log"
        crash_log.write_text(
            "java.lang.RuntimeException: Could not initialize class net.minecraft.client.Main\n"
            "at net.minecraft.client.main.Main.main(Main.java:231)\n"
            "Caused by: java.lang.OutOfMemoryError: Java heap space\n",
            encoding="utf-8",
        )
        crash = CrashDialog(
            window,
            title="Minecraft завершился с ошибкой",
            log_path=crash_log,
            exit_code=1,
        )
        crash.show()
        settle(180)
        crash.grab().save(str(docs / "screenshot-crash.png"), "PNG")
        crash.reject()
        crash.deleteLater()

        # Modpack store catalog.
        window.store_page._loaded = True
        window.navigate("store", persist=False, animate=False)
        settle(180)
        window.store_page._on_results(fake_modpacks())
        settle(220)
        window.grab().save(str(docs / "screenshot-store.png"), "PNG")

        # Profile with live 3D skin preview.
        profile = ProfileDialog(window, window.accounts, config.data_dir)
        profile.show()
        settle(650)
        profile.grab().save(str(docs / "screenshot-profile.png"), "PNG")
        profile.close()
        profile.deleteLater()
        settle(100)

        # 3D skin viewer: base and outer layer with walking animation.
        skin_dialog = SkinViewerDialog(window)
        skin_dialog.show()
        settle(600)
        skin_dialog.grab().save(str(docs / "screenshot-skin3d.png"), "PNG")
        skin_dialog.close()
        skin_dialog.deleteLater()
        settle(120)

        # Music popover.
        window._toggle_music_popover()
        settle(220)
        if window._music_popover is not None:
            window._music_popover.grab().save(
                str(docs / "screenshot-player.png"), "PNG"
            )
            window._music_popover.close()
            settle(100)

        # Midnight theme preview.
        window.apply_theme("midnight")
        window.navigate("home", persist=False, animate=False)
        settle(220)
        window.grab().save(str(docs / "screenshot-midnight.png"), "PNG")
        window.apply_theme("dark")

        window.close()
        app.processEvents()
        print(f"Wrote screenshots to {docs}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
