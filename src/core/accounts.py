"""Account storage and Yggdrasil logins for Fionix.

Only tokens are persisted — passwords are never written to disk.  Microsoft
OAuth needs a registered client id; the constant below is intentionally a
placeholder because a real id must belong to the launcher publisher.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, quote, urlparse

import requests

from config import (
    CLIENT_ID,
    MICROSOFT_AUTHORITY,
    MICROSOFT_SCOPE,
    MINECRAFT_APP_REGISTRATION_URL,
    REDIRECT_URL,
)
from src.core.launcher import offline_uuid

logger = logging.getLogger(__name__)

ACCOUNTS_FILE = "accounts.json"
PROVIDER_LABELS = {
    "microsoft": "Microsoft",
    "littleskin": "LittleSkin",
    "elyby": "Ely.by",
    "guest": "Гость",
}
PROVIDER_ICONS = {
    "microsoft": "windows",
    "littleskin": "skin",
    "elyby": "globe",
    "guest": "user",
}

MICROSOFT_AUTHORIZE_URL = f"{MICROSOFT_AUTHORITY}/authorize"
MICROSOFT_TOKEN_URL = f"{MICROSOFT_AUTHORITY}/token"
MINECRAFT_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
MINECRAFT_SKINS_URL = "https://api.minecraftservices.com/minecraft/profile/skins"
MINECRAFT_CAPES_URL = "https://api.minecraftservices.com/minecraft/profile/capes"
_MICROSOFT_REDIRECT_URI = REDIRECT_URL.strip().rstrip("/")
_EXCHANGE_LOCK = threading.Lock()
_EXCHANGE_IN_PROGRESS = False
_EXCHANGED_CODES: set[str] = set()

LITTLESKIN_AUTH = "https://littleskin.cn/api/yggdrasil/authserver/authenticate"
LITTLESKIN_PROFILE = (
    "https://littleskin.cn/api/yggdrasil/sessionserver/session/minecraft/profile/{uuid}"
)
ELYSKIN_AUTH = "https://authserver.ely.by/auth/authenticate"
ELYSKIN_PROFILE = "https://authserver.ely.by/api/users/profiles/minecraft/{name}"
ELYSKIN_SKIN = "https://skinsystem.ely.by/skins/{name}.png"

HTTP_HEADERS = {"User-Agent": "Fionix/1.0 (Minecraft launcher)"}


class AccountError(Exception):
    """A login/storage error whose text is safe to show to the player."""


@dataclass
class Account:
    id: str
    provider: str
    username: str
    uuid: str = ""
    access_token: str = ""
    skin_url: str = ""
    created_at: str = ""
    email: str = ""
    skin_variant: str = "classic"

    @property
    def provider_label(self) -> str:
        return PROVIDER_LABELS.get(self.provider, self.provider)

    @property
    def display_name(self) -> str:
        return self.username or self.provider_label

    @property
    def is_guest(self) -> bool:
        return self.provider == "guest"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "username": self.username,
            "uuid": self.uuid,
            "access_token": self.access_token,
            "skin_url": self.skin_url,
            "created_at": self.created_at,
            "email": self.email,
            "skin_variant": self.skin_variant,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Account":
        provider = str(raw.get("provider") or "guest")
        if provider not in PROVIDER_LABELS:
            provider = "guest"
        username = str(raw.get("username") or "FionixPlayer")[:32]
        account_uuid = str(raw.get("uuid") or offline_uuid(username))
        return cls(
            id=str(raw.get("id") or uuid.uuid4().hex),
            provider=provider,
            username=username,
            uuid=account_uuid,
            access_token=str(raw.get("access_token") or ""),
            skin_url=str(raw.get("skin_url") or ""),
            created_at=str(raw.get("created_at") or _now_iso()),
            email=str(raw.get("email") or ""),
            skin_variant=(
                "slim" if str(raw.get("skin_variant") or "").lower() == "slim" else "classic"
            ),
        )


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class AccountManager:
    """Persist multiple accounts and the currently selected one."""

    def __init__(self, data_dir: Path | str) -> None:
        self.path = Path(data_dir) / ACCOUNTS_FILE
        self._lock = threading.RLock()
        self.accounts: list[Account] = []
        self.active_id: str = ""
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read accounts: %s", exc)
            return
        if not isinstance(raw, Mapping):
            return
        accounts: list[Account] = []
        for item in raw.get("accounts", []):
            if isinstance(item, Mapping):
                accounts.append(Account.from_dict(item))
        self.accounts = accounts
        active = str(raw.get("active_id") or "")
        self.active_id = active if any(item.id == active for item in accounts) else (
            accounts[0].id if accounts else ""
        )

    def save(self) -> bool:
        with self._lock:
            try:
                _atomic_write(
                    self.path,
                    {
                        "active_id": self.active_id,
                        "accounts": [account.to_dict() for account in self.accounts],
                    },
                )
                return True
            except OSError as exc:
                logger.error("Could not save accounts: %s", exc)
                return False

    @property
    def current(self) -> Account | None:
        return next(
            (item for item in self.accounts if item.id == self.active_id), None
        )

    def get(self, account_id: str) -> Account | None:
        return next((item for item in self.accounts if item.id == account_id), None)

    def add(self, account: Account, *, make_active: bool = True) -> Account:
        with self._lock:
            if not account.uuid:
                account.uuid = offline_uuid(account.username)
            self.accounts.append(account)
            if make_active or not self.active_id:
                self.active_id = account.id
            self.save()
        return account

    def remove(self, account_id: str) -> bool:
        with self._lock:
            before = len(self.accounts)
            self.accounts = [item for item in self.accounts if item.id != account_id]
            if len(self.accounts) == before:
                return False
            if self.active_id == account_id:
                self.active_id = self.accounts[0].id if self.accounts else ""
            self.save()
        return True

    def set_active(self, account_id: str) -> bool:
        if not any(item.id == account_id for item in self.accounts):
            return False
        self.active_id = account_id
        self.save()
        return True

    def ensure_guest(self, username: str = "FionixPlayer") -> Account:
        current = self.current
        if current is not None:
            return current
        return self.add(create_guest(username))

    def update_skin(self, account_id: str, skin_url: str) -> None:
        account = self.get(account_id)
        if account is None:
            return
        account.skin_url = skin_url
        self.save()

    def set_skin_variant(self, account_id: str, variant: str) -> None:
        account = self.get(account_id)
        if account is None:
            return
        account.skin_variant = "slim" if variant == "slim" else "classic"
        self.save()

    def rename_guest(self, account_id: str, username: str) -> bool:
        account = self.get(account_id)
        name = (username or "").strip()
        if account is None or account.provider != "guest":
            return False
        if not 3 <= len(name) <= 16 or not all(ch.isalnum() or ch == "_" for ch in name):
            return False
        account.username = name
        account.uuid = offline_uuid(name)
        self.save()
        return True


def _minecraft_headers(account: Account) -> dict[str, str]:
    if account.provider != "microsoft" or not account.access_token:
        raise AccountError("Для скинов и плащей нужен аккаунт Microsoft.")
    return {
        **HTTP_HEADERS,
        "Authorization": f"Bearer {account.access_token}",
        "Accept": "application/json",
    }


def fetch_minecraft_profile(account: Account) -> dict[str, Any]:
    try:
        response = requests.get(
            MINECRAFT_PROFILE_URL,
            headers=_minecraft_headers(account),
            timeout=(10, 30),
        )
    except requests.RequestException as exc:
        raise AccountError("Не удалось получить профиль Minecraft.") from exc
    if response.status_code == 401:
        raise AccountError("Токен Microsoft истёк. Войдите в аккаунт снова.")
    if response.status_code >= 400:
        raise AccountError(f"Minecraft профиль недоступен (HTTP {response.status_code}).")
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise AccountError("Minecraft вернул некорректный профиль.")
    return dict(payload)


def upload_minecraft_skin(
    account: Account, skin_path: Path | str, variant: str = "classic"
) -> dict[str, Any]:
    path = Path(skin_path)
    if not path.is_file():
        raise AccountError("Файл скина не найден.")
    variant = variant if variant in {"classic", "slim"} else "classic"
    try:
        response = requests.post(
            MINECRAFT_SKINS_URL,
            headers=_minecraft_headers(account),
            files={"file": (path.name, path.read_bytes(), "image/png")},
            data={"variant": variant},
            timeout=(10, 45),
        )
    except requests.RequestException as exc:
        raise AccountError("Не удалось загрузить скин на Minecraft.") from exc
    if response.status_code >= 400:
        raise AccountError(
            f"Minecraft отклонил скин (HTTP {response.status_code}): "
            f"{response.text[:200]}"
        )
    return fetch_minecraft_profile(account)


def set_minecraft_cape(account: Account, cape_id: str | None) -> dict[str, Any]:
    try:
        if cape_id:
            response = requests.put(
                f"{MINECRAFT_CAPES_URL}/active",
                headers=_minecraft_headers(account),
                json={"capeId": cape_id},
                timeout=(10, 30),
            )
        else:
            response = requests.delete(
                f"{MINECRAFT_CAPES_URL}/active",
                headers=_minecraft_headers(account),
                timeout=(10, 30),
            )
    except requests.RequestException as exc:
        raise AccountError("Не удалось изменить плащ Minecraft.") from exc
    if response.status_code >= 400:
        raise AccountError(f"Minecraft отклонил плащ (HTTP {response.status_code}).")
    return fetch_minecraft_profile(account)


def create_guest(username: str = "FionixPlayer") -> Account:
    name = (username or "FionixPlayer").strip()[:16] or "FionixPlayer"
    return Account(
        id=uuid.uuid4().hex,
        provider="guest",
        username=name,
        uuid=offline_uuid(name),
        created_at=_now_iso(),
    )


def _post_yggdrasil(
    url: str, username: str, password: str, *, client_token: str
) -> Mapping[str, Any]:
    payload = {
        "agent": {"name": "Minecraft", "version": 1},
        "username": username,
        "password": password,
        "clientToken": client_token,
        "requestUser": True,
    }
    try:
        response = requests.post(
            url,
            json=payload,
            headers=HTTP_HEADERS,
            timeout=(10, 30),
        )
    except requests.RequestException as exc:
        raise AccountError("Нет связи с сервером авторизации.") from exc
    if response.status_code == 403:
        raise AccountError("Неверный логин или пароль.")
    if response.status_code >= 400:
        raise AccountError(
            f"Сервер авторизации вернул ошибку {response.status_code}."
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise AccountError("Сервер авторизации вернул некорректный ответ.") from exc
    if not isinstance(data, Mapping) or not data.get("accessToken"):
        message = data.get("errorMessage") if isinstance(data, Mapping) else ""
        raise AccountError(str(message or "Не удалось войти в аккаунт."))
    return data


def login_littleskin(username: str, password: str) -> Account:
    username = username.strip()
    if not username or not password:
        raise AccountError("Введите логин и пароль.")
    data = _post_yggdrasil(
        LITTLESKIN_AUTH, username, password, client_token=uuid.uuid4().hex
    )
    profile = data.get("selectedProfile")
    if not isinstance(profile, Mapping):
        raise AccountError("У аккаунта LittleSkin нет выбранного профиля.")
    name = str(profile.get("name") or username)
    account_uuid = str(profile.get("id") or offline_uuid(name))
    return Account(
        id=uuid.uuid4().hex,
        provider="littleskin",
        username=name,
        uuid=account_uuid,
        access_token=str(data.get("accessToken") or ""),
        skin_url=LITTLESKIN_PROFILE.format(uuid=quote(account_uuid)),
        created_at=_now_iso(),
    )


def login_elyby(username: str, password: str) -> Account:
    username = username.strip()
    if not username or not password:
        raise AccountError("Введите логин и пароль.")
    data = _post_yggdrasil(
        ELYSKIN_AUTH, username, password, client_token=uuid.uuid4().hex
    )
    profile = data.get("selectedProfile")
    if not isinstance(profile, Mapping):
        raise AccountError("У аккаунта Ely.by нет выбранного профиля.")
    name = str(profile.get("name") or username)
    account_uuid = str(profile.get("id") or offline_uuid(name))
    return Account(
        id=uuid.uuid4().hex,
        provider="elyby",
        username=name,
        uuid=account_uuid,
        access_token=str(data.get("accessToken") or ""),
        skin_url=ELYSKIN_SKIN.format(name=quote(name)),
        created_at=_now_iso(),
    )


def microsoft_login_url(state: str = "", redirect_uri: str | None = None) -> str:
    redirect = _MICROSOFT_REDIRECT_URI if redirect_uri is None else redirect_uri
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect,
        "response_mode": "query",
        "scope": MICROSOFT_SCOPE,
        "prompt": "select_account",
    }
    if state:
        params["state"] = state
    query = "&".join(f"{quote(key)}={quote(value)}" for key, value in params.items())
    return f"{MICROSOFT_AUTHORIZE_URL}?{query}"


def _microsoft_token_exchange(code: str, redirect_uri: str) -> str:
    global _EXCHANGE_IN_PROGRESS
    redirect_uri = _MICROSOFT_REDIRECT_URI
    code = code.strip()
    code_key = hashlib.sha256(code.encode("utf-8")).hexdigest()
    with _EXCHANGE_LOCK:
        if _EXCHANGE_IN_PROGRESS:
            raise AccountError("Обмен кода Microsoft уже выполняется.")
        if code_key in _EXCHANGED_CODES:
            raise AccountError(
                "Этот код Microsoft уже использован. Получите новый код."
            )
        _EXCHANGE_IN_PROGRESS = True
        _EXCHANGED_CODES.add(code_key)
    try:
        logger.info(
            "Microsoft token request: client_id=%s redirect_uri=%r "
            "grant_type=authorization_code code=%r",
            CLIENT_ID,
            redirect_uri,
            code,
        )
        response = requests.post(
            MICROSOFT_TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                # Public desktop client: no client_secret (AADSTS90023).
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "scope": MICROSOFT_SCOPE,
            },
            headers=HTTP_HEADERS,
            timeout=(10, 30),
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text[:1000]}
        log_payload = payload
        if response.status_code < 400 and isinstance(payload, Mapping):
            log_payload = {
                key: ("<redacted>" if key in {"access_token", "refresh_token", "id_token"} else value)
                for key, value in payload.items()
            }
        logger.info(
            "Microsoft token response: status=%s payload=%s",
            response.status_code,
            log_payload,
        )
        if response.status_code >= 400:
            detail = payload.get("error_description") or payload.get("error") or ""
            raise AccountError(f"Microsoft отклонил авторизацию. {detail}".strip())
        token = str(payload.get("access_token") or "")
        if not token:
            raise AccountError("Microsoft не вернул access token.")
        return token
    except requests.RequestException as exc:
        raise AccountError("Нет связи с Microsoft OAuth.") from exc
    finally:
        with _EXCHANGE_LOCK:
            _EXCHANGE_IN_PROGRESS = False


def _xbox_authenticate(ms_access_token: str) -> tuple[str, str]:
    try:
        xbox_response = requests.post(
            "https://user.auth.xboxlive.com/user/authenticate",
            json={
                "Properties": {
                    "AuthMethod": "RPS",
                    "SiteName": "user.auth.xboxlive.com",
                    "RpsTicket": f"d={ms_access_token}",
                },
                "RelyingParty": "http://auth.xboxlive.com",
                "TokenType": "JWT",
            },
            headers=HTTP_HEADERS,
            timeout=(10, 30),
        )
        logger.info("Xbox user auth: status=%s", xbox_response.status_code)
        if xbox_response.status_code >= 400:
            raise AccountError(
                f"Xbox Live отклонил вход Microsoft (HTTP {xbox_response.status_code})."
            )
        xbox = xbox_response.json()
        xsts_response = requests.post(
            "https://xsts.auth.xboxlive.com/xsts/authorize",
            json={
                "Properties": {
                    "SandboxId": "RETAIL",
                    "UserTokens": [xbox["Token"]],
                },
                "RelyingParty": "rp://api.minecraftservices.com/",
                "TokenType": "JWT",
            },
            headers=HTTP_HEADERS,
            timeout=(10, 30),
        )
        logger.info(
            "XSTS auth: status=%s body=%s",
            xsts_response.status_code,
            xsts_response.text[:800],
        )
        if xsts_response.status_code == 401:
            try:
                xerr = int(xsts_response.json().get("XErr", 0))
            except (ValueError, AttributeError):
                xerr = 0
            if xerr == 2148916233:
                raise AccountError(
                    "У аккаунта Microsoft нет Xbox-профиля. "
                    "Создайте его на xbox.com, затем повторите вход."
                )
            if xerr in {2148916238, 2148916236, 2148916237}:
                raise AccountError(
                    "Аккаунт Xbox является детским или требует согласия "
                    "родителя. Проверьте семейные настройки Xbox."
                )
            if xerr == 2148916235:
                raise AccountError(
                    "Xbox Live недоступен в регионе этого аккаунта."
                )
            raise AccountError(
                f"XSTS отклонил вход (XErr={xerr or 'неизвестно'}). "
                "Проверьте профиль Xbox."
            )
        xsts_response.raise_for_status()
        xsts = xsts_response.json()
        uhs = xbox["DisplayClaims"]["xui"][0]["uhs"]
        return str(uhs), str(xsts["Token"])
    except KeyError as exc:
        raise AccountError("Microsoft вернул неполный профиль Xbox.") from exc
    except requests.RequestException as exc:
        raise AccountError("Не удалось авторизоваться в Xbox Live.") from exc


def login_microsoft_code(code: str, redirect_uri: str | None = None) -> Account:
    code = code.strip()
    if not code:
        raise AccountError("Код авторизации Microsoft пуст.")
    redirect = _MICROSOFT_REDIRECT_URI
    ms_token = _microsoft_token_exchange(code, redirect)
    uhs, xsts_token = _xbox_authenticate(ms_token)
    try:
        mc_response = requests.post(
            "https://api.minecraftservices.com/authentication/login_with_xbox",
            json={"identityToken": f"XBL3.0 x={uhs};{xsts_token}"},
            headers=HTTP_HEADERS,
            timeout=(10, 30),
        )
        logger.info(
            "Minecraft login_with_xbox: status=%s body=%s",
            mc_response.status_code,
            mc_response.text[:800],
        )
        if mc_response.status_code == 403 and "invalid app registration" in mc_response.text.lower():
            raise AccountError(
                "Minecraft отклонил Client ID приложения (403 Invalid app registration). "
                "Нужно добавить Client ID в allowlist Minecraft: "
                f"{MINECRAFT_APP_REGISTRATION_URL}"
            )
        if mc_response.status_code >= 400:
            raise AccountError(
                f"Minecraft Services отклонил Xbox-токен "
                f"(HTTP {mc_response.status_code})."
            )
        mc = mc_response.json()
        mc_token = str(mc.get("access_token") or "")
        if not mc_token:
            raise AccountError("Minecraft не выдал токен для Microsoft-аккаунта.")
        profile_response = requests.get(
            "https://api.minecraftservices.com/minecraft/profile",
            headers={**HTTP_HEADERS, "Authorization": f"Bearer {mc_token}"},
            timeout=(10, 30),
        )
        logger.info(
            "Minecraft profile: status=%s body=%s",
            profile_response.status_code,
            profile_response.text[:800],
        )
        if profile_response.status_code == 404:
            raise AccountError(
                "У аккаунта Microsoft нет купленной Minecraft Java Edition."
            )
        if profile_response.status_code >= 400:
            raise AccountError(
                f"Профиль Minecraft недоступен "
                f"(HTTP {profile_response.status_code})."
            )
        profile = profile_response.json()
    except requests.RequestException as exc:
        raise AccountError("Не удалось получить профиль Minecraft.") from exc
    name = str(profile.get("name") or "Player")
    account_uuid = str(profile.get("id") or offline_uuid(name))
    skin_url = ""
    for skin in profile.get("skins", []):
        if isinstance(skin, Mapping) and skin.get("url"):
            skin_url = str(skin["url"])
            if skin.get("state") == "ACTIVE":
                break
    return Account(
        id=uuid.uuid4().hex,
        provider="microsoft",
        username=name,
        uuid=account_uuid,
        access_token=mc_token,
        skin_url=skin_url,
        created_at=_now_iso(),
    )


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """One-shot localhost callback for the Microsoft OAuth code."""

    server: "OAuthCallbackServer"

    def do_GET(self) -> None:  # noqa: N802 - HTTP handler API
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path not in ("", "/"):
            self.send_error(404)
            return
        self.server.received_code = str(params.get("code", [""])[0])
        self.server.received_error = str(
            params.get("error_description", params.get("error", [""]))[0]
        )
        self.server.received_state = str(params.get("state", [""])[0])
        body = (
            "<html><body style='font-family:Segoe UI;background:#111018;color:#F5F3FF'>"
            "<h2>Fionix</h2><p>Авторизация получена. Вернитесь в лаунчер.</p>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.server.received.set()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


class OAuthCallbackServer(HTTPServer):
    def __init__(self, address, handler, expected_state: str) -> None:
        super().__init__(address, handler)
        self.received: threading.Event = threading.Event()
        self.received_code = ""
        self.received_error = ""
        self.received_state = ""
        self.expected_state = expected_state

    def wait_for_code(self, timeout: float = 180, cancel_event=None) -> str:
        deadline = time.monotonic() + timeout
        while not self.received.wait(0.2):
            if cancel_event is not None and cancel_event.is_set():
                raise AccountError("Вход Microsoft отменён.")
            if time.monotonic() >= deadline:
                raise AccountError("Время ожидания входа Microsoft истекло.")
        if self.received_error:
            raise AccountError(f"Microsoft OAuth: {self.received_error}")
        if self.expected_state and self.received_state != self.expected_state:
            raise AccountError("OAuth state не совпал. Попробуйте снова.")
        if not self.received_code:
            raise AccountError("Microsoft не вернул код авторизации.")
        return self.received_code


def _callback_target() -> tuple[str, str]:
    parsed = urlparse(_MICROSOFT_REDIRECT_URI)
    host = parsed.hostname or "localhost"
    # Use the exact URI registered in Azure.  With the default
    # "http://localhost" this binds loopback port 80.
    return _MICROSOFT_REDIRECT_URI, host


def login_microsoft_oauth(
    timeout: float = 180,
    cancel_event=None,
    on_browser_url=None,
) -> Account:
    """Open the system browser, receive the callback and return an account.

    The HTTP server binds to loopback only.  The authorization code is
    exchanged immediately (never stored) and the resulting account contains
    the Minecraft access token, not the Microsoft token.
    """
    redirect, host = _callback_target()
    state = secrets.token_urlsafe(24)
    auth_url = microsoft_login_url(state, redirect)
    try:
        server = OAuthCallbackServer(
            (host, int(urlparse(redirect).port or 80)),
            OAuthCallbackHandler,
            state,
        )
    except OSError:
        # Always show Microsoft even if port 80 is busy: the user can copy
        # the redirect URL and use the manual code path.
        if on_browser_url is not None:
            on_browser_url(auth_url)
        else:
            webbrowser.open(auth_url)
        raise AccountError(
            "Не удалось открыть локальный порт для ответа Microsoft. "
            "Войдите в браузере и вставьте полную строку из адресной строки."
        )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if on_browser_url is not None:
            on_browser_url(auth_url)
        else:
            webbrowser.open(auth_url)
        code = server.wait_for_code(timeout, cancel_event)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    return login_microsoft_code(code, redirect)


def login_microsoft_manual(code_or_url: str) -> Account:
    """Fallback for users who paste the full redirect URL or just the code."""
    raw = code_or_url.strip()
    value = raw
    if "://" in raw:
        parsed = urlparse(raw)
        value = str(parse_qs(parsed.query).get("code", [""])[0])
        if not value:
            raise AccountError(
                "В ссылке нет параметра code. Скопируйте всю строку "
                "из адресной строки после входа Microsoft."
            )
    elif "code=" in raw:
        value = str(parse_qs(raw.partition("?")[2]).get("code", [""])[0])
    if not value:
        raise AccountError("Вставьте полную строку из адресной строки или код.")
    # One code → one exchange.  Never loop/retry this call: a failed first
    # exchange consumes the code and a retry returns AADSTS70000.
    return login_microsoft_code(value, _MICROSOFT_REDIRECT_URI)


def profile_skin_url(account: Account) -> str:
    """Return a URL usable by QNetworkAccessManager for the skin/avatar."""
    if account.skin_url:
        return account.skin_url
    if account.provider == "littleskin":
        return LITTLESKIN_PROFILE.format(uuid=quote(account.uuid))
    if account.provider == "elyby":
        return ELYSKIN_SKIN.format(name=quote(account.username))
    return ""
