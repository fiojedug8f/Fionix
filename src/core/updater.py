"""GitHub release checks and safe updater downloads.

When ``GITHUB_REPO`` is empty/placeholder the updater is completely offline:
no HTTP request is made.  A configured repository must contain a release with
an ``.exe`` asset; the asset is downloaded to a temporary directory and the
UI can launch it after a successful download.
"""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

import requests

from src import __version__
from config import GITHUB_API_URL, GITHUB_REPO

logger = logging.getLogger(__name__)

HTTP_HEADERS = {
    "User-Agent": f"Fionix/{__version__} updater",
    "Accept": "application/vnd.github+json",
}
NOT_CONFIGURED_MESSAGE = "Проверка обновлений недоступна (репозиторий не настроен)"
PLACEHOLDERS = {"", "пока нету", "none", "your_repo", "your-repo"}


class UpdateError(Exception):
    """An update check/download that could not be completed."""


Progress = Callable[[int, str, str], None]


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    available: bool
    current: str
    latest: str = ""
    url: str = ""
    notes: str = ""
    asset_url: str = ""
    asset_name: str = ""
    configured: bool = True

    @property
    def display_latest(self) -> str:
        return self.latest.lstrip("v") or "—"


def repo_configured() -> bool:
    value = str(GITHUB_REPO or "").strip()
    return bool(value) and value.lower() not in PLACEHOLDERS and "YOUR_" not in value


def version_tuple(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", value or "")
    return tuple(int(item) for item in numbers[:4]) or (0,)


def is_newer(latest: str, current: str) -> bool:
    left = version_tuple(latest)
    right = version_tuple(current)
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def _select_exe_asset(assets: list[Mapping]) -> tuple[str, str]:
    candidates: list[tuple[str, str]] = []
    for asset in assets:
        if not isinstance(asset, Mapping):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name.lower().endswith(".exe") and url:
            candidates.append((name, url))
    if not candidates:
        return "", ""
    preferred = next(
        (item for item in candidates if "fionix" in item[0].lower()), candidates[0]
    )
    return preferred[0], preferred[1]


def check_for_updates(
    current_version: str,
    *,
    timeout: tuple[int, int] = (8, 15),
    proxies: Mapping[str, str] | None = None,
) -> UpdateInfo:
    if not repo_configured():
        return UpdateInfo(
            available=False,
            current=current_version,
            configured=False,
        )
    url = f"{GITHUB_API_URL}/repos/{GITHUB_REPO}/releases/latest"
    try:
        response = requests.get(
            url, headers=HTTP_HEADERS, timeout=timeout, proxies=proxies
        )
    except requests.RequestException as exc:
        raise UpdateError("Не удалось проверить обновления: нет связи с GitHub.") from exc
    if response.status_code == 404:
        raise UpdateError("Релизы Fionix на GitHub пока не опубликованы.")
    if response.status_code >= 400:
        raise UpdateError(f"GitHub вернул ошибку {response.status_code}.")
    try:
        data = response.json()
    except ValueError as exc:
        raise UpdateError("GitHub вернул некорректный ответ.") from exc
    if not isinstance(data, Mapping):
        raise UpdateError("Некорректный ответ GitHub.")
    tag = str(data.get("tag_name") or data.get("name") or "")
    html_url = str(data.get("html_url") or "")
    notes = str(data.get("body") or "")
    if not tag:
        raise UpdateError("В последнем релизе GitHub нет номера версии.")
    assets = data.get("assets") or []
    asset_name, asset_url = _select_exe_asset(assets if isinstance(assets, list) else [])
    available = is_newer(tag, current_version)
    return UpdateInfo(
        available=available,
        current=current_version,
        latest=tag,
        url=html_url,
        notes=notes,
        asset_url=asset_url,
        asset_name=asset_name,
    )


def download_update(
    info: UpdateInfo,
    *,
    progress: Progress | None = None,
    proxies: Mapping[str, str] | None = None,
    cancel_event=None,
) -> Path:
    if not info.asset_url:
        raise UpdateError("В релизе GitHub нет .exe-файла для обновления.")
    directory = Path(tempfile.mkdtemp(prefix="fionix-update-"))
    filename = Path(info.asset_name or "Fionix-update.exe").name
    target = directory / filename
    temp = target.with_name(target.name + ".part")
    downloaded = 0

    def report(percent: int, title: str, detail: str = "") -> None:
        if progress is not None:
            progress(max(0, min(100, int(percent))), title, detail)

    try:
        report(2, "Загрузка обновления", filename)
        with requests.get(
            info.asset_url,
            headers=HTTP_HEADERS,
            proxies=proxies,
            stream=True,
            timeout=(15, 120),
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            with temp.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if cancel_event is not None and cancel_event.is_set():
                        from src.core.launcher import InstallCancelled

                        raise InstallCancelled("Загрузка обновления отменена.")
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        report(
                            5 + int(downloaded * 90 / total),
                            "Загрузка обновления",
                            f"{downloaded / 1024 / 1024:.1f} МБ",
                        )
        temp.replace(target)
        report(100, "Обновление загружено", filename)
        return target
    except requests.RequestException as exc:
        temp.unlink(missing_ok=True)
        raise UpdateError(f"Не удалось скачать обновление: {exc}") from exc
    except Exception:
        temp.unlink(missing_ok=True)
        raise
