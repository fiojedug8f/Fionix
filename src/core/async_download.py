"""Async streaming downloads with hash verification and bounded retries."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None

logger = logging.getLogger(__name__)

Progress = Callable[[int, str, str], None]
_MAX_PARALLEL = 4
_MAX_ATTEMPTS = 3
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True, slots=True)
class DownloadItem:
    url: str
    destination: Path
    sha512: str = ""
    sha1: str = ""
    sha256: str = ""


class DownloadCancelled(Exception):
    pass


def _hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matches(path: Path, item: DownloadItem) -> bool:
    if not path.is_file():
        return False
    for algorithm, expected in (
        ("sha512", item.sha512),
        ("sha1", item.sha1),
        ("sha256", item.sha256),
    ):
        if expected and _hash_file(path, algorithm).lower() != expected.lower():
            return False
    return True


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelled("Загрузка отменена.")


async def _stream(session, item, temp, progress, cancel_event, proxy):
    async with session.get(item.url, proxy=proxy) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        with temp.open("wb") as handle:
            async for chunk in response.content.iter_chunked(256 * 1024):
                _check_cancel(cancel_event)
                if not chunk:
                    continue
                handle.write(chunk)
                downloaded += len(chunk)
                if progress and total:
                    progress(
                        min(95, 5 + int(downloaded * 90 / total)),
                        f"Загрузка {item.destination.name}",
                        f"{downloaded / 1024 / 1024:.1f} МБ",
                    )


async def _download_one(
    session,
    semaphore,
    item,
    progress,
    cancel_event,
    completed,
    total_items,
    proxy,
):
    target = item.destination
    target.parent.mkdir(parents=True, exist_ok=True)
    if _matches(target, item):
        completed[0] += 1
        return target

    temp = target.with_name(target.name + ".part")
    async with semaphore:
        last_error = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            _check_cancel(cancel_event)
            try:
                await _stream(
                    session, item, temp, progress, cancel_event, proxy
                )
                _check_cancel(cancel_event)
                for algorithm, expected in (
                    ("sha512", item.sha512),
                    ("sha1", item.sha1),
                    ("sha256", item.sha256),
                ):
                    if expected and _hash_file(temp, algorithm).lower() != expected.lower():
                        raise ValueError(
                            f"Контрольная сумма {algorithm} не совпала: {target.name}"
                        )
                temp.replace(target)
                completed[0] += 1
                if progress:
                    progress(
                        min(99, 5 + int(completed[0] * 94 / max(1, total_items))),
                        f"Загрузка {target.name}",
                        f"{completed[0]} из {total_items}",
                    )
                return target
            except DownloadCancelled:
                temp.unlink(missing_ok=True)
                raise
            except Exception as exc:
                last_error = exc
                temp.unlink(missing_ok=True)
                logger.warning(
                    "Download attempt %s/%s failed for %s: %s",
                    attempt,
                    _MAX_ATTEMPTS,
                    item.url,
                    exc,
                )
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(0.8 * attempt)
        raise RuntimeError(f"Не удалось скачать {target.name}: {last_error}")


async def download_many(
    items: Iterable[DownloadItem],
    *,
    progress: Progress | None = None,
    cancel_event: threading.Event | None = None,
    proxy: str | None = None,
    limit: int = _MAX_PARALLEL,
    read_timeout: int = READ_TIMEOUT,
) -> list[Path]:
    queue = [item for item in items if item.url]
    if not queue:
        return []
    if aiohttp is None:
        raise RuntimeError("aiohttp не установлен")

    limit = max(1, min(_MAX_PARALLEL, int(limit)))
    timeout = aiohttp.ClientTimeout(
        total=None,
        sock_connect=CONNECT_TIMEOUT,
        sock_read=max(1, int(read_timeout)),
    )
    connector = aiohttp.TCPConnector(limit=limit, ttl_dns_cache=300)
    completed = [0]
    semaphore = asyncio.Semaphore(limit)
    async with aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers={"User-Agent": BROWSER_USER_AGENT},
    ) as session:
        tasks = [
            _download_one(
                session,
                semaphore,
                item,
                progress,
                cancel_event,
                completed,
                len(queue),
                proxy,
            )
            for item in queue
        ]
        return list(await asyncio.gather(*tasks))


def download_many_sync(
    items: Iterable[DownloadItem],
    *,
    progress: Progress | None = None,
    cancel_event: threading.Event | None = None,
    proxy: str | None = None,
    limit: int = _MAX_PARALLEL,
    read_timeout: int = READ_TIMEOUT,
) -> list[Path]:
    return asyncio.run(
        download_many(
            items,
            progress=progress,
            cancel_event=cancel_event,
            proxy=proxy,
            limit=limit,
            read_timeout=read_timeout,
        )
    )
