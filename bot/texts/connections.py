"""Connection instruction texts for platform onboarding.

Uses E.* emoji constants from bot.texts.emoji for consistency.
"""

from bot.texts.emoji import E

# ---------------------------------------------------------------------------
# VK
# ---------------------------------------------------------------------------

VK_STEP1_GROUP_URL = (
    f"{E.VK}"
    " <b>Подключение VK</b>\n\n"
    "Шаг 1/2 \u2014 Отправьте ссылку на группу VK\n\n"
    "Примеры:\n"
    "\u2022 https://vk.com/club123456\n"
    "\u2022 https://vk.com/mygroup\n"
    "\u2022 123456 (ID группы)\n\n"
    "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    "<i>Нужна группа, в которой вы администратор</i>"
)

VK_STEP2_API_KEY = (
    f"{E.VK}"
    " <b>Подключение VK</b>\n\n"
    "Шаг 2/2 \u2014 Создайте ключ API\n"
    "Группа: <b>{group_name}</b>\n\n"
    f"{E.KEY}"
    " <b>Инструкция:</b>\n\n"
    f"{E.N1}"
    " Откройте настройки API группы:\n"
    '   <a href="https://vk.com/club{group_id}?act=tokens">Открыть настройки API</a>\n\n'
    f"{E.N2}"
    " Нажмите <b>Создать ключ</b>\n\n"
    f"{E.N3}"
    " Отметьте три галочки:\n"
    f"   {E.CHECK}"
    " Управление сообществом\n"
    f"   {E.CHECK}"
    " Доступ к фотографиям\n"
    f"   {E.CHECK}"
    " Доступ к стене\n\n"
    f"{E.N4}"
    " Подтвердите через SMS\n\n"
    f"{E.N5}"
    " Скопируйте ключ и вставьте сюда \u2b07\ufe0f\n\n"
    "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    f"{E.LOCK}"
    " <i>Ключ хранится в зашифрованном виде</i>"
)

# Legacy: VK OAuth flow (kept for backward compat with routers/platforms/connections.py)
_VK_AUTH_URL = (
    "https://oauth.vk.com/authorize?"
    "client_id=2685278"
    "&scope=wall,photos,offline"
    "&response_type=token"
    "&redirect_uri=https://oauth.vk.com/blank.html"
    "&revoke=1"
)

def _vk_step2_auth() -> str:
    """Build VK auth step text using centralized emoji constants."""
    from bot.texts.emoji import E

    return (
        E.VK + " <b>Подключение VK</b>\n\n"
        "Шаг 2/2 \u2014 Авторизуйте доступ\n"
        "Группа: <b>{group_name}</b>\n\n"
        + E.KEY + " <b>Инструкция:</b>\n\n"
        + E.N1 + " Нажмите <b>Авторизоваться</b> ниже\n\n"
        + E.N2 + " Нажмите <b>Разрешить</b> на странице VK\n\n"
        + E.N3 + " Вас перенаправит на страницу с предупреждением.\n"
        "   Это нормально \u2014 скопируйте <b>всю ссылку</b>\n"
        "   из адресной строки и отправьте сюда \u2b07\ufe0f\n\n"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        + E.LOCK + " <i>Токен хранится в зашифрованном виде</i>"
    )


VK_STEP2_AUTH = _vk_step2_auth()


def _vk_type_select() -> str:
    """Build VK type selection screen."""
    from bot.texts.emoji import E

    return (
        E.VK + " <b>Подключение VK</b>\n\n"
        "Выберите тип подключения:\n\n"
        + E.N1 + " <b>Группа</b> \u2014 публикации от имени сообщества\n"
        + E.N2 + " <b>Личная страница</b> \u2014 публикации на вашу стену\n\n"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        + E.INFO + " <i>К проекту можно подключить и группу, и личную страницу</i>"
    )


VK_TYPE_SELECT = _vk_type_select()


def _vk_personal_auth() -> str:
    """Build VK personal page auth step text."""
    from bot.texts.emoji import E

    return (
        E.VK + " <b>Подключение VK</b>\n\n"
        "Шаг 1/1 \u2014 Авторизуйте доступ к стене\n\n"
        + E.KEY + " <b>Инструкция:</b>\n\n"
        + E.N1 + " Нажмите <b>Авторизоваться</b> ниже\n\n"
        + E.N2 + " Нажмите <b>Разрешить</b> на странице VK\n\n"
        + E.N3 + " Вас перенаправит на страницу с предупреждением.\n"
        "   Это нормально \u2014 скопируйте <b>всю ссылку</b>\n"
        "   из адресной строки и отправьте сюда \u2b07\ufe0f\n\n"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        + E.LOCK + " <i>Токен хранится в зашифрованном виде</i>"
    )


VK_PERSONAL_AUTH = _vk_personal_auth()

# ---------------------------------------------------------------------------
# WordPress
# ---------------------------------------------------------------------------

WP_STEP1_URL = (
    f"{E.WORDPRESS}"
    " <b>Подключение WordPress</b>\n\n"
    "Шаг 1/3 \u2014 Введите адрес вашего сайта\n\n"
    "<i>Пример: example.com</i>"
)

WP_STEP2_LOGIN = (
    f"{E.WORDPRESS}"
    " <b>Подключение WordPress</b>\n\n"
    "Шаг 2/3 \u2014 Введите логин WordPress\n\n"
    "Это ваш логин для входа в панель управления\n"
    "WordPress (wp-admin).\n\n"
    "Обычно это имя пользователя, <b>не email</b>.\n"
    "Найти его можно: WP-Admin \u2192 Пользователи \u2192 Ваш профиль."
)

WP_STEP3_CREDENTIALS = (
    f"{E.WORDPRESS}"
    " <b>Подключение WordPress</b>\n\n"
    "Шаг 3/3 \u2014 Введите Application Password\n\n"
    "Как создать:\n"
    "1. Откройте WP-Admin \u2192 Пользователи \u2192 Профиль\n"
    "2. Прокрутите вниз до раздела <b>Application Passwords</b>\n"
    "3. Введите название (например: SEO Master)\n"
    "4. Нажмите <b>Добавить новый</b>\n"
    "5. Скопируйте сгенерированный пароль\n\n"
    "Формат: <code>xxxx xxxx xxxx xxxx xxxx xxxx</code>\n\n"
    "Пароль хранится в зашифрованном виде"
)

TG_STEP1_CHANNEL = (
    f"{E.TELEGRAM}"
    " <b>Подключение Telegram-канала</b>\n\n"
    "Шаг 1/2 \u2014 Введите ссылку на канал\n\n"
    "<i>Формат: @channel или t.me/channel</i>"
)

TG_STEP2_BOT_SETUP = (
    f"{E.TELEGRAM}"
    " <b>Подключение Telegram-канала</b>\n\n"
    "Шаг 2/2 \u2014 Создайте бота-публикатора\n\n"
    "Инструкция (30 секунд):\n"
    "1. Откройте @BotFather в Telegram\n"
    "2. Отправьте команду /newbot\n"
    "3. Придумайте имя (например: Мой Контент Бот)\n"
    "4. Скопируйте токен и вставьте сюда\n\n"
    "После этого добавьте бота <b>администратором</b>\n"
    "в ваш канал с правом публикации сообщений.\n\n"
    "Токен хранится в зашифрованном виде"
)
