"""Design tokens and the global QSS stylesheet.

All colours used by Fionix live here.  Widgets read :func:`current_theme` at
paint time, while classic Qt widgets are styled by the stylesheet produced by
:func:`build_stylesheet`.  That keeps theme switching in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from string import Template

from PySide6.QtGui import QColor

FONT_FAMILY = "Segoe UI"
FONT_DISPLAY = "Segoe UI Semibold"


def _c(hex_value: str, alpha: int = 255) -> QColor:
    color = QColor(hex_value)
    color.setAlpha(alpha)
    return color


def _css(color: QColor) -> str:
    if color.alpha() == 255:
        return color.name()
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


@dataclass(frozen=True, slots=True)
class Theme:
    key: str
    display_name: str
    dark: bool

    accent: QColor
    accent_light: QColor
    accent_2: QColor
    accent_3: QColor
    accent_soft: QColor
    accent_border: QColor
    accent_glow: QColor

    text: QColor
    text_secondary: QColor
    text_muted: QColor

    panel: QColor
    panel_hover: QColor
    panel_solid: QColor
    sidebar: QColor

    border: QColor
    border_strong: QColor

    input: QColor
    input_border: QColor

    success: QColor
    danger: QColor
    warning: QColor
    success_soft: QColor
    danger_soft: QColor

    backdrop_tint: QColor
    shadow: QColor

    def css(self, color: QColor) -> str:
        return _css(color)

    def qss_vars(self) -> dict[str, str]:
        return {
            "font": FONT_FAMILY,
            "accent": _css(self.accent),
            "accent_light": _css(self.accent_light),
            "accent_2": _css(self.accent_2),
            "accent_3": _css(self.accent_3),
            "accent_soft": _css(self.accent_soft),
            "accent_border": _css(self.accent_border),
            "accent_glow": _css(self.accent_glow),
            "text": _css(self.text),
            "text_secondary": _css(self.text_secondary),
            "text_muted": _css(self.text_muted),
            "panel": _css(self.panel),
            "panel_hover": _css(self.panel_hover),
            "panel_solid": _css(self.panel_solid),
            "sidebar": _css(self.sidebar),
            "border": _css(self.border),
            "border_strong": _css(self.border_strong),
            "input": _css(self.input),
            "input_border": _css(self.input_border),
            "success": _css(self.success),
            "danger": _css(self.danger),
            "warning": _css(self.warning),
            "success_soft": _css(self.success_soft),
            "danger_soft": _css(self.danger_soft),
        }


DARK = Theme(
    key="dark",
    display_name="Fionix Dark",
    dark=True,
    accent=_c("#0078D4"),
    accent_light=_c("#4CC2FF"),
    accent_2=_c("#005FB8"),
    accent_3=_c("#50E6FF"),
    accent_soft=_c("#0078D4", 34),
    accent_border=_c("#0078D4", 100),
    accent_glow=_c("#0078D4", 96),
    text=_c("#F5F5F5"),
    text_secondary=_c("#C8C8C8"),
    text_muted=_c("#9A9A9A"),
    panel=_c("#282828", 218),
    panel_hover=_c("#333333", 232),
    panel_solid=_c("#202020"),
    sidebar=_c("#1A1A1A", 232),
    border=_c("#FFFFFF", 26),
    border_strong=_c("#FFFFFF", 46),
    input=_c("#FFFFFF", 12),
    input_border=_c("#FFFFFF", 30),
    success=_c("#4ADE80"),
    danger=_c("#FB7185"),
    warning=_c("#FBBF24"),
    success_soft=_c("#34D399", 26),
    danger_soft=_c("#FB7185", 24),
    backdrop_tint=_c("#202020", 218),
    shadow=_c("#000000", 130),
)

MIDNIGHT = Theme(
    key="midnight",
    display_name="Fionix Midnight",
    dark=True,
    accent=_c("#8B5CF6"),
    accent_light=_c("#BFB0FF"),
    accent_2=_c("#2563EB"),
    accent_3=_c("#06B6D4"),
    accent_soft=_c("#7C5CFF", 34),
    accent_border=_c("#8B5CF6", 84),
    accent_glow=_c("#7C5CFF", 112),
    text=_c("#F8F7FF"),
    text_secondary=_c("#ABA7BF"),
    text_muted=_c("#747086"),
    panel=_c("#0A0A12", 220),
    panel_hover=_c("#161624", 235),
    panel_solid=_c("#08080E"),
    sidebar=_c("#030307", 224),
    border=_c("#FFFFFF", 18),
    border_strong=_c("#FFFFFF", 34),
    input=_c("#FFFFFF", 9),
    input_border=_c("#FFFFFF", 22),
    success=_c("#34D399"),
    danger=_c("#FB7185"),
    warning=_c("#FBBF24"),
    success_soft=_c("#34D399", 26),
    danger_soft=_c("#FB7185", 24),
    backdrop_tint=_c("#000000", 158),
    shadow=_c("#000000", 220),
)

LIGHT = Theme(
    key="light",
    display_name="Fionix Light",
    dark=False,
    accent=_c("#0067C0"),
    accent_light=_c("#005A9E"),
    accent_2=_c("#004E8C"),
    accent_3=_c("#0078D4"),
    accent_soft=_c("#0067C0", 26),
    accent_border=_c("#0067C0", 90),
    accent_glow=_c("#0067C0", 80),
    text=_c("#1C1927"),
    text_secondary=_c("#4B465C"),
    text_muted=_c("#777184"),
    panel=_c("#FFFFFF", 226),
    panel_hover=_c("#F1EDFA", 240),
    panel_solid=_c("#FFFFFF"),
    sidebar=_c("#F7F4FC", 238),
    border=_c("#241B38", 24),
    border_strong=_c("#241B38", 42),
    input=_c("#241B38", 10),
    input_border=_c("#241B38", 28),
    success=_c("#047857"),
    danger=_c("#BE123C"),
    warning=_c("#B45309"),
    success_soft=_c("#10B981", 28),
    danger_soft=_c("#F43F5E", 24),
    backdrop_tint=_c("#F4F1FA", 205),
    shadow=_c("#2B2140", 45),
)

THEMES: dict[str, Theme] = {
    theme.key: theme for theme in (DARK, MIDNIGHT, LIGHT)
}
_current: Theme = DARK
_custom_accent: str = ""
_custom_text: str = ""
_custom_panel: str = ""


def _with_accent(theme: Theme, accent_value: str) -> Theme:
    if not accent_value:
        return theme
    color = QColor(accent_value)
    if not color.isValid():
        return theme
    light = QColor(color).lighter(158)
    dark = QColor(color).darker(122)
    third = QColor(color).lighter(128)
    soft = QColor(color)
    soft.setAlpha(theme.accent_soft.alpha())
    border = QColor(color)
    border.setAlpha(theme.accent_border.alpha())
    glow = QColor(color)
    glow.setAlpha(theme.accent_glow.alpha())
    return replace(
        theme,
        accent=color,
        accent_light=light,
        accent_2=dark,
        accent_3=third,
        accent_soft=soft,
        accent_border=border,
        accent_glow=glow,
    )


def _hex_or_empty(value: str) -> str:
    candidate = (value or "").strip()
    if len(candidate) == 7 and candidate.startswith("#") and QColor(candidate).isValid():
        return candidate.lower()
    return ""


def _with_colors(theme: Theme, text_value: str, panel_value: str) -> Theme:
    updates: dict[str, QColor] = {}
    if text_value:
        text = QColor(text_value)
        dark_text = text.lightness() < 128
        secondary = text.lighter(155) if dark_text else text.darker(135)
        muted = text.lighter(185) if dark_text else text.darker(165)
        updates.update(
            text=text,
            text_secondary=secondary,
            text_muted=muted,
        )
    if panel_value:
        panel = QColor(panel_value)
        light_panel = panel.lightness() > 150
        base = QColor(panel)
        base.setAlpha(200 if light_panel else theme.panel.alpha())
        hover = QColor(panel).darker(106) if light_panel else QColor(panel).lighter(112)
        hover.setAlpha(225)
        solid = QColor(panel)
        solid.setAlpha(255)
        sidebar = QColor(panel).darker(108) if light_panel else QColor(panel).darker(125)
        sidebar.setAlpha(225)
        input_color = QColor(panel).darker(104) if light_panel else QColor(panel).lighter(112)
        input_color.setAlpha(30 if light_panel else 14)
        input_border = QColor(panel).darker(150) if light_panel else QColor(255, 255, 255, 30)
        border = QColor(0, 0, 0, 32) if light_panel else QColor(255, 255, 255, 24)
        updates.update(
            panel=base,
            panel_hover=hover,
            panel_solid=solid,
            sidebar=sidebar,
            input=input_color,
            input_border=input_border,
            border=border,
            border_strong=QColor(0, 0, 0, 55) if light_panel else QColor(255, 255, 255, 44),
        )
    return replace(theme, **updates) if updates else theme


def current_theme() -> Theme:
    return _with_colors(
        _with_accent(_current, _custom_accent), _custom_text, _custom_panel
    )


def set_theme(key: str) -> Theme:
    global _current
    _current = THEMES.get(key, DARK)
    return current_theme()


def set_accent_color(value: str) -> Theme:
    """Apply a user-selected ``#RRGGBB`` accent (empty restores the theme)."""
    global _custom_accent
    _custom_accent = _hex_or_empty(value)
    return current_theme()


