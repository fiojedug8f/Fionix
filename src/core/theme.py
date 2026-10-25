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
    accent=_c("#8B5CF6"),
    accent_light=_c("#C4B5FD"),
    accent_2=_c("#4F8CFF"),
    accent_3=_c("#22D3EE"),
    accent_soft=_c("#8B5CF6", 38),
    accent_border=_c("#8B5CF6", 96),
    accent_glow=_c("#8B5CF6", 130),
    text=_c("#F5F3FF"),
    text_secondary=_c("#B9B4CE"),
    text_muted=_c("#827E96"),
    panel=_c("#171722", 183),
    panel_hover=_c("#232333", 215),
    panel_solid=_c("#15151E"),
    sidebar=_c("#0C0C13", 184),
    border=_c("#FFFFFF", 22),
    border_strong=_c("#FFFFFF", 40),
    input=_c("#FFFFFF", 12),
    input_border=_c("#FFFFFF", 26),
    success=_c("#34D399"),
    danger=_c("#FB7185"),
    warning=_c("#FBBF24"),
    success_soft=_c("#34D399", 30),
    danger_soft=_c("#FB7185", 28),
    backdrop_tint=_c("#05050B", 92),
    shadow=_c("#000000", 180),
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

THEMES: dict[str, Theme] = {theme.key: theme for theme in (DARK, MIDNIGHT)}
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
/* ============================== base ============================== */
* {
    outline: none;
}
QWidget {
    color: $text;
    font-family: "$font";
    font-size: 13px;
}
QMainWindow, QDialog {
    background: transparent;
}
QToolTip {
    background-color: $panel_solid;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
}
QLabel {
    background: transparent;
}
QWidget#Shell, QWidget#ContentRoot, QWidget#Page {
    background: transparent;
}
QStackedWidget {
    background: transparent;
}

/* ============================== labels ============================== */
QLabel#PageTitle {
    font-size: 26px;
    font-weight: 600;
    color: $text;
}
QLabel#PageSubtitle {
    font-size: 13px;
    color: $text_secondary;
}
QLabel#SectionTitle {
    font-size: 16px;
    font-weight: 600;
    color: $text;
}
QLabel#InstanceCardTitle {
    font-size: 16px;
    font-weight: 600;
    color: $text;
}
QLabel#CardAction {
    font-size: 11px;
    font-weight: 600;
    color: $accent_light;
}
QLabel#InstanceHeroTitle {
    font-size: 24px;
    font-weight: 600;
    color: $text;
}
QLabel#InstancePlaytime {
    font-size: 20px;
    font-weight: 600;
    color: $accent_light;
}
QLabel#InstanceTimer {
    font-size: 13px;
    font-weight: 600;
    color: $accent_3;
}
QLabel#LoaderTag {
    background-color: $accent_soft;
    border: 1px solid $accent_border;
    border-radius: 8px;
    padding: 2px 8px;
    color: $accent_light;
    font-size: 10px;
    font-weight: 600;
}
QFrame#DialogSection {
    background-color: transparent;
    border: none;
}
QFrame#DialogDivider {
    background-color: $border;
    border: none;
    min-height: 1px;
    max-height: 1px;
}
QLabel#DialogTitle {
    font-size: 22px;
    font-weight: 600;
    color: $text;
}
QLabel#PopoverTitle {
    font-size: 14px;
    font-weight: 600;
    color: $text;
}
QLabel#FieldLabel {
    font-size: 13px;
    font-weight: 600;
    color: $text;
}
QLabel#FieldHint {
    font-size: 12px;
    color: $text_muted;
}
QLabel#Muted {
    color: $text_muted;
    font-size: 12px;
}
QLabel#Caption {
    color: $text_muted;
    font-size: 11px;
}
QLabel#Caption[state="error"] {
    color: $danger;
}
QLabel#Caption[state="ok"] {
    color: $success;
}
QLabel#ProfileName {
    font-size: 14px;
    font-weight: 600;
    color: $text;
}
QLabel#ProfileRole {
    font-size: 11px;
    color: $text_muted;
}
QLabel#ValueLabel {
    font-size: 13px;
    font-weight: 600;
    color: $accent_light;
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
QLabel#SaveState {
    font-size: 12px;
    color: $text_muted;
}
QLabel#SaveState[state="ok"] {
    color: $success;
}
QLabel#SaveState[state="saving"] {
    color: $warning;
}
QLabel#SaveState[state="error"] {
    color: $danger;
}
QLabel#RunState {
    font-size: 12px;
    font-weight: 600;
    color: $text_secondary;
}
QLabel#RunState[state="ready"] {
    color: $success;
}
QLabel#RunState[state="playing"] {
    color: $accent_3;
}
QLabel#RunState[state="busy"] {
    color: $warning;
}
QLabel#RunState[state="error"] {
    color: $danger;
}
QLabel#ProgressPhase {
    font-size: 14px;
    font-weight: 600;
    color: $text;
}
QLabel#ProgressDetail {
    font-size: 11px;
    color: $text_muted;
}
QLabel#DialogError {
    font-size: 12px;
    color: $danger;
}
QLabel#Badge {
    background-color: $accent_soft;
    border: 1px solid $accent_border;
    border-radius: 9px;
    padding: 3px 9px;
    color: $accent_light;
    font-size: 10px;
    font-weight: 600;
}
QLabel#Tag {
    background-color: $input;
    border: 1px solid $input_border;
    border-radius: 8px;
    padding: 3px 8px;
    color: $text_muted;
    font-size: 10px;
    font-weight: 500;
}
QLabel#CountChip {
    background-color: rgba(255, 255, 255, 14);
    border: 1px solid $border;
    border-radius: 7px;
    padding: 1px 6px;
    color: $text_muted;
    font-size: 10px;
    font-weight: 600;
    min-width: 12px;
}

