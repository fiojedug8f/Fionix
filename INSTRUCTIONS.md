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

Ключ создаётся на <https://console.curseforge.com/> и задаётся **только** в
корневом `config.py`:

```python
CURSEFORGE_API_KEY = "..."
```

Поля в UI для игрока нет. При пустом ключе CurseForge скрыт, Modrinth
продолжает работать.

## Сборка EXE

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
pyinstaller Fionix.spec
.\dist\Fionix\Fionix.exe
```

## Обновления

В корневом `config.py` задайте:

```python
GITHUB_REPO = "owner/repo"
```

Релиз должен содержать `.exe`-asset. Пока `GITHUB_REPO` равно `"пока нету"`,
сетевые запросы обновления не выполняются.

## Проверки

```powershell
python -m unittest discover -s tests -v
python tools/smoke_test.py
python tools/screenshot.py
```