def set_custom_colors(text_value: str, panel_value: str) -> Theme:
    """Apply optional text/panel overrides for the auto-contrast feature."""
    global _custom_text, _custom_panel
    _custom_text = _hex_or_empty(text_value)
    _custom_panel = _hex_or_empty(panel_value)
    return current_theme()


def theme_options() -> list[tuple[str, str]]:
    return [(theme.key, theme.display_name) for theme in THEMES.values()]


_QSS = Template(
    """
/* ============================================================
   Fionix 1.5 — Windows 11 Fluent (Mica/Acrylic) stylesheet
   Flat surfaces, neutral glass panels, one accent for actions.
   ============================================================ */
* {
    outline: none;
}
QWidget {
    color: $text;
    font-family: "Segoe UI", "Inter", "Segoe UI Variable", sans-serif;
    font-size: 13px;
    selection-background-color: $accent;
    selection-color: #FFFFFF;
}
QMainWindow, QDialog {
    background: transparent;
}
QWidget#ContentRoot, QWidget#Page, QStackedWidget, QWidget#Shell,
QWidget#VideoBackground, QWidget#GallerySurface {
    background: transparent;
}
QMainWindow[fullscreen="true"], QWidget#ContentRoot[fullscreen="true"],
QFrame#Shell[fullscreen="true"], QFrame#Sidebar[fullscreen="true"] {
    border-radius: 0px;
}

/* ------------------------------ surfaces ------------------------------ */
QFrame#Shell {
    background: transparent;
    border: 1px solid rgba(255, 255, 255, 24);
    border-radius: 12px;
}
QFrame#Sidebar {
    background: rgba(32, 32, 32, 235);
    border: none;
    border-right: 1px solid rgba(255, 255, 255, 20);
    border-top-left-radius: 12px;
    border-bottom-left-radius: 12px;
}
QFrame#Sidebar[maximized="true"] {
    border-top-left-radius: 0px;
    border-bottom-left-radius: 0px;
}
QFrame#ProfileCard, QFrame#SettingsCard, QFrame#InstanceHero,
QFrame#InstallInfo, QFrame#StatChip, QFrame#HeroCard,
QFrame#DetailHero, QFrame#StoreBanner, QFrame#VersionCard,
QFrame#DownloadRow, QFrame#ContentRow, QFrame#Popover,
QFrame#SidebarEmpty, QFrame#ContentEmpty, QFrame#EmptyState,
QFrame#ProxyFields {
    background-color: rgba(45, 45, 45, 200);
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 12px;
}
QFrame#DialogCard {
    background-color: rgba(37, 37, 37, 248);
    border: 1px solid rgba(255, 255, 255, 28);
    border-radius: 12px;
}
QFrame#Divider, QFrame#DialogDivider, QFrame#TitleBarSeparator {
    background-color: rgba(255, 255, 255, 20);
    border: none;
    min-height: 1px;
    max-height: 1px;
}
QFrame#StoreBanner:hover, QFrame#DetailHero:hover, QFrame#VersionCard:hover,
QFrame#DownloadRow:hover {
    border-color: rgba(255, 255, 255, 38);
    background-color: rgba(52, 52, 52, 215);
}

/* ------------------------------ typography ----------------------------- */
QLabel#PageTitle {
    font-size: 26px;
    font-weight: 600;
    color: $text;
}
QLabel#DialogTitle {
    font-size: 22px;
    font-weight: 600;
    color: $text;
}
QLabel#PageSubtitle {
    font-size: 13px;
    font-weight: 400;
    color: $text_secondary;
}
QLabel#SectionTitle {
    font-size: 15px;
    font-weight: 600;
    color: $text;
}
QLabel#FieldLabel {
    font-size: 12px;
    font-weight: 600;
    color: $text;
}
QLabel#FieldHint, QLabel#Caption, QLabel#Muted {
    font-size: 11px;
    color: $text_muted;
}
QLabel#ValueLabel {
    font-size: 14px;
    font-weight: 600;
    color: $text;
}
QLabel#DialogError, QLabel#ProgressDetail {
    font-size: 11px;
    color: $text_secondary;
}
QLabel#InstanceCardTitle {
    font-size: 16px;
    font-weight: 600;
    color: $text;
}
QLabel#InstanceHeroTitle {
    font-size: 24px;
    font-weight: 600;
    color: $text;
}
QLabel#InstancePlaytime {
    font-size: 20px;
    font-weight: 600;
    color: $text;
}
QLabel#InstanceTimer {
    font-size: 12px;
    font-weight: 600;
    color: $accent_light;
}
QLabel#CardAction {
    font-size: 11px;
    color: $text_secondary;
}
QLabel#EmptyTitle {
    font-size: 15px;
    font-weight: 600;
    color: $text;
}
QLabel#EmptyText {
    font-size: 12px;
    color: $text_muted;
}
QLabel#ProfileName {
    font-size: 13px;
    font-weight: 600;
    color: $text;
}
QLabel#ProfileRole {
    font-size: 10px;
    color: $text_muted;
}
QLabel#Tag, QLabel#LoaderTag, QLabel#CountChip {
    background: rgba(255, 255, 255, 10);
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 6px;
    padding: 2px 7px;
    color: $text_secondary;
    font-size: 10px;
    font-weight: 600;
}
QLabel#CoreTileTitle {
    font-size: 13px;
    font-weight: 600;
    color: $text;
}
QLabel#CoreTileSubtitle {
    font-size: 10px;
    color: $text_muted;
}
QLabel#RunState {
    font-size: 11px;
    color: $text_secondary;
}
QLabel#RunState[state="error"] { color: $danger; }
QLabel#RunState[state="busy"] { color: $warning; }
QLabel#RunState[state="playing"] { color: $success; }
QLabel#IncompatibleBadge {
    background: rgba(251, 191, 36, 28);
    border: 1px solid rgba(251, 191, 36, 110);
    border-radius: 5px;
    color: #FBBF24;
    font-size: 9px;
    font-weight: 600;
    padding: 2px 6px;
}
QLabel#ModCardTitle {
    font-size: 14px;
    font-weight: 600;
    color: $text;
}
QLabel#ModCardText {
    font-size: 11px;
    color: $text_secondary;
}
QLabel#ModCardStatus {
    font-size: 10px;
    font-weight: 600;
    color: $text_muted;
}
QLabel#ModCardStatus[state="working"] { color: $accent_light; }
QLabel#ModCardStatus[state="done"] { color: $success; }
QLabel#ModCardStatus[state="error"] { color: $danger; }
QLabel#GalleryThumb {
    background: rgba(255, 255, 255, 8);
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 8px;
    color: $text_muted;
}
QLabel#BannerTitle {
    font-size: 22px;
    font-weight: 600;
    color: $text;
}

/* ------------------------------ buttons -------------------------------- */
QPushButton {
    background-color: rgba(255, 255, 255, 9);
    color: $text;
    border: 1px solid rgba(255, 255, 255, 12);
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: rgba(255, 255, 255, 16);
    border-color: rgba(255, 255, 255, 24);
}
QPushButton:pressed {
    background-color: rgba(255, 255, 255, 7);
}
QPushButton:disabled {
    background-color: rgba(255, 255, 255, 4);
    border-color: rgba(255, 255, 255, 8);
    color: $text_muted;
}
QPushButton#PrimaryButton {
    background-color: $accent;
    border: none;
    border-radius: 8px;
    color: #FFFFFF;
    font-weight: 600;
    padding: 9px 20px;
}
QPushButton#PrimaryButton:hover {
    background-color: $accent_light;
}
QPushButton#PrimaryButton:pressed {
    background-color: $accent_2;
}
QPushButton#SoftButton {
    background-color: $accent_soft;
    border: 1px solid $accent_border;
    border-radius: 8px;
    color: $accent_light;
    font-weight: 600;
}
QPushButton#SoftButton:hover {
    background-color: $accent_border;
    color: #FFFFFF;
}
QPushButton#GhostButton {
    background: transparent;
    border: 1px solid rgba(255, 255, 255, 28);
    color: $text_secondary;
}
QPushButton#GhostButton:hover {
    background: rgba(255, 255, 255, 10);
    border-color: rgba(255, 255, 255, 46);
    color: $text;
}
QPushButton#DangerButton {
    background: rgba(251, 113, 133, 24);
    border: 1px solid rgba(251, 113, 133, 70);
    color: $danger;
}
QPushButton#DangerButton:hover { background: rgba(251, 113, 133, 42); }
QPushButton#LinkButton {
    background: transparent;
    border: none;
    color: $text_secondary;
    padding: 3px 4px;
}
QPushButton#LinkButton:hover { color: $accent_light; }
QPushButton#TabButton {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0px;
    padding: 8px 12px;
    color: $text_muted;
    font-weight: 600;
}
QPushButton#TabButton:hover { color: $text_secondary; }
QPushButton#TabButton:checked {
    color: $text;
    border-bottom: 2px solid $accent;
}
QPushButton#CoreTile {
    background: rgba(255, 255, 255, 6);
    border: 1px solid rgba(255, 255, 255, 16);
    border-radius: 8px;
    padding: 8px;
    text-align: left;
}
QPushButton#CoreTile:hover { background: rgba(255, 255, 255, 12); }
QPushButton#CoreTile:checked {
    background: $accent_soft;
    border: 1px solid $accent;
}
QPushButton#CoreTile:disabled {
    background: rgba(255, 255, 255, 3);
    color: $text_muted;
}
QPushButton#ContentTile {
    background: rgba(45, 45, 45, 200);
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 12px;
    padding: 0px;
}
QPushButton#ContentTile:hover {
    background: rgba(54, 54, 54, 220);
    border-color: rgba(255, 255, 255, 34);
}
QPushButton#InstanceCard {
    background: rgba(45, 45, 45, 200);
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 12px;
    padding: 0px;
    text-align: left;
}
QPushButton#InstanceCard:hover {
    background: rgba(54, 54, 54, 220);
    border-color: rgba(255, 255, 255, 32);
}
QPushButton#ModCard {
    background: rgba(45, 45, 45, 200);
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 10px;
    padding: 0px;
    text-align: left;
}
QPushButton#ModCard:hover {
    background: rgba(54, 54, 54, 220);
    border-color: rgba(255, 255, 255, 32);
}
QPushButton#ProviderTile {
    background: rgba(45, 45, 45, 200);
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 10px;
    padding: 0px;
}
QPushButton#ProviderTile:hover { border-color: $accent; }
QLabel#ProviderTitle { font-size: 14px; font-weight: 600; color: $text; }
QLabel#ProviderBadge {
    background: $accent_soft;
    border: 1px solid $accent_border;
    border-radius: 6px;
    color: $accent_light;
    font-size: 10px;
    font-weight: 600;
    padding: 2px 8px;
}
QPushButton#VersionChip {
    background: rgba(255, 255, 255, 8);
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 8px;
    padding: 5px 10px;
    color: $text_secondary;
}
QPushButton#VersionChip:hover, QPushButton#VersionChip:checked {
    background: $accent_soft;
    border-color: $accent;
    color: $text;
}

/* ------------------------------ inputs --------------------------------- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: rgba(255, 255, 255, 8);
    color: $text;
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: $accent;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: $accent;
    background-color: rgba(255, 255, 255, 11);
}
QLineEdit:disabled, QComboBox:disabled { color: $text_muted; }
QComboBox::drop-down {
    border: none;
    width: 26px;
}
QComboBox::down-arrow {
    width: 10px;
    height: 10px;
}
QComboBox QAbstractItemView {
    background-color: #2D2D2D;
    color: $text;
    border: 1px solid rgba(255, 255, 255, 28);
    border-radius: 8px;
    selection-background-color: $accent;
    selection-color: #FFFFFF;
    padding: 4px;
}
QCheckBox, QRadioButton { spacing: 8px; color: $text_secondary; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid rgba(255, 255, 255, 48);
    background: rgba(255, 255, 255, 7);
}
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: $accent;
    border-color: $accent;
}

/* ------------------------------ navigation ----------------------------- */
QPushButton#NavButton {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: $text_muted;
    text-align: left;
    padding: 9px 12px;
}
QPushButton#NavButton:hover {
    background: rgba(255, 255, 255, 8);
    color: $text_secondary;
}
QPushButton#NavButton:checked {
    background: $accent_soft;
    color: $text;
}

/* ------------------------------ tabs ----------------------------------- */
QTabWidget#ContentTabs::pane {
    background-color: rgba(45, 45, 45, 200);
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 10px;
    top: -1px;
}
QTabWidget#ContentTabs QTabBar::tab {
    background: transparent;
    color: $text_muted;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 9px 16px;
    margin-right: 4px;
}
QTabWidget#ContentTabs QTabBar::tab:selected {
    color: $text;
    border-bottom-color: $accent;
}
QTabWidget#ContentTabs QTabBar::tab:hover { color: $text_secondary; }
QTextBrowser#ModBody {
    background: rgba(255, 255, 255, 4);
    border: none;
    border-radius: 8px;
    color: $text_secondary;
    padding: 18px;
}

/* ------------------------------ progress ------------------------------- */
QProgressBar {
    background: rgba(255, 255, 255, 12);
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background-color: $accent;
    border-radius: 4px;
}
QSlider::groove:horizontal {
    background: rgba(255, 255, 255, 16);
    height: 4px;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: $accent;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #FFFFFF;
    border: none;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover { background: $accent_light; }

/* ------------------------------ lists / scroll ------------------------- */
QScrollArea, QScrollArea > QWidget > QWidget {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 46);
    min-height: 28px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 76); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0px;
}
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: rgba(255, 255, 255, 46);
    min-width: 28px;
    border-radius: 4px;
}
QListWidget, QListView, QTreeView {
    background: transparent;
    border: none;
    color: $text_secondary;
    outline: none;
}
QListWidget::item, QListView::item {
    padding: 6px;
    border-radius: 6px;
}
QListWidget::item:hover, QListView::item:hover {
    background: rgba(255, 255, 255, 8);
}
QListWidget::item:selected, QListView::item:selected {
    background: $accent_soft;
    color: $text;
}
QListWidget#Playlist {
    background: rgba(255, 255, 255, 4);
    border: 1px solid rgba(255, 255, 255, 16);
    border-radius: 8px;
    padding: 4px;
}

/* ------------------------------ misc ----------------------------------- */
QToolTip {
    background-color: #2D2D2D;
    color: $text;
    border: 1px solid rgba(255, 255, 255, 28);
    border-radius: 6px;
    padding: 5px 8px;
}
QMenu {
    background-color: #2D2D2D;
    color: $text;
    border: 1px solid rgba(255, 255, 255, 24);
    border-radius: 8px;
    padding: 5px;
}
QMenu::item { padding: 7px 22px; border-radius: 5px; }
QMenu::item:selected { background: $accent_soft; }
QMessageBox { background-color: #252525; }
QFrame#HeroCard {
    border-radius: 12px;
}
"""
)

def build_stylesheet(theme: Theme | None = None) -> str:
    theme = theme or _current
    return _QSS.substitute(theme.qss_vars())
