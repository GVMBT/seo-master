"""Connection instruction texts for platform onboarding.

Uses E.* emoji constants from bot.texts.emoji for consistency.
All titles in CAPS per project UX standard.
"""

from bot.texts.emoji import E

_SEP = "\u2500" * 10

# ---------------------------------------------------------------------------
# VK
# ---------------------------------------------------------------------------

VK_STEP1_GROUP_URL = (
    f"{E.VK} <b>ПОДКЛЮЧЕНИЕ VK</b>\n\n"
    "Шаг 1/2 \u2014 Отправьте ссылку на группу VK\n\n"
    "Примеры:\n"
    "\u2022 https://vk.com/club123456\n"
    "\u2022 https://vk.com/mygroup\n"
    "\u2022 123456 (ID группы)\n\n"
    f"{_SEP}\n"
    f"{E.LIGHTBULB} <i>Нужна группа, в которой вы администратор</i>"
)

VK_STEP2_API_KEY = (
    f"{E.VK} <b>ПОДКЛЮЧЕНИЕ VK</b>\n\n"
    "Шаг 2/2 \u2014 Создайте ключ API\n"
    "Группа: <b>{{group_name}}</b>\n\n"
    f"{E.KEY} <b>Инструкция:</b>\n\n"
    f"{E.N1} Откройте настройки API группы:\n"
    '   <a href="https://vk.com/club{{group_id}}?act=tokens">Открыть настройки API</a>\n\n'
    f"{E.N2} Нажмите <b>Создать ключ</b>\n\n"
    f"{E.N3} Отметьте три галочки:\n"
    f"   {E.CHECK} Управление сообществом\n"
    f"   {E.CHECK} Доступ к фотографиям\n"
    f"   {E.CHECK} Доступ к стене\n\n"
    f"{E.N4} Подтвердите через SMS\n\n"
    f"{E.N5} Скопируйте ключ и вставьте сюда\n\n"
    f"{_SEP}\n"
    f"{E.LOCK} <i>Ключ хранится в зашифрованном виде</i>"
)


def _vk_step2_auth() -> str:
    """Build VK OAuth auth step text."""
    return (
        f"{E.VK} <b>ПОДКЛЮЧЕНИЕ VK</b>\n\n"
        "Шаг 2/2 \u2014 Авторизуйте доступ\n"
        "Группа: <b>{group_name}</b>\n\n"
        f"{E.KEY} <b>Инструкция:</b>\n\n"
        f"{E.N1} Нажмите <b>Авторизоваться</b> ниже\n\n"
        f"{E.N2} Нажмите <b>Разрешить</b> на странице VK\n\n"
        f"{E.N3} Вас перенаправит на страницу с предупреждением.\n"
        "   Это нормально \u2014 скопируйте <b>всю ссылку</b>\n"
        "   из адресной строки и отправьте сюда\n\n"
        f"{_SEP}\n"
        f"{E.LOCK} <i>Токен хранится в зашифрованном виде</i>"
    )


VK_STEP2_AUTH = _vk_step2_auth()

# Legacy OAuth URL
_VK_AUTH_URL = (
    "https://oauth.vk.com/authorize?"
    "client_id=2685278"
    "&scope=wall,photos,offline"
    "&response_type=token"
    "&redirect_uri=https://oauth.vk.com/blank.html"
    "&revoke=1"
)


def _vk_type_select() -> str:
    """Build VK type selection screen."""
    return (
        f"{E.VK} <b>ПОДКЛЮЧЕНИЕ VK</b>\n\n"
        "Выберите тип подключения:\n\n"
        f"{E.N1} <b>Группа</b> \u2014 публикации от имени сообщества\n"
        f"{E.N2} <b>Личная страница</b> \u2014 публикации на вашу стену\n\n"
        f"{_SEP}\n"
        f"{E.INFO} <i>К проекту можно подключить и группу, и личную страницу</i>"
    )


VK_TYPE_SELECT = _vk_type_select()


