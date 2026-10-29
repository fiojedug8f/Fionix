"""Screenshots gallery shown on the instance page.

Screenshots are taken from the in-game overlay and stored in
``<instance>/screenshots`` so every build has its own gallery.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import (
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QImageReader,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.core.theme import current_theme

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
TILE_SIZE = QSize(168, 94)
MAX_TILES = 24


def screenshot_folders(instance_path: Path | None) -> list[Path]:
    """Every folder Minecraft (or the overlay) may store screenshots in.

    The launcher starts the game with ``gameDirectory = <instance>``, so F2
    screenshots land in ``<instance>/screenshots`` -- the very folder the
    overlay writes to.  Imported packs sometimes keep a nested ``.minecraft``
    folder, so that one is checked as well.
    """
    if instance_path is None:
        return []
    base = Path(instance_path)
    return [
        base / "screenshots",
        base / ".minecraft" / "screenshots",
        base / "minecraft" / "screenshots",
    ]


def screenshot_files(instance_path: Path | None) -> list[Path]:
    """Newest-first list of screenshots of one instance (overlay + game)."""
    if instance_path is None:
        return []
    seen: set[Path] = set()
    entries: list[Path] = []
    for folder in screenshot_folders(instance_path):
        if not folder.is_dir():
            continue
        try:
            candidates = [
                path
                for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
            ]
        except OSError:
            logger.debug("Could not list screenshots", exc_info=True)
            continue
        for path in candidates:
            try:
                key = path.resolve()
            except OSError:
                key = path
            if key in seen:
                continue
            seen.add(key)
            entries.append(path)
    if not entries:
        return []

    def sort_key(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(entries, key=sort_key, reverse=True)


def _thumbnail(path: Path) -> QPixmap | None:
    """Decode a screenshot at thumbnail size instead of full resolution."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        reader.setScaledSize(
            size.scaled(TILE_SIZE * 2, Qt.AspectRatioMode.KeepAspectRatio)
        )
    image = reader.read()
    if image.isNull():
        return None
    return QPixmap.fromImage(image)


class ScreenshotPreview(QDialog):
    """Full-size view of one screenshot."""

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(path.name)
        self.setModal(True)
        theme = current_theme()
        self.setStyleSheet(
            f"QDialog {{ background: {theme.panel_solid.name()}; }}"
            f"QLabel {{ color: {theme.text.name()}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        image = QPixmap(str(path))
        caption = QLabel(path.name)
        caption.setObjectName("Caption")
        layout.addWidget(caption)
        if image.isNull():
            layout.addWidget(QLabel("Не удалось открыть изображение"))
            self.resize(420, 200)
            return
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        max_width = int(available.width() * 0.86) if available else 1280
        max_height = int(available.height() * 0.82) if available else 800
        if image.width() > max_width or image.height() > max_height:
            image = image.scaled(
                max_width,
                max_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        label = QLabel()
        label.setPixmap(image)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label, 1)
        self.resize(image.width() + 28, image.height() + 56)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.close()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
            self.close()
            return
        super().keyPressEvent(event)


class ScreenshotTile(QPushButton):
    def __init__(
        self, path: Path, gallery: "ScreenshotGallery"
    ) -> None:
        super().__init__(gallery)
        self.path = path
        self.gallery = gallery
        self.setObjectName("ScreenshotTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(TILE_SIZE.width(), TILE_SIZE.height())
        self.setIconSize(TILE_SIZE - QSize(6, 6))
        pixmap = _thumbnail(path)
        if pixmap is None or pixmap.isNull():
            self.setText(path.stem)
        else:
            self.setIcon(QIcon(pixmap))
        self.setToolTip(f"{path.name}\nНажмите, чтобы открыть")
        self.clicked.connect(self._open)
        self._apply_style()

    def _apply_style(self) -> None:
        theme = current_theme()
        self.setStyleSheet(
            "QPushButton#ScreenshotTile {"
            "  background: transparent;"
            f" border: 1px solid {theme.border.name()};"
            " border-radius: 8px; padding: 2px;"
            "}"
            "QPushButton#ScreenshotTile:hover {"
            f" border-color: {theme.accent.name()};"
            "}"
        )

    def _open(self) -> None:
        preview = ScreenshotPreview(self.path, self.gallery)
        preview.exec()
        preview.deleteLater()


class ScreenshotGallery(QFrame):
    """Horizontal strip of the newest screenshots of one instance."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ScreenshotGallery")
        self._instance_path: Path | None = None
        self._instance_name = ""
        self._tiles: list[ScreenshotTile] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(10)
        title = QLabel("Скриншоты")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        self.count_label = QLabel("0")
        self.count_label.setObjectName("Caption")
        header.addWidget(self.count_label)
        header.addStretch(1)
        hint = QLabel("Снимок можно сделать в оверлее (Shift+F1)")
        hint.setObjectName("Caption")
        header.addWidget(hint)
        self.open_button = QPushButton("Открыть папку")
        self.open_button.setObjectName("GhostButton")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.setFixedHeight(34)
        self.open_button.clicked.connect(self.open_folder)
        header.addWidget(self.open_button)
        layout.addLayout(header)

        self.empty_label = QLabel(
            "Скриншотов пока нет. Запустите игру, откройте оверлей (Shift+F1) "
            "и нажмите «Сделать скриншот»."
        )
        self.empty_label.setObjectName("Muted")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setFixedHeight(TILE_SIZE.height() + 22)
        self.strip = QWidget()
        self.strip_layout = QHBoxLayout(self.strip)
        self.strip_layout.setContentsMargins(2, 2, 2, 2)
        self.strip_layout.setSpacing(8)
        self.strip_layout.addStretch(1)
        self.scroll.setWidget(self.strip)
        layout.addWidget(self.scroll)
        self.scroll.hide()

    # ----------------------------------------------------------------- data
    def load(self, instance_path: Path | None, instance_name: str = "") -> None:
        self._instance_path = Path(instance_path) if instance_path else None
        self._instance_name = instance_name
        self._rebuild()

    def refresh(self) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        for tile in self._tiles:
            self.strip_layout.removeWidget(tile)
            tile.deleteLater()
        self._tiles = []
        files = screenshot_files(self._instance_path)[:MAX_TILES]
        self.count_label.setText(str(len(files)))
        has_files = bool(files)
        self.empty_label.setVisible(not has_files)
        self.scroll.setVisible(has_files)
        self.open_button.setEnabled(self._instance_path is not None)
        for index, path in enumerate(files):
            tile = ScreenshotTile(path, self)
            self._tiles.append(tile)
            self.strip_layout.insertWidget(index, tile)

    # -------------------------------------------------------------- actions
    def open_folder(self) -> None:
        if self._instance_path is None:
            return
        folder = self._instance_path / "screenshots"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.debug("Could not create screenshots folder", exc_info=True)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._rebuild()