/* ============================== frames ============================== */
QFrame#Sidebar {
    background-color: $sidebar;
    border: none;
    border-right: 1px solid $border;
    border-top-left-radius: 20px;
    border-bottom-left-radius: 20px;
}
QFrame#Sidebar[maximized="true"] {
    border-top-left-radius: 0px;
    border-bottom-left-radius: 0px;
}
QFrame#ProfileCard {
    background-color: rgba(255, 255, 255, 5);
    border: 1px solid $border;
    border-radius: 14px;
}
QFrame#GlassCard, QFrame#SettingCard, QFrame#StoreTile {
    background-color: $panel;
    border: 1px solid $border;
    border-radius: 18px;
}
QFrame#StoreTile:hover {
    background-color: $panel_hover;
    border-color: $accent_border;
}
QFrame#EmptyState {
    background-color: rgba(255, 255, 255, 6);
    border: 1px dashed $border_strong;
    border-radius: 18px;
}
QFrame#SidebarEmpty {
    background-color: rgba(255, 255, 255, 5);
    border: 1px dashed $border_strong;
    border-radius: 13px;
}
QFrame#Divider {
    background-color: $border;
    border: none;
    max-height: 1px;
    min-height: 1px;
}
QFrame#Popover {
    background-color: $panel_solid;
    border: 1px solid $border_strong;
    border-radius: 18px;
}
QFrame#DialogCard {
    background-color: $panel_solid;
    border: 1px solid $border_strong;
    border-radius: 22px;
}
QFrame#DialogIcon {
    border-radius: 18px;
    background-color: $accent_soft;
    border: 1px solid $accent_border;
}
QFrame#MusicArt {
    border-radius: 14px;
}
QFrame#TitleBarSeparator {
    background-color: $border;
    border: none;
    max-width: 1px;
    min-width: 1px;
}
QFrame#StatChip {
    background-color: rgba(255, 255, 255, 6);
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#ProxyFields {
    background: transparent;
}
QFrame#InstallInfo {
    background-color: $input;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#InstanceHero {
    background-color: $panel;
    border: 1px solid $border;
    border-radius: 20px;
}

