"""Connection instruction texts for platform onboarding.

Premium emoji IDs from screen/icons/:
- 5305396259765394964 = VK logo
- 5305702774401439462 = WordPress logo
- 5305643301989290953 = Telegram logo
- 5305635128666526830 = key
- 5305748374069221919 = lock
"""

# ---------------------------------------------------------------------------
# VK
# ---------------------------------------------------------------------------

VK_STEP1_GROUP_URL = (
    '<tg-emoji emoji-id="5305396259765394964">\U0001f535</tg-emoji>'
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
    '<tg-emoji emoji-id="5305396259765394964">\U0001f535</tg-emoji>'
    " <b>Подключение VK</b>\n\n"
    "Шаг 2/2 \u2014 Создайте ключ API\n"
    "Группа: <b>{group_name}</b>\n\n"
    '<tg-emoji emoji-id="5305635128666526830">\U0001f511</tg-emoji>'
    " <b>Инструкция:</b>\n\n"
    '<tg-emoji emoji-id="5305338243347157769">1\ufe0f\u20e3</tg-emoji>'
    " Откройте настройки API группы:\n"
    '   <a href="https://vk.com/club{group_id}?act=tokens">Открыть настройки API</a>\n\n'
    '<tg-emoji emoji-id="5307730153583972349">2\ufe0f\u20e3</tg-emoji>'
    " Нажмите <b>Создать ключ</b>\n\n"
    '<tg-emoji emoji-id="5305563909518825468">3\ufe0f\u20e3</tg-emoji>'
    " Отметьте три галочки:\n"
    '   <tg-emoji emoji-id="5307785824950064221">\u2705</tg-emoji>'
    " Управление сообществом\n"
    '   <tg-emoji emoji-id="5307785824950064221">\u2705</tg-emoji>'
    " Доступ к фотографиям\n"
    '   <tg-emoji emoji-id="5307785824950064221">\u2705</tg-emoji>'
    " Доступ к стене\n\n"
    '<tg-emoji emoji-id="5305799131992730110">4\ufe0f\u20e3</tg-emoji>'
    " Подтвердите через SMS\n\n"
    '<tg-emoji emoji-id="5307500080775863670">5\ufe0f\u20e3</tg-emoji>'
    " Скопируйте ключ и вставьте сюда \u2b07\ufe0f\n\n"
    "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
    '<tg-emoji emoji-id="5305748374069221919">\U0001f512</tg-emoji>'
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

    # Use replace for {group_name} placeholder since f-strings consume braces
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

# ---------------------------------------------------------------------------
# WordPress
# ---------------------------------------------------------------------------

WP_STEP1_URL = (
    '<tg-emoji emoji-id="5305702774401439462">🌐</tg-emoji>'
    " <b>Подключение WordPress</b>\n\n"
    "Шаг 1/3 — Введите адрес вашего сайта\n\n"
    "<i>Пример: example.com</i>"
)

WP_STEP2_LOGIN = (
    '<tg-emoji emoji-id="5305702774401439462">🌐</tg-emoji>'
    " <b>Подключение WordPress</b>\n\n"
    "Шаг 2/3 — Введите логин WordPress\n\n"
    "Это ваш логин для входа в панель управления\n"
    "WordPress (wp-admin).\n\n"
    "Обычно это имя пользователя, <b>не email</b>.\n"
    "Найти его можно: WP-Admin → Пользователи → Ваш профиль."
)

WP_STEP3_CREDENTIALS = (
    '<tg-emoji emoji-id="5305702774401439462">🌐</tg-emoji>'
    " <b>Подключение WordPress</b>\n\n"
    "Шаг 3/3 — Введите Application Password\n\n"
    "Как создать:\n"
    "1. Откройте WP-Admin → Пользователи → Профиль\n"
    "2. Прокрутите вниз до раздела <b>Application Passwords</b>\n"
    "3. Введите название (например: SEO Master)\n"
    "4. Нажмите <b>Добавить новый</b>\n"
    "5. Скопируйте сгенерированный пароль\n\n"
    "Формат: <code>xxxx xxxx xxxx xxxx xxxx xxxx</code>\n\n"
    "Пароль хранится в зашифрованном виде"
)

TG_STEP1_CHANNEL = (
    '<tg-emoji emoji-id="5305643301989290953">✈</tg-emoji>'
    " <b>Подключение Telegram-канала</b>\n\n"
    "Шаг 1/2 — Введите ссылку на канал\n\n"
    "<i>Формат: @channel или t.me/channel</i>"
)

TG_STEP2_BOT_SETUP = (
    '<tg-emoji emoji-id="5305643301989290953">✈</tg-emoji>'
    " <b>Подключение Telegram-канала</b>\n\n"
    "Шаг 2/2 — Создайте бота-публикатора\n\n"
    "Инструкция (30 секунд):\n"
    "1. Откройте @BotFather в Telegram\n"
    "2. Отправьте команду /newbot\n"
    "3. Придумайте имя (например: Мой Контент Бот)\n"
    "4. Скопируйте токен и вставьте сюда\n\n"
    "После этого добавьте бота <b>администратором</b>\n"
    "в ваш канал с правом публикации сообщений.\n\n"
    "Токен хранится в зашифрованном виде"
)
