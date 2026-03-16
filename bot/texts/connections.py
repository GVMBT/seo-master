"""Connection instruction texts for platform onboarding.

Uses Emoji constants from bot.texts.emoji for consistent custom emoji rendering.
"""

from bot.texts.emoji import Emoji

# ---------------------------------------------------------------------------
# VK
# ---------------------------------------------------------------------------

VK_STEP1_GROUP_URL = (
    f"{Emoji.VK} <b>Подключение VK</b>\n\n"
    f"{Emoji.NUM_1} Отправьте ссылку на группу VK, к которой\n"
    "хотите подключиться.\n\n"
    f"{Emoji.LIGHTBULB} Примеры:\n"
    "\u2022 https://vk.com/club123456\n"
    "\u2022 https://vk.com/mygroup\n"
    "\u2022 123456 (ID группы)"
)

VK_STEP2_OAUTH = (
    f"{Emoji.VK} <b>Подключение VK</b>\n\n"
    "Группа найдена: <b>{group_name}</b>\n\n"
    f"{Emoji.NUM_2} Нажмите кнопку ниже, чтобы предоставить\n"
    "доступ на публикацию.\n\n"
    f"{Emoji.LOCK} Токен хранится в зашифрованном виде"
)

# ---------------------------------------------------------------------------
# WordPress
# ---------------------------------------------------------------------------

WP_STEP1_URL = (
    f"{Emoji.WORDPRESS} <b>Подключение WordPress</b>\n\n"
    f"{Emoji.NUM_1} Введите адрес вашего сайта\n\n"
    f"{Emoji.INFO} <i>Пример: example.com</i>"
)

WP_STEP2_LOGIN = (
    f"{Emoji.WORDPRESS} <b>Подключение WordPress</b>\n\n"
    f"{Emoji.NUM_2} Введите логин WordPress\n\n"
    "Это ваш логин для входа в панель управления\n"
    "WordPress (wp-admin).\n\n"
    f"{Emoji.LIGHTBULB} Обычно это имя пользователя, <b>не email</b>.\n"
    "Найти его можно: WP-Admin \u2192 Пользователи \u2192 Ваш профиль."
)

WP_STEP3_CREDENTIALS = (
    f"{Emoji.WORDPRESS} <b>Подключение WordPress</b>\n\n"
    f"{Emoji.NUM_3} Введите Application Password\n\n"
    f"{Emoji.LIGHTBULB} Как создать:\n"
    f"{Emoji.NUM_1} Откройте WP-Admin \u2192 Пользователи \u2192 Профиль\n"
    f"{Emoji.NUM_2} Прокрутите вниз до раздела <b>Application Passwords</b>\n"
    f"{Emoji.NUM_3} Введите название (например: SEO Master)\n"
    f"{Emoji.NUM_4} Нажмите <b>Добавить новый</b>\n"
    f"{Emoji.NUM_5} Скопируйте сгенерированный пароль\n\n"
    f"{Emoji.INFO} Формат: <code>xxxx xxxx xxxx xxxx xxxx xxxx</code>\n\n"
    f"{Emoji.LOCK} Пароль хранится в зашифрованном виде"
)

TG_STEP1_CHANNEL = (
    f"{Emoji.TELEGRAM} <b>Подключение Telegram-канала</b>\n\n"
    f"{Emoji.NUM_1} Введите ссылку на канал\n\n"
    f"{Emoji.INFO} <i>Формат: @channel или t.me/channel</i>"
)

TG_STEP2_BOT_SETUP = (
    f"{Emoji.TELEGRAM} <b>Подключение Telegram-канала</b>\n\n"
    f"{Emoji.NUM_2} Создайте бота-публикатора\n\n"
    f"{Emoji.LIGHTBULB} Инструкция (30 секунд):\n"
    f"{Emoji.NUM_1} Откройте @BotFather в Telegram\n"
    f"{Emoji.NUM_2} Отправьте команду /newbot\n"
    f"{Emoji.NUM_3} Придумайте имя (например: Мой Контент Бот)\n"
    f"{Emoji.NUM_4} Скопируйте токен и вставьте сюда\n\n"
    "После этого добавьте бота <b>администратором</b>\n"
    "в ваш канал с правом публикации сообщений.\n\n"
    f"{Emoji.LOCK} Токен хранится в зашифрованном виде"
)