/* ============================== buttons ============================== */
QPushButton {
    background-color: $input;
    color: $text;
    border: 1px solid $input_border;
    border-radius: 11px;
    padding: 9px 16px;
    font-size: 13px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: $panel_hover;
    border-color: $accent_border;
}
QPushButton:pressed {
    background-color: $accent_soft;
}
QPushButton:disabled {
    color: $text_muted;
    background-color: rgba(255, 255, 255, 4);
    border-color: $border;
}
QPushButton#GhostButton {
    background-color: transparent;
    border: 1px solid $border_strong;
    color: $text_secondary;
    border-radius: 11px;
    padding: 9px 16px;
}
QPushButton#GhostButton:hover {
    border-color: $accent_border;
    color: $text;
    background-color: $accent_soft;
}
QPushButton#SoftButton {
    background-color: $accent_soft;
    border: 1px solid $accent_border;
    color: $accent_light;
}
QPushButton#SoftButton:hover {
    background-color: $accent_soft;
    color: $text;
}
QPushButton#DangerButton {
    background-color: $danger_soft;
    border: 1px solid rgba(251, 113, 133, 70);
    color: $danger;
}
QPushButton#DangerButton:hover {
    background-color: rgba(251, 113, 133, 44);
}
QPushButton#LinkButton {
    background: transparent;
    border: none;
    color: $text_muted;
    padding: 4px 2px;
    font-size: 12px;
}
QPushButton#LinkButton:hover {
    color: $accent_light;
}
QPushButton#VersionChip {
    background-color: $input;
    border: 1px solid $input_border;
    border-radius: 9px;
    padding: 5px 11px;
    color: $text_secondary;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#VersionChip:hover {
    border-color: $accent_border;
    color: $text;
    background-color: $accent_soft;
}
QPushButton#ProviderTile {
    background-color: rgba(255, 255, 255, 6);
    border: 1px solid $border;
    border-radius: 14px;
    padding: 0px;
    text-align: left;
}
QPushButton#ProviderTile:hover {
    background-color: $panel_hover;
    border-color: $accent_border;
}
QLabel#ProviderTitle {
    font-size: 14px;
    font-weight: 600;
    color: $text;
}
QLabel#ProviderSubtitle {
    font-size: 11px;
    color: $text_muted;
}
QPushButton#UpdatePill {
    background-color: $accent_soft;
    border: 1px solid $accent_border;
    border-radius: 9px;
    color: $accent_light;
    font-size: 10px;
    font-weight: 600;
    padding: 5px 10px;
}
QPushButton#UpdatePill:hover {
    color: $text;
    border-color: $accent;
}
QPushButton#InstanceCard {
    background-color: $panel;
    border: 1px solid $border;
    border-radius: 17px;
    padding: 0px;
    text-align: left;
}
QPushButton#ModCard {
    background-color: $panel;
    border: 1px solid $border;
    border-radius: 15px;
    padding: 0px;
    text-align: left;
}
QPushButton#PrimaryButton {
    background-color: $accent;
    border: 1px solid $accent;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover {
    background-color: $accent_light;
}
QLabel#GalleryThumb {
    background-color: $input;
    border: 1px solid $border;
    border-radius: 12px;
    color: $text_muted;
}
QWidget#GallerySurface {
    background-color: transparent;
}
QFrame#VersionCard {
    background-color: rgba(255, 255, 255, 5);
    border: 1px solid $border;
    border-radius: 11px;
}
QFrame#VersionCard:hover {
    border-color: $accent_border;
    background-color: $panel_hover;
}
QFrame#DetailHero {
    background-color: $panel;
    border: 1px solid $accent_border;
    border-radius: 18px;
}
QFrame#DetailHero QLabel#PageTitle {
    font-size: 30px;
    font-weight: 700;
}
QFrame#StoreBanner {
    background-color: $panel;
    border: 1px solid $accent_border;
    border-radius: 18px;
}
QLabel#BannerTitle {
    font-size: 25px;
    font-weight: 700;
    color: $text;
}
QLabel#PremiumCrown {
    color: #FFD166;
    font-size: 15px;
    font-weight: 700;
}
QFrame#DownloadRow {
    background-color: rgba(255, 255, 255, 6);
    border: 1px solid $border;
    border-radius: 10px;
}
QPushButton#ModCard:hover {
    background-color: $panel_hover;
    border-color: $accent_border;
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
QLabel#ModCardStatus[state="working"] {
    color: $accent_light;
}
QLabel#ModCardStatus[state="done"] {
    color: $success;
}
QLabel#ModCardStatus[state="error"] {
    color: $danger;
}
QTabWidget#ContentTabs::pane {
    background-color: $panel_solid;
    border: 1px solid $border;
    border-radius: 12px;
    top: -1px;
}
QTabWidget#ContentTabs QTabBar::tab {
    background-color: $panel;
    color: $text_secondary;
    border: 1px solid $border;
    padding: 8px 16px;
    margin-right: 4px;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
}
QTabWidget#ContentTabs QTabBar::tab:selected {
    background-color: $panel_solid;
    color: $text;
    border-color: $accent_border;
}
QTextBrowser#ModBody {
    background-color: $panel_solid;
    border: 1px solid $border;
    border-radius: 12px;
    color: $text_secondary;
    padding: 10px;
}
QListWidget#Playlist {
    background-color: $input;
    border: 1px solid $border;
    border-radius: 11px;
    color: $text_secondary;
    padding: 4px;
}
QListWidget#Playlist::item {
    border-radius: 7px;
    padding: 6px 8px;
    min-height: 26px;
}
QListWidget#Playlist::item:hover {
    background-color: $accent_soft;
}
QListWidget#Playlist::item:selected {
    background-color: $accent_soft;
    color: $text;
}
QPushButton#InstanceCard:hover {
    background-color: $panel_hover;
    border-color: $accent_border;
}
QPushButton#InstanceCard:pressed {
    background-color: $accent_soft;
}
QPushButton#CoreTile {
    background-color: rgba(255, 255, 255, 6);
    border: 1px solid $border;
    border-radius: 15px;
    padding: 0px;
    text-align: left;
}
QPushButton#CoreTile:hover {
    background-color: rgba(255, 255, 255, 14);
    border-color: $border_strong;
}
QPushButton#CoreTile:checked {
    background-color: $accent_soft;
    border: 2px solid $accent;
}
QPushButton#CoreTile:disabled {
    background-color: rgba(255, 255, 255, 3);
    border-color: $border;
}
QPushButton#ContentTile {
    background-color: $panel;
    border: 1px solid $border;
    border-radius: 17px;
    padding: 0px;
    text-align: left;
}
QPushButton#ContentTile:hover {
    background-color: $panel_hover;
    border-color: $accent_border;
}
QPushButton#ContentTile:pressed {
    background-color: $accent_soft;
}
QPushButton#TabButton {
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0px;
    padding: 8px 12px;
    color: $text_muted;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#TabButton:hover {
    color: $text_secondary;
}
QPushButton#TabButton:checked {
    color: $text;
    border-bottom: 2px solid $accent;
}
QPushButton#TabButton:disabled {
    color: rgba(128, 124, 150, 110);
}
QFrame#ContentRow {
    background-color: rgba(255, 255, 255, 4);
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#ContentRow:hover {
    background-color: rgba(255, 255, 255, 9);
    border-color: $border_strong;
}
QFrame#ContentRow[disabled="true"] {
    background-color: rgba(255, 255, 255, 3);
    border-color: $border;
}
QFrame#ContentRow[disabled="true"] QLabel#ContentFileName {
    color: $text_muted;
}
QLabel#CoreTileTitle {
    font-size: 15px;
    font-weight: 600;
    color: $text;
}
QLabel#CoreTileSubtitle {
    font-size: 11px;
    color: $text_muted;
}
QLabel#ContentTileTitle {
    font-size: 14px;
    font-weight: 600;
    color: $text;
}
QLabel#ContentTileCount {
    font-size: 20px;
    font-weight: 600;
    color: $accent_light;
}
QLabel#ContentFileName {
    font-size: 13px;
    font-weight: 500;
    color: $text;
}
QLabel#ContentFileMeta {
    font-size: 11px;
    color: $text_muted;
}
QLabel#ContentFileStatus {
    font-size: 10px;
    font-weight: 600;
    color: $success;
}
QLabel#ContentFileStatus[state="off"] {
    color: $text_muted;
}
QLabel#ContentFileStatus[state="error"] {
    color: $danger;
}
QFrame#ContentEmpty {
    background-color: rgba(255, 255, 255, 3);
    border: 1px dashed $border_strong;
    border-radius: 14px;
}

