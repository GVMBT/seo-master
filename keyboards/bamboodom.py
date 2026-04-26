"""Inline keyboards for the Bamboodom admin section."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# ---------------------------------------------------------------------------
# Root entry — три кнопки: Статьи / Администрирование / К панели
# ---------------------------------------------------------------------------


def bamboodom_root_kb() -> InlineKeyboardMarkup:
    """Корневой экран Bamboodom."""
    rows = [
        [InlineKeyboardButton(text="📝 Статьи", callback_data="bamboodom:articles")],
        [InlineKeyboardButton(text="⚙️ Администрирование", callback_data="bamboodom:admin")],
        [InlineKeyboardButton(text="📊 Аналитика", callback_data="bamboodom:analytics")],
        [InlineKeyboardButton(text="К панели", callback_data="admin:panel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_analytics_kb() -> InlineKeyboardMarkup:
    """Подменю «Аналитика» (4F)."""
    rows = [
        [InlineKeyboardButton(text="📰 Утренний дайджест", callback_data="bamboodom:analytics:digest")],
        [InlineKeyboardButton(text="📈 Сводка вчера", callback_data="bamboodom:analytics:yesterday")],
        [InlineKeyboardButton(text="📈 Сводка за 7 дней", callback_data="bamboodom:analytics:week")],
        [InlineKeyboardButton(text="🔝 Топ-10 страниц (7 дней)", callback_data="bamboodom:analytics:top_pages")],
        [InlineKeyboardButton(text="🌐 Источники трафика", callback_data="bamboodom:analytics:sources")],
        [InlineKeyboardButton(text="🔎 Запросы из Яндекса", callback_data="bamboodom:analytics:queries")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_analytics_back_kb() -> InlineKeyboardMarkup:
    """Кнопка возврата с экрана конкретного отчёта."""
    rows = [
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:analytics")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# «Статьи» — то, что раньше было entry-экраном
# ---------------------------------------------------------------------------


def bamboodom_articles_kb() -> InlineKeyboardMarkup:
    """Подменю «Статьи» — все ранее существовавшие кнопки."""
    rows = [
        [InlineKeyboardButton(text="Smoke-test", callback_data="bamboodom:smoke")],
        [InlineKeyboardButton(text="Контекст сайта", callback_data="bamboodom:context")],
        [InlineKeyboardButton(text="Артикулы", callback_data="bamboodom:codes")],
        [InlineKeyboardButton(text="AI-публикация", callback_data="bamboodom:ai:start")],
        [InlineKeyboardButton(text="Публикация в sandbox", callback_data="bamboodom:publish")],
        [InlineKeyboardButton(text="История публикаций", callback_data="bamboodom:history")],
        [InlineKeyboardButton(text="Настройки", callback_data="bamboodom:settings")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Старое имя оставляем как алиас — некоторые legacy-вызовы используют bamboodom_entry_kb()
def bamboodom_entry_kb() -> InlineKeyboardMarkup:
    """Алиас для bamboodom_articles_kb (legacy-имя)."""
    return bamboodom_articles_kb()


# ---------------------------------------------------------------------------
# «Администрирование»
# ---------------------------------------------------------------------------


def bamboodom_admin_kb() -> InlineKeyboardMarkup:
    """Подменю «Администрирование»."""
    rows = [
        [InlineKeyboardButton(text="🔄 Переобход в Яндекс Вебмастер", callback_data="bamboodom:admin:recrawl")],
        [InlineKeyboardButton(text="🗺 Регенерировать sitemap (блог)", callback_data="bamboodom:admin:regen")],
        [InlineKeyboardButton(text="🗺 Регенерировать sitemap (весь сайт)", callback_data="bamboodom:admin:regen_full")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_recrawl_preview_kb() -> InlineKeyboardMarkup:
    """Экран после краула: показал что нашёл, спрашивает подтвердить отправку."""
    rows = [
        [InlineKeyboardButton(text="📨 Отправить в Я.Вебмастер", callback_data="bamboodom:admin:recrawl:run")],
        [InlineKeyboardButton(text="🔁 Перепроверить", callback_data="bamboodom:admin:recrawl")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:admin")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_recrawl_progress_kb() -> InlineKeyboardMarkup:
    """Во время отправки — пустая клавиатура (можно добавить cancel позже)."""
    return InlineKeyboardMarkup(inline_keyboard=[])


def bamboodom_recrawl_result_kb() -> InlineKeyboardMarkup:
    """Финальный экран отправки."""
    rows = [
        [InlineKeyboardButton(text="🔁 Запустить ещё раз", callback_data="bamboodom:admin:recrawl")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:admin")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Существующие подэкраны раздела «Статьи» — без изменений по составу,
# только Назад теперь ведёт на bamboodom:articles (а не на bamboodom:entry).
# ---------------------------------------------------------------------------


def bamboodom_smoke_result_kb() -> InlineKeyboardMarkup:
    """Smoke-test result screen."""
    rows = [
        [InlineKeyboardButton(text="Повторить", callback_data="bamboodom:smoke")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:articles")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_context_kb() -> InlineKeyboardMarkup:
    """Context-screen: refresh + back."""
    rows = [
        [InlineKeyboardButton(text="Обновить", callback_data="bamboodom:context:refresh")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:articles")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_codes_kb() -> InlineKeyboardMarkup:
    """Codes-screen: refresh + back."""
    rows = [
        [InlineKeyboardButton(text="Обновить", callback_data="bamboodom:codes:refresh")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:articles")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_publish_input_kb() -> InlineKeyboardMarkup:
    """Publish — entry FSM state: example + cancel."""
    rows = [
        [InlineKeyboardButton(text="Вставить пример JSON", callback_data="bamboodom:publish:example")],
        [InlineKeyboardButton(text="Отмена", callback_data="bamboodom:articles")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_publish_confirm_kb() -> InlineKeyboardMarkup:
    """Publish — confirm state."""
    rows = [
        [InlineKeyboardButton(text="Отправить", callback_data="bamboodom:publish:submit")],
        [InlineKeyboardButton(text="Вернуться к редактированию", callback_data="bamboodom:publish")],
        [InlineKeyboardButton(text="Отмена", callback_data="bamboodom:articles")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_publish_result_kb(article_url: str | None) -> InlineKeyboardMarkup:
    """Publish — result screen. Article URL is a direct HTTP link when available."""
    rows: list[list[InlineKeyboardButton]] = []
    if article_url:
        rows.append([InlineKeyboardButton(text="Открыть статью", url=article_url)])
    rows.append([InlineKeyboardButton(text="Опубликовать ещё", callback_data="bamboodom:publish")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="bamboodom:articles")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_history_kb() -> InlineKeyboardMarkup:
    """History-screen keyboard."""
    rows = [
        [InlineKeyboardButton(text="Опубликовать ещё", callback_data="bamboodom:publish")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:articles")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_settings_kb() -> InlineKeyboardMarkup:
    """Settings stub: only back button."""
    rows = [
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:articles")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_ai_material_kb() -> InlineKeyboardMarkup:
    """AI FSM — step 1: choose material category."""
    rows = [
        [InlineKeyboardButton(text="WPC панели", callback_data="bamboodom:ai:mat:wpc")],
        [InlineKeyboardButton(text="Гибкая керамика", callback_data="bamboodom:ai:mat:flex")],
        [InlineKeyboardButton(text="Реечные панели", callback_data="bamboodom:ai:mat:reiki")],
        [InlineKeyboardButton(text="Алюминиевые профили", callback_data="bamboodom:ai:mat:profiles")],
        [InlineKeyboardButton(text="Отмена", callback_data="bamboodom:articles")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_ai_keyword_kb() -> InlineKeyboardMarkup:
    """AI FSM — step 2: waiting for keyword. Only cancel button."""
    rows = [
        [InlineKeyboardButton(text="Отмена", callback_data="bamboodom:articles")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_ai_generating_kb() -> InlineKeyboardMarkup:
    """AI FSM — step 3: generating. Only cancel button (4B.1.4)."""
    rows = [
        [InlineKeyboardButton(text="❌ Отменить", callback_data="bamboodom:ai:cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_ai_preview_kb() -> InlineKeyboardMarkup:
    """AI FSM — step 4: preview with publish / regenerate / cancel."""
    rows = [
        [InlineKeyboardButton(text="Опубликовать", callback_data="bamboodom:ai:publish")],
        [InlineKeyboardButton(text="Перегенерировать", callback_data="bamboodom:ai:regenerate")],
        [InlineKeyboardButton(text="Отмена", callback_data="bamboodom:articles")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_ai_result_kb(article_url: str | None) -> InlineKeyboardMarkup:
    """AI FSM — step 5: result screen."""
    rows: list[list[InlineKeyboardButton]] = []
    if article_url:
        rows.append([InlineKeyboardButton(text="Открыть статью", url=article_url)])
    rows.append([InlineKeyboardButton(text="Ещё статью", callback_data="bamboodom:ai:start")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="bamboodom:articles")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
