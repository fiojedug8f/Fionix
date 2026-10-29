"""Application bootstrap for Fionix (accounts, market and customization)."""

from __future__ import annotations

import ctypes
import logging
import logging.handlers
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from src import __version__
from src.app_paths import asset_path, default_data_dir, ensure_data_layout
from src.core.config_manager import ConfigManager
from src.core.theme import (
    build_stylesheet,
    set_accent_color,
    set_custom_colors,
    set_theme,
)
from src.ui.main_window import MainWindow

logger = logging.getLogger(__name__)

APP_ID = "Fionix.Launcher.0.1"


def _configure_logging(data_dir: Path) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "fionix.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)


def _install_exception_hook() -> None:
    def handle(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical(
            "Unhandled exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )

    sys.excepthook = handle


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        logger.debug("Could not set Windows AppUserModelID")


def _load_bundled_fonts() -> None:
    """Optionally register fonts shipped in ``assets/fonts``."""
    fonts_dir = asset_path("fonts")
    if not fonts_dir.is_dir():
        return
    for path in sorted(fonts_dir.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(path)) == -1:
            logger.warning("Could not load bundled font: %s", path)


def create_application(argv: list[str] | None = None) -> QApplication:
    # QtWebEngine uses Chromium's GPU path for skinview3d. The blocklist is
    # conservative on Windows drivers and silently falls back to software.
    existing_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    # Never let a stale system flag force Chromium into software WebGL.
    existing_flags = (
        existing_flags.replace("--disable-gpu", "")
        .replace("--disable-gpu-compositing", "")
        .replace("--use-gl=swiftshader", "")
        .strip()
    )
    required_flags = (
        "--ignore-gpu-blocklist --enable-gpu-rasterization "
        "--use-angle=d3d11"
    )
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        f"{existing_flags} {required_flags}".strip()
    )
    # Must be set before QApplication; otherwise QtWebEngine may create a
    # software OpenGL context and the skin preview drops to ~3 FPS.
    QApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True
    )
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Fionix")
    app.setApplicationDisplayName("Fionix Launcher")
    app.setOrganizationName("Fionix")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    _load_bundled_fonts()
    app.setFont(QFont("Segoe UI", 10))

    icon_path = asset_path("icons", "fionix.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    return app


def _show_data_error(data_dir: Path, error: OSError) -> None:
    QMessageBox.critical(
        None,
        "Fionix",
        "Не удалось подготовить папку данных:\n"
        f"{data_dir}\n\n{error}\n\n"
        "Проверьте права доступа и попробуйте снова.",
    )


def run(argv: list[str] | None = None) -> int:
    _install_exception_hook()
    _set_windows_app_id()
    app = create_application(argv)

    data_dir = default_data_dir()
    try:
        data_dir = ensure_data_layout(data_dir)
    except OSError as exc:
        logger.exception("Cannot create the data layout")
        _show_data_error(data_dir, exc)
        return 1

    try:
        _configure_logging(data_dir)
    except OSError:
        # A read-only log file should not prevent the launcher from starting.
        logger.exception("Cannot configure file logging; continuing without a log")

    try:
        config = ConfigManager(data_dir)
    except OSError as exc:
        logger.exception("Cannot initialise settings")
        _show_data_error(data_dir, exc)
        return 1

    logger.info("Starting Fionix %s (data: %s)", __version__, data_dir)
    set_theme(config.theme)
    set_accent_color(config.accent)
    set_custom_colors(config.text_color, config.panel_color)
    app.setStyleSheet(build_stylesheet())

    window = MainWindow(config)
    window.show()

    exit_code = app.exec()
    logger.info("Fionix stopped with exit code %s", exit_code)
    return exit_code