/* ============================== inputs ============================== */
QLineEdit, QSpinBox {
    background-color: $input;
    color: $text;
    border: 1px solid $input_border;
    border-radius: 10px;
    padding: 9px 12px;
    font-size: 13px;
    selection-background-color: $accent;
    selection-color: #FFFFFF;
}
QLineEdit:hover, QSpinBox:hover {
    border-color: $border_strong;
}
QLineEdit:focus, QSpinBox:focus {
    border-color: $accent_border;
    background-color: rgba(255, 255, 255, 16);
}
QLineEdit:disabled, QSpinBox:disabled {
    color: $text_muted;
    background-color: rgba(255, 255, 255, 4);
    border-color: $border;
}
QLineEdit[readOnly="true"] {
    color: $text_secondary;
    background-color: rgba(255, 255, 255, 6);
}

QComboBox {
    background-color: $input;
    color: $text;
    border: 1px solid $input_border;
    border-radius: 10px;
    padding: 8px 34px 8px 12px;
    min-height: 21px;
    font-size: 13px;
}
QComboBox:hover {
    border-color: $border_strong;
}
QComboBox:focus, QComboBox:on {
    border-color: $accent_border;
}
QComboBox::drop-down {
    border: none;
    width: 30px;
}
QComboBox::down-arrow {
    image: none;
    width: 0px;
    height: 0px;
}
QComboBox QAbstractItemView {
    background-color: $panel_solid;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: 10px;
    padding: 6px;
    outline: none;
    selection-background-color: $accent_soft;
    selection-color: $text;
}
QComboBox QAbstractItemView::item {
    min-height: 30px;
    border-radius: 7px;
    padding-left: 8px;
}
QComboBox QAbstractItemView::item:hover {
    background-color: $input;
}

