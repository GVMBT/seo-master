"""Async HTTP client for Yandex Webmaster API v4.

Используется ТОЛЬКО админским разделом Bamboodom для отправки URL'ов на
переобход после публикации новых статей блога.

API docs:
- https://yandex.ru/dev/webmaster/doc/dg/concepts/about.html
- POST /v4/user/{user-id}/hosts/{host-id}/recrawl/queue — добавить URL в очередь
- GET  /v4/user/{user-id}/hosts/{host-id}/recrawl/queue — посмотреть лимиты
- GET  /v4/user — определить user_id текущего токена
- GET  /v4/user/{uid}/hosts — список хостов

Токен генерируется на oauth.yandex.ru с правами `webmaster:hosts`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from bot.config import get_settings
from integrations.yandex_webmaster.exceptions import (
    YandexWebmasterAuthError,
    YandexWebmasterError,
    YandexWebmasterHostNotFoundError,
    YandexWebmasterQuotaExceededError,
    YandexWebmasterRateLimitError,
)
from integrations.yandex_webmaster.models import (
    YWHost,
    YWHostsList,
    YWRecrawlAddResponse,
    YWUserInfo,
)

log = structlog.get_logger()

_API_BASE = "https://api.webmaster.yandex.net/v4"
_DEFAULT_TIMEOUT = 15.0
_MAX_ERROR_BODY = 500


@dataclass
class YandexWebmasterClient:
    """Async wrapper над Yandex Webmaster API v4.

    Поля можно явно прокинуть в тестах. По умолчанию читаем из Settings.
    """

    token: str = ""
    user_id: str = ""
    host_id: str = ""
    site_url: str = ""
    http_client: httpx.AsyncClient | None = None
    timeout: float = _DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        settings = get_settings()
        if not self.token:
            self.token = settings.yandex_webmaster_token.get_secret_value()
        if not self.user_id:
            self.user_id = settings.yandex_webmaster_user_id
        if not self.host_id:
            self.host_id = settings.yandex_webmaster_host_id
        if not self.site_url:
            self.site_url = settings.yandex_webmaster_site

    # ---- internals ----------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise YandexWebmasterAuthError("YANDEX_WEBMASTER_TOKEN не настроен")
        return {
            "Authorization": f"OAuth {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        headers = self._headers()
        url = f"{_API_BASE}{path}"
        effective_timeout = timeout if timeout is not None else self.timeout

        async def _send(client: httpx.AsyncClient) -> httpx.Response:
            return await client.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=effective_timeout,
            )

        try:
            if self.http_client is not None:
                resp = await _send(self.http_client)
            else:
                async with httpx.AsyncClient(timeout=effective_timeout) as client:
                    resp = await _send(client)
        except httpx.TimeoutException as exc:
            raise YandexWebmasterError(f"Timeout on {path}: {exc}") from exc
        except httpx.RequestError as exc:
            raise YandexWebmasterError(f"Network error on {path}: {exc}") from exc

        return self._handle_response(path, resp)

    @staticmethod
    def _handle_response(path: str, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code in (401, 403):
            raise YandexWebmasterAuthError(
                f"OAuth-токен невалиден / нет прав (HTTP {resp.status_code}): {resp.text[:_MAX_ERROR_BODY]}"
            )
        if resp.status_code == 429:
            retry_after_raw = resp.headers.get("Retry-After", "60")
            try:
                retry_after = int(retry_after_raw)
            except ValueError:
                retry_after = 60
            raise YandexWebmasterRateLimitError(retry_after, message=resp.text[:_MAX_ERROR_BODY])
        if resp.status_code == 404:
            raise YandexWebmasterHostNotFoundError(f"Не найдено: {path} — {resp.text[:_MAX_ERROR_BODY]}")
        if resp.status_code >= 400:
            # Часто 4xx = «суточная квота исчерпана» — отдельная категория
            body_text = resp.text[:_MAX_ERROR_BODY]
            lowered = body_text.lower()
            if "quota" in lowered or "limit" in lowered:
                raise YandexWebmasterQuotaExceededError(body_text)
            raise YandexWebmasterError(f"HTTP {resp.status_code} on {path}: {body_text}")

        # 204 No Content (бывает на recrawl POST) → пустой ответ ОК
        if resp.status_code == 204 or not resp.content:
            return {}

        try:
            data = resp.json()
        except ValueError as exc:
            raise YandexWebmasterError(f"Non-JSON response on {path}: {resp.text[:_MAX_ERROR_BODY]}") from exc
        if not isinstance(data, dict):
            raise YandexWebmasterError(f"Unexpected JSON shape on {path}: {type(data).__name__}")
        return data

    # ---- public API ---------------------------------------------------

    async def get_user(self) -> YWUserInfo:
        """GET /v4/user — определить user_id для OAuth-токена."""
        data = await self._request("GET", "/user")
        return YWUserInfo.model_validate(data)

    async def list_hosts(self, user_id: str | None = None) -> list[YWHost]:
        """GET /v4/user/{uid}/hosts — список верифицированных хостов."""
        uid = user_id or self.user_id
        if not uid:
            user = await self.get_user()
            uid = str(user.user_id)
            self.user_id = uid
        data = await self._request("GET", f"/user/{uid}/hosts")
        return YWHostsList.model_validate(data).hosts

    async def resolve_host_id(self, site_url: str | None = None) -> str:
        """Находит host_id для заданного site_url (по умолчанию self.site_url).

        Сравнение по ascii_host_url (без слэша на конце).
        Ошибка YandexWebmasterHostNotFoundError если не найден.
        """
        target = (site_url or self.site_url).rstrip("/").lower()
        hosts = await self.list_hosts()
        for h in hosts:
            ascii_url = (h.ascii_host_url or "").rstrip("/").lower()
            if ascii_url == target:
                return h.host_id
        # Резервный матч по host_id (он содержит ascii-домен)
        for h in hosts:
            if target.split("//", 1)[-1].split("/", 1)[0] in (h.host_id or ""):
                return h.host_id
        raise YandexWebmasterHostNotFoundError(
            f"Хост {target} не найден среди верифицированных. "
            f"Проверьте https://webmaster.yandex.ru/sites/ и подтвердите права."
        )

    async def ensure_host_id(self) -> str:
        """Возвращает self.host_id; если пустой — резолвит и кеширует на инстансе."""
        if self.host_id:
            return self.host_id
        self.host_id = await self.resolve_host_id()
        return self.host_id

    async def add_to_recrawl(self, url: str) -> YWRecrawlAddResponse:
        """POST /v4/user/{uid}/hosts/{hid}/recrawl/queue — добавить URL.

        Серверный rate-limit: ~1 URL в секунду. Не блочит, отвечает 429 если перебор.
        """
        if not self.user_id:
            user = await self.get_user()
            self.user_id = str(user.user_id)
        await self.ensure_host_id()
        data = await self._request(
            "POST",
            f"/user/{self.user_id}/hosts/{self.host_id}/recrawl/queue",
            json_body={"url": url},
            timeout=15.0,
        )
        return YWRecrawlAddResponse.model_validate(data) if data else YWRecrawlAddResponse()

    async def get_recrawl_quota(self) -> dict[str, Any]:
        """GET /v4/user/{uid}/hosts/{hid}/recrawl/queue — история переобхода.

        Возвращает dict с полями:
            tasks: list[{task_id, url, state, added_at, ...}] — последние ~30 дней.
        Из этого извлекается «отправлено сегодня», «в очереди», «обошёл робот».
        Дневную квоту читаем отдельно через `get_recrawl_quota_info`.
        """
        if not self.user_id:
            user = await self.get_user()
            self.user_id = str(user.user_id)
        await self.ensure_host_id()
        return await self._request(
            "GET",
            f"/user/{self.user_id}/hosts/{self.host_id}/recrawl/queue",
        )

    async def get_recrawl_quota_info(self) -> dict[str, Any]:
        """GET /v4/user/{uid}/hosts/{hid}/recrawl/quota — текущий лимит/использовано (4E).

        Поля: `daily_quota`, `quota_remainder`. Если endpoint вернёт 404 (бывает у молодых
        хостов) — отдаём пустой dict, чтобы UI не валил кнопку.
        """
        if not self.user_id:
            user = await self.get_user()
            self.user_id = str(user.user_id)
        await self.ensure_host_id()
        try:
            return await self._request(
                "GET",
                f"/user/{self.user_id}/hosts/{self.host_id}/recrawl/quota",
            )
        except YandexWebmasterError as exc:
            if "404" in str(exc):
                return {}
            raise

    async def get_host_summary(self) -> dict[str, Any]:
        """GET /v4/user/{uid}/hosts/{hid}/summary — общая инфа о хосте (4E).

        Требует scope `webmaster:hostinfo`. Поля среди прочих:
            host_problem_critical_score, sqi, last_access_at,
            searchable_pages_count (в поиске Яндекса).
        """
        if not self.user_id:
            user = await self.get_user()
            self.user_id = str(user.user_id)
        await self.ensure_host_id()
        return await self._request(
            "GET",
            f"/user/{self.user_id}/hosts/{self.host_id}/summary",
        )

    async def get_host_problems(self) -> dict[str, Any]:
        """GET /v4/user/{uid}/hosts/{hid}/possible-problems — текущие проблемы по хосту (4E).

        Удобно для будущего «что не так с сайтом» в UI. Сейчас не используется
        в дашборде, но клиент готов. Требует `webmaster:hostinfo`.
        """
        if not self.user_id:
            user = await self.get_user()
            self.user_id = str(user.user_id)
        await self.ensure_host_id()
        return await self._request(
            "GET",
            f"/user/{self.user_id}/hosts/{self.host_id}/possible-problems",
        )

    async def smoke_test(self) -> tuple[str, str, list[YWHost]]:
        """Простая проверка конфига: вернёт (user_id, host_id, hosts).

        Использовать в админке для кнопки «Проверить связь» (если добавим).
        """
        user = await self.get_user()
        self.user_id = str(user.user_id)
        hosts = await self.list_hosts()
        try:
            host_id = await self.resolve_host_id()
        except YandexWebmasterHostNotFoundError:
            host_id = ""
        return self.user_id, host_id, hosts


async def add_urls_with_rate_limit(
    client: YandexWebmasterClient,
    urls: list[str],
    *,
    delay_sec: float = 1.1,
    on_progress: Any = None,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Отправляет список URL'ов на переобход с rate-limit.

    Возвращает (sent, failed) где failed = list[(url, error_message)].
    on_progress(i, total, url, ok) — опциональный callback (sync или async).
    """
    sent: list[str] = []
    failed: list[tuple[str, str]] = []
    total = len(urls)
    for i, url in enumerate(urls, start=1):
        ok = False
        err = ""
        try:
            await client.add_to_recrawl(url)
            sent.append(url)
            ok = True
        except YandexWebmasterRateLimitError as exc:
            await asyncio.sleep(min(exc.retry_after, 30))
            try:
                await client.add_to_recrawl(url)
                sent.append(url)
                ok = True
            except YandexWebmasterError as exc2:
                err = str(exc2)
                failed.append((url, err))
        except YandexWebmasterError as exc:
            err = str(exc)
            failed.append((url, err))
        except Exception as exc:
            err = f"unexpected: {exc!r}"
            failed.append((url, err))

        if on_progress is not None:
            try:
                res = on_progress(i, total, url, ok)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                log.warning("yw_progress_callback_failed", exc_info=True)

        if i < total:
            await asyncio.sleep(delay_sec)

    return sent, failed
