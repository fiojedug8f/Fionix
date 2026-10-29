# Fionix — технические инструкции

Этот файл предназначен для разработчика/сборщика. Пользовательский README
содержит только описание продукта.

## Microsoft OAuth

OAuth-параметры находятся в корневом `config.py`:

```python
CLIENT_ID = "..."
CLIENT_SECRET = "..."
REDIRECT_URL = "http://localhost"
```

В Microsoft Entra ID:

1. Создайте приложение **App registrations**.
2. В **Supported account types** выберите
   **«Accounts in any organizational directory and personal Microsoft accounts»**.
3. В **Authentication → Add a platform → Mobile and desktop applications**
   добавьте redirect URI:
   - `http://localhost` — базовый адрес из `config.py`; Fionix слушает
     loopback-порт 80;
   - `http://localhost:53682` — резервный вариант, если вы явно укажете
     этот порт в `REDIRECT_URL` (или используете ручной ввод кода).
   Redirect URI в Azure должен совпадать с `REDIRECT_URL`.
4. В коде используется authority `consumers`, поэтому поддерживаются личные
   consumer-аккаунты.
5. Scope: `XboxLive.signin offline_access`.
6. После получения authorization code лаунчер обменивает его на Microsoft
   token, проходит Xbox Live/XSTS и получает Minecraft access token.
   Приложение зарегистрировано как **public client**, поэтому `client_secret`
   в token-запросе не отправляется — иначе Microsoft вернёт `AADSTS90023`
   и аннулирует код.

`CLIENT_SECRET` оставлен в конфигурации только для совместимости; для
публичного desktop-клиента он не используется.

Браузер открывается через системный обработчик Windows (`QDesktopServices`).
Если окно не появилось, закройте старые экземпляры Fionix (они могут держать
порт 80), проверьте браузер по умолчанию и нажмите «Открыть страницу входа».
Если браузер не вернул управление, вставьте полный redirect URL или сам `code`
вручную; код действует около 10 минут.

`CLIENT_SECRET` не нужен public-клиенту и не должен публиковаться в открытом
репозитории.

## Одобрение Client ID для Minecraft Services

Ошибка:

```text
403 Invalid app registration
```

не лечится настройками Entra. Microsoft OAuth, Xbox Live и XSTS могут
проходить успешно, но `api.minecraftservices.com` принимает только Client ID
из allowlist Minecraft. Нужно подать заявку на одобрение приложения:

<https://aka.ms/AppRegInfo>

После одобрения Mojang тот же Client ID начнёт работать без изменений в
лаунчере. До одобрения вход Microsoft в сторонний лаунчер невозможен.

## CurseForge

Ключ CurseForge **не хранится в лаунчере**. Запросы идут через собственный
Cloudflare Worker, который подставляет серверный ключ (`x-api-key`) сам:

1. Разверните воркер с ключом CurseForge (см. <https://console.curseforge.com/>).
2. Пропишите его адрес в корневом `config.py`:

```python
# можно с /v1 или без — лаунчер нормализует сам
CURSEFORGE_API_KEY = "https://fionix-cf.<ваш-аккаунт>.workers.dev"
```

В репозитории прописан рабочий воркер Fionix, поэтому CurseForge работает сразу
после клонирования. Свой воркер подставляется заменой этой строки; пустое
значение полностью отключает вкладку (Modrinth продолжает работать).
Поля в UI для игрока нет.

Если воркер требует Chrome-TLS (Cloudflare), лаунчер использует `curl_cffi`;
без него остаётся обычный `requests`.

## Сборка EXE

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
pyinstaller Fionix.spec
.\dist\Fionix.exe
```

`Fionix.spec` сам подхватывает необязательные вещи, если они есть:

- `.deps/` — локальный `pip install --target .deps` (офлайн-сборка);
- `curl_cffi`, `keyboard`, `pywin32` — попадают в exe, если установлены;
- `assets/fionix.manifest` — манифест Windows (DPI).

Установщик (без прав администратора, ставит в `%LOCALAPPDATA%\Programs\Fionix`):

```powershell
pyinstaller Fionix.spec --distpath release-onefile
pyinstaller Fionix_Setup.spec --distpath release-installer
```

## Обновления

В корневом `config.py` задайте:

```python
GITHUB_REPO = "owner/repo"
```

Релиз должен содержать `.exe`-asset. Пока `GITHUB_REPO` не задан, сетевые
запросы обновления не выполняются.

## Проверки

```powershell
python -m unittest discover -s tests -v
python tools/smoke_test.py
python tools/screenshot.py
```