def _vk_personal_auth() -> str:
    """Build VK personal page auth step text."""
    return (
        f"{E.VK} <b>ПОДКЛЮЧЕНИЕ VK</b>\n\n"
        "Шаг 1/1 \u2014 Авторизуйте доступ к стене\n\n"
        f"{E.KEY} <b>Инструкция:</b>\n\n"
        f"{E.N1} Нажмите <b>Авторизоваться</b> ниже\n\n"
        f"{E.N2} Нажмите <b>Разрешить</b> на странице VK\n\n"
        f"{E.N3} Вас перенаправит на страницу с предупреждением.\n"
        "   Это нормально \u2014 скопируйте <b>всю ссылку</b>\n"
        "   из адресной строки и отправьте сюда\n\n"
        f"{_SEP}\n"
        f"{E.LOCK} <i>Токен хранится в зашифрованном виде</i>"
    )


VK_PERSONAL_AUTH = _vk_personal_auth()

# ---------------------------------------------------------------------------
# WordPress
# ---------------------------------------------------------------------------

WP_STEP1_URL = (
    f"{E.WORDPRESS} <b>ПОДКЛЮЧЕНИЕ WORDPRESS</b>\n\n"
    "Шаг 1/3 \u2014 Введите адрес вашего сайта\n\n"
    "<i>Пример: example.com</i>\n\n"
    f"{_SEP}\n"
    f"{E.LIGHTBULB} <i>Введите домен без http:// и www</i>"
)

WP_STEP2_LOGIN = (
    f"{E.WORDPRESS} <b>ПОДКЛЮЧЕНИЕ WORDPRESS</b>\n\n"
    "Шаг 2/3 \u2014 Введите логин WordPress\n\n"
    "Это ваш логин для входа в панель управления\n"
    "WordPress (wp-admin).\n\n"
    "Обычно это имя пользователя, <b>не email</b>.\n"
    "Найти его можно: WP-Admin \u2192 Пользователи \u2192 Ваш профиль.\n\n"
    f"{_SEP}\n"
    f"{E.LIGHTBULB} <i>Если не знаете логин — спросите администратора сайта</i>"
)

WP_STEP3_CREDENTIALS = (
    f"{E.WORDPRESS} <b>ПОДКЛЮЧЕНИЕ WORDPRESS</b>\n\n"
    "Шаг 3/3 \u2014 Введите Application Password\n\n"
    f"{E.KEY} <b>Как создать:</b>\n\n"
    f"{E.N1} Откройте WP-Admin \u2192 Пользователи \u2192 Профиль\n\n"
    f"{E.N2} Прокрутите вниз до <b>Application Passwords</b>\n\n"
    f"{E.N3} Введите название (например: SEO Master)\n\n"
    f"{E.N4} Нажмите <b>Добавить новый</b>\n\n"
    f"{E.N5} Скопируйте сгенерированный пароль\n\n"
    "Формат: <code>xxxx xxxx xxxx xxxx xxxx xxxx</code>\n\n"
    f"{_SEP}\n"
    f"{E.LOCK} <i>Пароль хранится в зашифрованном виде</i>"
)

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

TG_STEP1_CHANNEL = (
    f"{E.TELEGRAM} <b>ПОДКЛЮЧЕНИЕ TELEGRAM</b>\n\n"
    "Шаг 1/2 \u2014 Введите ссылку на канал\n\n"
    "<i>Формат: @channel или t.me/channel</i>\n\n"
    f"{_SEP}\n"
    f"{E.LIGHTBULB} <i>Бот будет публиковать посты в этот канал</i>"
)

TG_STEP2_BOT_SETUP = (
    f"{E.TELEGRAM} <b>ПОДКЛЮЧЕНИЕ TELEGRAM</b>\n\n"
    "Шаг 2/2 \u2014 Создайте бота-публикатора\n\n"
    f"{E.KEY} <b>Инструкция:</b>\n\n"
    f"{E.N1} Откройте @BotFather в Telegram\n\n"
    f"{E.N2} Отправьте команду /newbot\n\n"
    f"{E.N3} Придумайте имя (например: Мой Контент Бот)\n\n"
    f"{E.N4} Скопируйте токен и вставьте сюда\n\n"
    "После этого добавьте бота <b>администратором</b>\n"
    "в ваш канал с правом публикации сообщений.\n\n"
    f"{_SEP}\n"
    f"{E.LOCK} <i>Токен хранится в зашифрованном виде</i>"
)
