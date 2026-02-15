"""Router: built-in help system (F46). Callback-based, no FSM."""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from keyboards.category import help_back_kb, help_main_kb
from routers._helpers import guard_callback_message

router = Router(name="help")


# ---------------------------------------------------------------------------
# Help texts (Russian)
# ---------------------------------------------------------------------------

_HELP_MAIN = "<b>Справка SEO Master Bot</b>\n\nВыберите раздел:"

_HELP_CONNECT = (
    "<b>Первое подключение</b>\n\n"
    "<b>WordPress (подробно):</b>\n"
    "1. Войдите в админку вашего сайта\n"
    "   (обычно: ваш-сайт.ru/wp-admin)\n"
    "2. Перейдите: Пользователи → Профиль\n"
    "3. Прокрутите вниз до «Пароли приложений»\n"
    "4. В поле «Имя» введите: SEO Bot\n"
    "5. Нажмите «Добавить новый пароль»\n"
    "6. Скопируйте пароль (показывается один раз!)\n"
    "7. В боте: Проект → Подключения → WordPress\n"
    "8. Введите URL сайта, ваш логин WP и\n"
    "   скопированный пароль приложения\n\n"
    "Важно: пароль приложения — это НЕ ваш\n"
    "обычный пароль от WordPress. Это отдельный\n"
    "ключ только для API.\n\n"
    "<b>Telegram:</b>\n"
    "1. Создайте канал в Telegram\n"
    "2. Создайте бота через @BotFather\n"
    "3. Добавьте бота администратором канала\n"
    "   (с правом публикации сообщений)\n"
    "4. В боте: Проект → Подключения → Telegram\n"
    "5. Введите токен бота и @username канала\n\n"
    "<b>VK:</b>\n"
    "1. Создайте сообщество VK (или используйте\n"
    "   существующее)\n"
    "2. Настройки сообщества → Работа с API →\n"
    "   Создать ключ (права: стена, фотографии)\n"
    "3. В боте: Проект → Подключения → VK\n"
    "4. Введите токен и ID сообщества\n\n"
    "<b>Pinterest:</b>\n"
    "1. В боте: Проект → Подключения → Pinterest\n"
    "2. Перейдите по ссылке авторизации\n"
    "3. Разрешите доступ боту\n"
    "4. Выберите доску для публикации"
)

_HELP_PROJECT = (
    "<b>Создание проекта</b>\n\n"
    "1. Главное меню → Проекты → Создать проект\n"
    "2. Введите название, компанию и специализацию\n"
    "3. Опционально: сайт (для анализа и брендинга)\n\n"
    "Проект = ваш бизнес/сайт. Категории внутри проекта = темы контента.\n\n"
    "<b>Редактирование:</b>\n"
    "Проект → Редактировать данные → выберите поле\n\n"
    "Заполните максимум полей (город, телефон, email, опыт, преимущества) — "
    "AI использует их для генерации более точного контента."
)

_HELP_CATEGORY = (
    "<b>Категории и контент</b>\n\n"
    "Категория = тема контента (напр. «Кухонная мебель»).\n\n"
    "<b>Ключевые фразы:</b>\n"
    "Автоподбор из DataForSEO или загрузка файлом. "
    "Используются для SEO-оптимизации статей.\n\n"
    "<b>Описание:</b>\n"
    "AI-генерация описания категории. Используется в промптах.\n\n"
    "<b>Прайс-лист:</b>\n"
    "Текстом или Excel. Используется AI для точных цен в контенте.\n\n"
    "<b>Отзывы:</b>\n"
    "AI-генерация реалистичных отзывов для контента.\n\n"
    "<b>Медиа:</b>\n"
    "Фото и документы для использования в публикациях."
)

_HELP_PUBLISH = (
    "<b>Публикация контента</b>\n\n"
    "<b>Быстрая публикация:</b>\n"
    "Кнопка «Быстрая публикация» → выбор категории → выбор платформы → "
    "генерация → превью → публикация. Ручной контроль каждой статьи.\n\n"
    "<b>Автопубликация (расписание):</b>\n"
    "Проект → Планировщик → настройте дни, время и частоту. "
    "Бот автоматически генерирует и публикует контент по расписанию.\n\n"
    "<b>Типы контента:</b>\n"
    "• Статьи (WordPress) — SEO-оптимизированные, с изображениями\n"
    "• Посты (Telegram, VK, Pinterest) — короткие, с 1 изображением\n\n"
    "<b>Токены:</b>\n"
    "Статья ~320 токенов, пост ~40-60 токенов. "
    "Баланс в профиле, пополнение в тарифах."
)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "help:main")
async def cb_help_main(callback: CallbackQuery) -> None:
    """Show help sections menu."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    await msg.edit_text(_HELP_MAIN, reply_markup=help_main_kb().as_markup())
    await callback.answer()


@router.callback_query(F.data == "help:connect")
async def cb_help_connect(callback: CallbackQuery) -> None:
    """Help: platform connections."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    await msg.edit_text(_HELP_CONNECT, reply_markup=help_back_kb().as_markup())
    await callback.answer()


@router.callback_query(F.data == "help:project")
async def cb_help_project(callback: CallbackQuery) -> None:
    """Help: project creation."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    await msg.edit_text(_HELP_PROJECT, reply_markup=help_back_kb().as_markup())
    await callback.answer()


@router.callback_query(F.data == "help:category")
async def cb_help_category(callback: CallbackQuery) -> None:
    """Help: categories and content."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    await msg.edit_text(_HELP_CATEGORY, reply_markup=help_back_kb().as_markup())
    await callback.answer()


@router.callback_query(F.data == "help:publish")
async def cb_help_publish(callback: CallbackQuery) -> None:
    """Help: publishing."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    await msg.edit_text(_HELP_PUBLISH, reply_markup=help_back_kb().as_markup())
    await callback.answer()