QSlider {
    background: transparent;
}
QSlider::groove:horizontal {
    height: 5px;
    background-color: rgba(255, 255, 255, 22);
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent, stop:1 $accent_2);
    border-radius: 3px;
}
QSlider::add-page:horizontal {
    background-color: rgba(255, 255, 255, 18);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
    background-color: #FBFAFF;
    border: 3px solid $accent;
}
QSlider::handle:horizontal:hover {
    margin: -7px 0;
    border: 4px solid $accent_light;
    background-color: #FFFFFF;
}

QProgressBar {
    background-color: rgba(255, 255, 255, 18);
    border: none;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    border-radius: 4px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent, stop:1 $accent_2);
}

QCheckBox {
    color: $text_secondary;
    spacing: 9px;
    font-size: 13px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1px solid $input_border;
    background-color: $input;
}
QCheckBox::indicator:hover {
    border-color: $accent_border;
}
QCheckBox::indicator:checked {
    background-color: $accent;
    border-color: $accent;
}

/* ============================== scroll ============================== */
QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 4px 1px;
}
QScrollBar::handle:vertical {
    background-color: rgba(255, 255, 255, 34);
    border-radius: 4px;
    min-height: 36px;
}
QScrollBar::handle:vertical:hover {
    background-color: rgba(255, 255, 255, 58);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: transparent;
    height: 9px;
    margin: 1px 4px;
}
QScrollBar::handle:horizontal {
    background-color: rgba(255, 255, 255, 34);
    border-radius: 4px;
    min-width: 36px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

/* ============================== misc ============================== */
QMenu {
    background-color: $panel_solid;
    color: $text;
    border: 1px solid $border_strong;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    border-radius: 6px;
    padding: 6px 18px 6px 10px;
}
QMenu::item:selected {
    background-color: $accent_soft;
}
"""
)


def build_stylesheet(theme: Theme | None = None) -> str:
    theme = theme or _current
    return _QSS.substitute(theme.qss_vars())
