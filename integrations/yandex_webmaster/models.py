"""Pydantic models for Yandex Webmaster API responses."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class YWHostQuota(BaseModel):
    """Лимиты переобхода (recrawl quota) для одного хоста."""

    model_config = ConfigDict(extra="ignore")

    daily_quota: int = Field(default=0, alias="daily_quota")
    used: int = Field(default=0)


class YWUserInfo(BaseModel):
    """GET /v4/user — минимальные поля."""

    model_config = ConfigDict(extra="ignore")

    user_id: int


class YWHost(BaseModel):
    """Один хост из GET /v4/user/{uid}/hosts."""

    model_config = ConfigDict(extra="ignore")

    host_id: str
    ascii_host_url: str = ""
    unicode_host_url: str = ""
    verified: bool = False


class YWHostsList(BaseModel):
    """GET /v4/user/{uid}/hosts."""

    model_config = ConfigDict(extra="ignore")

    hosts: list[YWHost] = Field(default_factory=list)


class YWRecrawlAddResponse(BaseModel):
    """POST /v4/user/{uid}/hosts/{hid}/recrawl/queue — успешный ответ.

    Сервер возвращает task_id, мы его не используем (нечего показывать), но
    модель оставлена для логирования / будущей истории.
    """

    model_config = ConfigDict(extra="ignore")

    task_id: str = ""
