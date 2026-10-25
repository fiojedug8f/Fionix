"""Small, dependency-free UI translation helper for Russian/English."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QLabel, QTabWidget, QWidget

EN: dict[str, str] = {
    "Главная": "Home",
    "Магазин": "Store",
    "Настройки": "Settings",
    "НАВИГАЦИЯ": "NAVIGATION",
    "ЭКЗЕМПЛЯРЫ": "INSTANCES",
    "Экземпляры": "Instances",
    "Создать экземпляр": "Create instance",
    "Импорт .fionixpack": "Import .fionixpack",
    "Открыть папку игры": "Open game folder",
    "Соберите свой идеальный мир": "Build your perfect world",
    "Соберите свою коллекцию миров — всё под рукой.": "Build your world collection — all in one place.",
    "Создайте первую сборку и начните своё приключение.": "Create your first instance and start playing.",
    "Ваши экземпляры": "Your instances",
    "Пока здесь пусто": "Nothing here yet",
    "Карточки сборок появятся здесь": "Your instances will appear here",
    "Смотреть сборку": "View modpack",
    "Подробнее": "Details",
    "РЕКОМЕНДАЦИЯ": "RECOMMENDED",
    "Модпаки": "Modpacks",
    "Моды": "Mods",
    "Текстурпаки": "Resource packs",
    "Шейдеры": "Shaders",
    "Карты": "Maps",
    "Играть": "Play",
    "Загрузить": "Download",
    "Загрузка": "Loading",
    "Установить": "Install",
    "Установленные": "Installed",
    "Маркет": "Market",
    "Описание": "Description",
    "Галерея": "Gallery",
    "Версии": "Versions",
    "Назад": "Back",
    "Готово": "Done",
    "Отмена": "Cancel",
    "Сохранить": "Save",
    "Создать": "Create",
    "Настройки экземпляра": "Instance settings",
    "Настройки экземпляра": "Instance settings",
    "Открыть папку": "Open folder",
    "Поделиться": "Share",
    "Удалить экземпляр": "Delete instance",
    "Бэкап": "Backup",
    "Внешний вид": "Appearance",
    "Аккаунты": "Accounts",
    "Производительность": "Performance",
    "Java": "Java",
    "Прокси": "Proxy",
    "Данные": "Data",
    "О программе": "About",
    "Тема оформления": "Color theme",
    "Акцентный цвет": "Accent color",
    "Авто-контраст": "Auto contrast",
    "Фон лаунчера": "Launcher background",
    "Громкость видео-фона": "Video background volume",
    "Язык интерфейса": "Interface language",
    "Русский": "Russian",
    "Английский": "English",
    "Профиль": "Profile",
    "Активный аккаунт": "Active account",
    "Изменить ник": "Change nickname",
    "Загрузить PNG": "Upload PNG",
    "Классический (Стив)": "Classic (Steve)",
    "Тонкий (Алекс)": "Slim (Alex)",
    "Плащи Microsoft": "Microsoft capes",
    "Снять плащ": "Remove cape",
    "Закрыть": "Close",
    "Сначала создайте экземпляр в библиотеке.": "Create an instance in the library first.",
    "Сначала создайте экземпляр в библиотеке.": "Create an instance in the library first.",
    "Нет экземпляров": "No instances",
    "Куда установить?": "Where should it go?",
    "Выберите экземпляр": "Choose an instance",
    "Несовместимо": "Incompatible",
    "Поиск модов…": "Search mods…",
    "Найти": "Search",
    "Страница": "Page",
    "показано": "shown",
    "Загрузка рекомендаций…": "Loading recommendations…",
    "У вас пока нет сборок": "You have no instances yet",
}

PREFIXES = {
    "Добро пожаловать, ": "Welcome, ",
}


def translate(text: str, language: str) -> str:
    if language != "en":
        return text
    if text in EN:
        return EN[text]
    for prefix, replacement in PREFIXES.items():
        if text.startswith(prefix):
            return replacement + text[len(prefix):]
    return text


def apply_language(root: QWidget, language: str) -> None:
    """Translate static labels/buttons and restore Russian when switching back."""
    for widget in root.findChildren(QWidget):
        if isinstance(widget, (QAbstractButton, QLabel)):
            original = widget.property("i18n_ru")
            if original is None:
                original = widget.text()
                widget.setProperty("i18n_ru", original)
            desired = original if language != "en" else translate(str(original), language)
            if widget.text() != desired:
                widget.setText(desired)
        elif isinstance(widget, QTabWidget):
            originals = widget.property("i18n_tabs")
            if originals is None:
                originals = [widget.tabText(i) for i in range(widget.count())]
                widget.setProperty("i18n_tabs", originals)
            for index, original in enumerate(originals):
                desired = original if language != "en" else translate(original, language)
                if widget.tabText(index) != desired:
                    widget.setTabText(index, desired)
