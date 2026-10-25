"""Home screen: welcome hero, primary CTA and the instance library."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.launcher import LOADER_ICONS, Instance, format_playtime
from src.core.theme import current_theme
from src.ui.pages import Page, build_header, page_badge
from src.ui.pages.store_page import StoreBanner
from src.ui.widgets import (
    CapsLabel,
    EmptyState,
    GradientLabel,
    IconBadge,
    PrimaryButton,
    with_alpha,
)


def instances_word(count: int) -> str:
    count = abs(int(count))
    if count % 10 == 1 and count % 100 != 11:
        return "сборка"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "сборки"
    return "сборок"


class HeroCard(QFrame):
    """Large glass hero with painted neon atmosphere."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HeroCard")
        self.setMinimumHeight(270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)

        # Fluent/Mica: neutral flat acrylic surface, no legacy gradient.
        painter.fillPath(path, QColor(34, 34, 34, 232))
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(rect, QColor(255, 255, 255, 8))
        painter.restore()

        painter.setPen(QPen(QColor(255, 255, 255, 34), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


class InstanceCard(QPushButton):
    """Clickable library card for one Minecraft instance."""

    def __init__(self, instance: Instance, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.instance = instance
        self.setObjectName("InstanceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(156)
        self.setToolTip("Открыть экземпляр")
        self.setAccessibleName(f"Открыть {instance.name}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 15)
        layout.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        custom = QPixmap(instance.icon_path) if instance.icon_path else QPixmap()
        if not custom.isNull():
            badge = QLabel()
            badge.setFixedSize(40, 40)
            badge.setPixmap(
                custom.scaled(
                    40,
                    40,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            badge.setStyleSheet("border-radius: 11px;")
        else:
            badge = IconBadge(
                LOADER_ICONS.get(instance.loader, "cube"),
                size=40,
                icon_size=19,
                radius=11,
            )
        top.addWidget(badge)
        top.addStretch(1)
        version_tag = QLabel(instance.loader_name.upper())
        version_tag.setObjectName("Tag")
        top.addWidget(version_tag, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        layout.addSpacing(13)

        title = QLabel(instance.name)
        title.setObjectName("InstanceCardTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        layout.addSpacing(3)

        meta = QLabel(f"Minecraft Java Edition · {instance.version}")
        meta.setObjectName("FieldHint")
        layout.addWidget(meta)
        layout.addStretch(1)
        layout.addSpacing(10)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        playtime = QLabel(f"Наиграно: {format_playtime(instance.playtime_seconds)}")
        playtime.setObjectName("Muted")
        bottom.addWidget(playtime, 1)
        action = QLabel("Открыть  →")
        action.setObjectName("CardAction")
        bottom.addWidget(action, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(bottom)

        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)


class HomePage(Page):
    create_requested = Signal()
    import_requested = Signal()
    open_game_folder_requested = Signal()
    pack_selected = Signal(object)
    instance_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body.setSpacing(16)
        self._instances: list[Instance] = []
        self.empty_state: EmptyState | None = None

        self.header_count_badge = page_badge("0 СБОРОК")
        header = build_header(
            "Добро пожаловать, Гость",
            "Соберите свою коллекцию миров — всё под рукой.",
            self.header_count_badge,
        )
        self._greeting_label = next(
            (
                label
                for label in header.findChildren(QLabel)
                if label.objectName() == "PageTitle"
            ),
            None,
        )
        self.body.addWidget(header)
        self.body.addSpacing(4)

        hero = HeroCard()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(40, 24, 40, 22)
        hero_layout.setSpacing(0)
        hero_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        hero_layout.addWidget(
            CapsLabel("FIONIX LAUNCHER", size=10, spacing=2.2, accent=True),
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        hero_layout.addSpacing(8)

        title = GradientLabel("Соберите свой идеальный мир", size=33)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)
        hero_layout.addSpacing(6)

        subtitle = QLabel(
            "Экземпляры, моды и настройки — в одном лаунчере.<br>"
            "Создайте первую сборку и начните своё приключение."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setFixedWidth(620)
        hero_layout.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignHCenter)
        hero_layout.addSpacing(17)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        actions.addStretch(1)
        self.create_button = PrimaryButton("Создать экземпляр", "plus")
        self.create_button.clicked.connect(self.create_requested.emit)
        actions.addWidget(self.create_button, 0, Qt.AlignmentFlag.AlignVCenter)
        import_button = QPushButton("Импорт .fionixpack")
        import_button.setObjectName("GhostButton")
        import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        import_button.setFixedHeight(42)
        import_button.clicked.connect(self.import_requested.emit)
        actions.addWidget(import_button, 0, Qt.AlignmentFlag.AlignVCenter)
        open_folder_button = QPushButton("Открыть папку игры")
        open_folder_button.setObjectName("GhostButton")
        open_folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder_button.setFixedHeight(42)
        open_folder_button.clicked.connect(self.open_game_folder_requested.emit)
        actions.addWidget(open_folder_button, 0, Qt.AlignmentFlag.AlignVCenter)
        actions.addStretch(1)
        hero_layout.addLayout(actions)
        hero_layout.addSpacing(10)

        note = CapsLabel(
            "MINECRAFT: JAVA EDITION  ·  АВТО-УСТАНОВКА JAVA",
            size=9,
            spacing=1.4,
            muted=True,
        )
        hero_layout.addWidget(note, 0, Qt.AlignmentFlag.AlignHCenter)

        self.body.addWidget(hero, 0)

        self.carousel = StoreBanner(QNetworkAccessManager(self))
        self.carousel.project_clicked.connect(self.pack_selected.emit)
        self.body.addWidget(self.carousel)

        section_header = QWidget()
        section_row = QHBoxLayout(section_header)
        section_row.setContentsMargins(2, 6, 2, 0)
        section_row.setSpacing(10)
        section_title = QLabel("Ваши экземпляры")
        section_title.setObjectName("SectionTitle")
        section_row.addWidget(section_title)
        self.section_count = QLabel("0")
        self.section_count.setObjectName("CountChip")
        section_row.addWidget(self.section_count)
        section_row.addStretch(1)
        self.section_hint = QLabel("Карточки сборок появятся здесь")
        self.section_hint.setObjectName("Muted")
        section_row.addWidget(self.section_hint)
        self.body.addWidget(section_header)

        self.grid_host = QWidget()
        self.instances_grid = QGridLayout(self.grid_host)
        self.instances_grid.setContentsMargins(0, 0, 0, 0)
        self.instances_grid.setSpacing(16)
        self.instances_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.body.addWidget(self.grid_host, 1)

        footer = QLabel("Java, библиотеки и ресурсы скачиваются автоматически")
        footer.setObjectName("Caption")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(footer)

        self.set_instances([])

    # ---------------------------------------------------------------- data
    def set_instances(self, instances: list[Instance]) -> None:
        self._instances = list(instances)
        count = len(self._instances)
        plural = instances_word(count)
        self.header_count_badge.setText(f"{count} {plural.upper()}")
        self.section_count.setText(str(count))
        self.section_hint.setText(
            "Нажмите на карточку, чтобы открыть экземпляр"
            if count
            else "Карточки сборок появятся здесь"
        )
        self._rebuild_grid()

    def _clear_grid(self) -> None:
        while self.instances_grid.count():
            item = self.instances_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for column in range(3):
            self.instances_grid.setColumnStretch(column, 0)
        self.instances_grid.setRowStretch(0, 0)
        self.empty_state = None

    def _rebuild_grid(self) -> None:
        self._clear_grid()
        if not self._instances:
            empty = EmptyState(
                "cube",
                "Пока здесь пусто",
                "Здесь появятся карточки ваших экземпляров. Создайте первую сборку — "
                "и она займёт своё место в библиотеке.",
            )
            empty.setMinimumHeight(154)
            empty.description_label.setMaximumWidth(560)
            empty.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.empty_state = empty
            self.instances_grid.addWidget(empty, 0, 0, 1, 3)
            self.instances_grid.setRowStretch(0, 1)
            for column in range(3):
                self.instances_grid.setColumnStretch(column, 1)
            return

        columns = 2 if len(self._instances) <= 2 else 3
        for index, instance in enumerate(self._instances):
            card = InstanceCard(instance)
            card.clicked.connect(lambda _checked=False, item=instance: self.instance_selected.emit(item))
            self.instances_grid.addWidget(card, index // columns, index % columns)
        for column in range(3):
            self.instances_grid.setColumnStretch(column, 1 if column < columns else 0)

    # --------------------------------------------------------------- misc
    def set_player_name(self, name: str) -> None:
        display = (name or "Гость").strip()
        if self._greeting_label is not None:
            self._greeting_label.setText(f"Добро пожаловать, {display}")
