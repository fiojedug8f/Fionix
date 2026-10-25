"""Page scaffolding shared by the main screens."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class Page(QScrollArea):
    """Transparent, vertically scrollable page with consistent margins."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        margins: tuple[int, int, int, int] = (30, 20, 30, 26),
        spacing: int = 18,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PageScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.viewport().setAutoFillBackground(False)

        self.content = QWidget()
        self.content.setObjectName("PageContent")
        self.content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(spacing)
        self.setWidget(self.content)


def build_header(
    title: str,
    subtitle: str,
    trailing: QWidget | None = None,
) -> QWidget:
    """Standard page heading with optional trailing badge."""
    header = QWidget()
    row = QHBoxLayout(header)
    row.setContentsMargins(2, 0, 2, 0)
    row.setSpacing(16)

    text_column = QVBoxLayout()
    text_column.setContentsMargins(0, 0, 0, 0)
    text_column.setSpacing(4)
    title_label = QLabel(title)
    title_label.setObjectName("PageTitle")
    subtitle_label = QLabel(subtitle)
    subtitle_label.setObjectName("PageSubtitle")
    text_column.addWidget(title_label)
    text_column.addWidget(subtitle_label)
    row.addLayout(text_column)
    row.addStretch(1)
    if trailing is not None:
        row.addWidget(trailing, 0, Qt.AlignmentFlag.AlignVCenter)
    return header


def page_badge(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Badge")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label
