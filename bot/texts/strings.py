"""All user-facing strings -- single source of truth for bot copywriting."""

# -----------------------------------------------
# Dashboard
# -----------------------------------------------
WELCOME_TITLE = "ДОБРО ПОЖАЛОВАТЬ"
WELCOME_TEXT = (
    "Привет{name_part}! "
    "Я напишу SEO-статьи и посты для вашего бизнеса "
    "и опубликую на сайт и в соцсети."
)
WELCOME_HINT = "Создайте первый проект \u2014 это займёт 30 секунд"
BALANCE_ESTIMATE = "Хватит на ~{articles} статей"
BALANCE_ESTIMATE_FULL = "Хватит на ~{articles} статей или ~{posts} постов"
BALANCE_ZERO_TITLE = "Баланс: 0 токенов"
BALANCE_ZERO = "Для генерации контента нужно пополнить баланс."
BALANCE_NEGATIVE_TITLE = "Баланс: {balance} токенов"
BALANCE_NEGATIVE = (
    "Долг {debt} токенов будет списан при следующей покупке.\n"
    "Для генерации контента пополните баланс."
)
NO_PROJECTS = "У вас пока нет проектов."
NO_PROJECTS_HINT = "Создайте первый \u2014 это займёт 30 секунд."
LAST_PUB = "Последняя: \u00ab{keyword}\u00bb{suffix}"
FORECAST = "~{weekly} ток/нед  \u00b7  ~{monthly} ток/мес"

# -----------------------------------------------
# Projects
# -----------------------------------------------
PROJECTS_TITLE = "ПРОЕКТЫ"
PROJECT_CARD_HINT = "Добавьте категории и подключите площадки"
PROJECT_EDIT_TITLE = "РЕДАКТИРОВАНИЕ"
PROJECT_EDIT_HINT = "Нажмите на поле для редактирования"
PROJECT_EDIT_PROMPT = "Введите новое значение"
PROJECT_EDIT_CURRENT = "Текущее значение:"
PROJECT_EDIT_EMPTY = "не заполнено"
PROJECT_EDIT_UPDATED = "Поле \u00ab{label}\u00bb обновлено."

PROJECT_CREATE_TITLE = "НОВЫЙ ПРОЕКТ"
PROJECT_CREATE_QUESTION = "Как назовём проект?"
PROJECT_CREATE_HINT = "Пример: Мебель Комфорт"
PROJECT_CREATED = "Проект \u00ab{name}\u00bb создан!"
PROJECT_CREATE_CANCELLED = "Создание проекта отменено."
PROJECT_EDIT_CANCELLED = "Редактирование отменено."

PROJECT_DELETE_TITLE = "УДАЛЕНИЕ ПРОЕКТА"
PROJECT_DELETE_QUESTION = "Удалить проект \u00ab{name}\u00bb?"
PROJECT_DELETE_LIST_HEADER = "Будут удалены:"
PROJECT_DELETE_ITEMS = [
    "Все категории и ключевые фразы",
    "Подключения к платформам",
    "Расписания автопубликации",
]
PROJECT_DELETE_NOTE = "Уже опубликованные статьи на сайте останутся."
PROJECT_DELETE_WARNING = "Это действие нельзя отменить"
PROJECT_DELETED = "Проект \u00ab{name}\u00bb удалён."
PROJECT_DELETE_ERROR = "Не удалось удалить проект. Попробуйте позже."

PROJECT_LIMIT_REACHED = "Достигнут лимит проектов ({limit})."
PROJECT_NOT_FOUND = "Проект не найден."

PLATFORMS_NOT_CONNECTED = "Платформы: не подключены"

# -----------------------------------------------
# Project fields
# -----------------------------------------------
FIELD_LABELS: dict[str, str] = {
    "name": "название проекта",
    "company_name": "название компании",
    "specialization": "специализацию",
    "website_url": "URL сайта",
    "description": "описание компании",
    "advantages": "преимущества",
    "experience": "опыт работы",
    "company_city": "город",
    "company_address": "адрес",
    "company_phone": "телефон",
    "company_email": "email",
}

FIELD_DISPLAY: dict[str, str] = {
    "name": "Название проекта",
    "company_name": "Название компании",
    "specialization": "Специализация",
    "website_url": "URL сайта",
    "description": "Описание компании",
    "advantages": "Преимущества",
    "experience": "Опыт работы",
    "company_city": "Город",
    "company_address": "Адрес",
    "company_phone": "Телефон",
    "company_email": "Email",
}

SECTION_BASIC = "Основное"
SECTION_ABOUT = "О компании"
SECTION_CONTACTS = "Контакты"

# -----------------------------------------------
# Categories
# -----------------------------------------------
CATEGORY_EMPTY = "Категорий пока нет."
CATEGORY_EMPTY_HINT = (
    "Категория = тема контента "
    "(например: \u00abSEO-оптимизация\u00bb или \u00abКулинарные рецепты\u00bb)."
)
CATEGORY_CREATED = (
    "Категория \u00ab{name}\u00bb создана!\n"
    "Теперь добавьте ключевые фразы \u2014 без них невозможна генерация статей."
)
CATEGORY_CREATE_PROMPT = "Введите название категории."
CATEGORY_CREATE_EXAMPLE = "Пример: Кухни на заказ"
CATEGORY_CREATE_CANCELLED = "Создание категории отменено."
CATEGORY_NAME_LENGTH = "Название: от 2 до 100 символов."
CATEGORY_HINT = "Заполните все пункты \u2014 статьи будут качественнее"

CATEGORY_DELETE_QUESTION = "Удалить категорию \u00ab{name}\u00bb?"
CATEGORY_DELETE_SCHEDULES = "Будет отменено расписаний: {count}"
CATEGORY_DELETE_WARNING = "Это действие нельзя отменить."
CATEGORY_DELETED = "Категория \u00ab{name}\u00bb удалена."
CATEGORY_DELETE_ERROR = "Не удалось удалить категорию. Попробуйте позже."
CATEGORY_NOT_FOUND = "Категория не найдена."
CATEGORY_LIMIT_REACHED = "Достигнут лимит категорий ({limit}) в проекте."
CATEGORY_NEEDS_WEBSITE = "Сначала заполните информацию о проекте (укажите сайт)."

# -----------------------------------------------
# Keywords
# -----------------------------------------------
KEYWORDS_EMPTY = "Фразы не добавлены. Без них бот не знает о чём писать статьи."
KEYWORDS_HINT = "Ключевики \u2014 основа для качественных статей"
KEYWORDS_DELETED_ALL = "Все фразы удалены."
KEYWORDS_CLUSTER_DELETED = "Группа \u00ab{name}\u00bb удалена."
KEYWORDS_CLUSTER_DELETED_EMPTY = "Группа \u00ab{name}\u00bb удалена. Фразы закончились."
KEYWORDS_DELETE_ALL_TITLE = "УДАЛЕНИЕ КЛЮЧЕВЫХ ФРАЗ"
KEYWORDS_DELETE_ALL_QUESTION = "Удалить все фразы ({total} фраз, {clusters} групп)?"
KEYWORDS_DELETE_ALL_WARNING = "Это действие необратимо."
KEYWORDS_SELECT_DELETE = "Выберите группу фраз для удаления:"
KEYWORDS_UPLOAD_PROMPT = (
    "Загрузите текстовый файл (.txt) с ключевыми фразами.\n"
    "Каждая фраза на отдельной строке.\n\n"
    "Максимум: {max_phrases} фраз, {max_size_mb} МБ."
)
KEYWORDS_GENERATION_CANCELLED = "Подбор фраз отменён."
KEYWORDS_UPLOAD_CANCELLED = "Загрузка отменена."
KEYWORDS_GEO_PROMPT = (
    "Укажите географию продвижения:\n"
    "<i>Например: Москва, Россия, СНГ</i>\n\nОт 2 до 200 символов."
)

# -----------------------------------------------
# Description
# -----------------------------------------------
DESCRIPTION_HINT = "Описание помогает AI писать точнее"
DESCRIPTION_EMPTY = "Описание не задано."
DESCRIPTION_EMPTY_DETAIL = (
    "Расскажите о вашем бизнесе в этой категории \u2014 "
    "AI будет писать точнее и убедительнее."
)
DESCRIPTION_GENERATED_TITLE = "ОПИСАНИЕ СГЕНЕРИРОВАНО"
DESCRIPTION_MANUAL_PROMPT = "Введите описание категории (10\u20132000 символов):"
DESCRIPTION_MANUAL_LENGTH = "Описание: от 10 до 2000 символов."
DESCRIPTION_MANUAL_CANCELLED = "Ввод описания отменён."
DESCRIPTION_GENERATING = "Генерирую описание..."
DESCRIPTION_GENERATION_ERROR = "AI-сервис временно недоступен. Попробуйте через минуту."

# -----------------------------------------------
# Prices
# -----------------------------------------------
PRICES_HINT = "В статьях будут реальные цены ваших товаров"
PRICES_EMPTY = "Прайс не загружен. Добавьте \u2014 в статьях будут реальные цены."
PRICES_LOADED = "Прайс загружен"
PRICES_TEXT_PROMPT = (
    "Введите прайс-лист. Формат: Название \u2014 Цена\n"
    "Каждый товар с новой строки.\n\n"
    "<i>Пример:\n"
    "Кухня угловая \u00abМодена\u00bb \u2014 89 900 руб\n"
    "Стол обеденный \u00abЛофт\u00bb \u2014 24 500 руб</i>"
)
PRICES_TEXT_EMPTY = (
    "Не найдено ни одной строки. Введите прайс в формате:\n"
    "Название \u2014 Цена\nКаждый товар с новой строки."
)
PRICES_TEXT_MAX_ROWS = "Максимум {max} строк. Сейчас: {count}."
PRICES_SAVED = "Прайс сохранён ({count} позиций)"
PRICES_EXCEL_PROMPT = (
    "Загрузите Excel-файл (.xlsx) с прайсом.\n"
    "Будут использованы все столбцы. Заголовки распознаются автоматически."
)
PRICES_EXCEL_UPLOADED = "Файл загружен ({count} позиций)"
PRICES_CANCELLED = "Ввод цен отменён."
PRICES_DELETED = "Прайс удалён."
PRICES_EXCEL_WRONG_FORMAT = "Неверный формат. Загрузите файл с расширением .xlsx."
PRICES_EXCEL_TOO_BIG = "Файл слишком большой ({size_mb:.1f} МБ). Максимум 5 МБ."
PRICES_EXCEL_EMPTY = "Файл пуст. Загрузите файл с данными."
PRICES_EXCEL_NO_DATA = "В файле не найдено данных. Загрузите файл с заполненными строками."
PRICES_EXCEL_READ_ERROR = "Не удалось прочитать файл. Убедитесь, что это корректный .xlsx."
PRICES_EXCEL_EXPECT = "Ожидается файл Excel (.xlsx). Для отмены напишите \u00abОтмена\u00bb."

# -----------------------------------------------
# Connections
# -----------------------------------------------
CONNECTIONS_TITLE = "МОИ ПОДКЛЮЧЕНИЯ"
CONNECTIONS_EMPTY = "Подключений пока нет. Подключите сайт или соцсеть для автопубликации."
CONNECTIONS_HINT = "Подключите площадки для автопостинга контента"
CONNECTIONS_MANAGE_HINT = "Проверяйте статус и удаляйте неактивные подключения"
CONNECTIONS_NOT_FOUND = "Подключение не найдено."
CONNECTIONS_DELETE_TITLE = "УДАЛЕНИЕ ПОДКЛЮЧЕНИЯ"
CONNECTIONS_DELETE_LIST_HEADER = "Будут удалены:"
CONNECTIONS_DELETE_ITEMS = [
    "Связанные расписания",
    "Настройки кросс-постинга",
]
CONNECTIONS_DELETE_WARNING = "Это действие нельзя отменить"
CONNECTIONS_CANCELLED = "Подключение отменено."
CONNECTIONS_WP_ALREADY = (
    "К проекту уже подключён WordPress-сайт. Для другого сайта создайте новый проект."
)
CONNECTIONS_TG_ALREADY = (
    "К проекту уже подключён Telegram-канал. Для другого канала создайте новый проект."
)
CONNECTIONS_VK_ALREADY = (
    "К проекту уже подключена VK-группа. Для другой группы создайте новый проект."
)
CONNECTIONS_PINTEREST_ALREADY = (
    "К проекту уже подключён Pinterest. Для другой доски создайте новый проект."
)

CONNECTIONS_STATUS_ACTIVE = "Активно"
CONNECTIONS_STATUS_ERROR = "Ошибка"

# -----------------------------------------------
# Profile
# -----------------------------------------------
PROFILE_TITLE = "ПРОФИЛЬ"
PROFILE_HINT = "Пополняйте баланс и приглашайте друзей для бонусов"

NOTIFICATIONS_TITLE = "УВЕДОМЛЕНИЯ"
NOTIFICATIONS_PROMPT = "Выберите типы уведомлений:"
NOTIFICATIONS_PUBLICATIONS = "Публикации \u2014 уведомления об автопубликациях и ошибках"
NOTIFICATIONS_BALANCE = "Баланс \u2014 предупреждение о низком балансе и пополнениях"
NOTIFICATIONS_NEWS = "Новости \u2014 новые возможности и обновления бота"
NOTIFICATIONS_HINT = "Нажмите для переключения"
NOTIFICATIONS_UPDATE_ERROR = "Ошибка обновления. Попробуйте позже."

REFERRAL_TITLE = "РЕФЕРАЛЬНАЯ ПРОГРАММА"
REFERRAL_DESC = (
    "Приглашайте друзей и получайте <b>10%</b> от каждой их покупки!\n"
    "Бонус начисляется автоматически при каждой оплате реферала."
)
REFERRAL_HINT = "Скопируйте ссылку и отправьте друзьям"

DELETE_ACCOUNT_TITLE = "УДАЛЕНИЕ АККАУНТА"
DELETE_ACCOUNT_LIST_HEADER = "Будут безвозвратно удалены:"
DELETE_ACCOUNT_ITEMS = [
    "Все проекты и категории",
    "Все подключения к платформам",
    "Все расписания автопубликации",
    "Активные превью статей",
]
DELETE_ACCOUNT_ANON = "Токены и история платежей будут анонимизированы."
DELETE_ACCOUNT_WARNING = "Это действие необратимо."
DELETE_ACCOUNT_SUCCESS = "Ваш аккаунт и все данные удалены.\n\nВы можете начать заново с /start"
DELETE_ACCOUNT_ERROR = "Произошла ошибка при удалении аккаунта. Обратитесь в поддержку."
DELETE_ACCOUNT_CANCELLED = "Удаление отменено."

# -----------------------------------------------
# Pipeline
# -----------------------------------------------
ARTICLE_READY_TITLE = "СТАТЬЯ ГОТОВА"
ARTICLE_PUBLISHED_TITLE = "СТАТЬЯ ОПУБЛИКОВАНА"
ARTICLE_ERROR_TITLE = "НЕ УДАЛОСЬ СГЕНЕРИРОВАТЬ"
ARTICLE_ERROR_REFUND = "Токены возвращены на баланс."
ARTICLE_ERROR_HINT = "Попробуйте через 5 минут \u2014 обычно помогает"
ARTICLE_CANCELLED = "Статья отменена. Токены возвращены."
ARTICLE_PREVIEW_UNAVAILABLE = "(Превью недоступно, фрагмент ниже)"

PIPELINE_READINESS_TITLE = "СТАТЬЯ (4/5) \u2014 ПОДГОТОВКА"
PIPELINE_CONFIRM_TITLE = "СТАТЬЯ (5/5) \u2014 ПОДТВЕРЖДЕНИЕ"
PIPELINE_COST_GOD = "Стоимость: ~{cost} ток. (GOD_MODE \u2014 бесплатно)"
PIPELINE_COST_NORMAL = "Стоимость: ~{cost} ток."
PIPELINE_SESSION_EXPIRED = "Данные сессии устарели."
PIPELINE_CATEGORY_NOT_SET = "Категория не выбрана. Начните заново."
PIPELINE_NO_KEYWORDS = "Нет доступных ключевых фраз. Добавьте их в категорию."
PIPELINE_INSUFFICIENT_BALANCE = "Недостаточно токенов."

PIPELINE_PROGRESS_TITLE = "Генерация статьи"
PIPELINE_PUBLISH_TITLE = "Публикация"
PIPELINE_STEP_SERPER = ("Сбор данных из Google", "Данные собраны")
PIPELINE_STEP_COMPETITORS = ("Анализ конкурентов", "Конкуренты проанализированы")
PIPELINE_STEP_GENERATE = ("Генерация текста и изображений", "Текст и изображения готовы")
PIPELINE_STEP_PREVIEW = ("Подготовка предпросмотра", "Предпросмотр готов")

PIPELINE_PRICES_QUESTION = "Добавить прайс-лист?\n\nВ статье будут реальные цены ваших товаров."
PIPELINE_PRICES_TEXT_PROMPT = (
    "Введите прайс-лист текстом.\n"
    "Формат: Товар \u2014 Цена (каждый с новой строки).\n\n"
    "<i>Пример:\nКухня Прага \u2014 от 120 000 руб.\nШкаф-купе \u2014 от 45 000 руб.</i>"
)
PIPELINE_PRICES_EXCEL_PROMPT = (
    "Загрузите Excel-файл (.xlsx) с прайсом.\n"
    "Колонки: A \u2014 Название, B \u2014 Цена, C \u2014 Описание (опц.).\n"
    "Максимум 1000 строк, 5 МБ."
)
PIPELINE_PRICES_SAVED = "Сохранено {count} позиций."
PIPELINE_PRICES_EXCEL_UPLOADED = "Загружено {count} позиций из Excel."
PIPELINE_PRICES_SAVE_ERROR = "Не удалось сохранить цены. Попробуйте снова."

PIPELINE_IMAGES_CURRENT = "Изображения \u2014 сейчас: {count} AI\n\nВыберите количество:"

PIPELINE_WP_CONNECT_URL = "Подключение WordPress\n\nВведите адрес вашего сайта.\n<i>Пример: example.com</i>"
PIPELINE_WP_CONNECT_LOGIN = (
    "Подключение WordPress\n\n"
    "Сайт: {url}\n\n"
    "Введите логин WordPress (имя пользователя)."
)
PIPELINE_WP_NOT_FOUND = "WordPress-подключение не найдено. Проверьте настройки."
PIPELINE_WP_PUBLISH_ERROR = "Ошибка публикации на WordPress. Попробуйте снова."
PIPELINE_PUBLISH_LOCKED = "Публикация уже выполняется..."
PIPELINE_PREVIEW_EXPIRED = "Превью устарело или уже опубликовано."

PIPELINE_TOPIC_TITLE = "Статья (3/5) \u2014 Тема"
PIPELINE_TOPIC_QUESTION = "О чём будет статья? Назовите тему."
PIPELINE_TOPIC_WHICH = "Какая тема?"

# -----------------------------------------------
# Scheduler
# -----------------------------------------------
SCHEDULER_TITLE = "ПЛАНИРОВЩИК"
SCHEDULER_TYPE_PROMPT = "Выберите тип контента:"
SCHEDULER_ARTICLES_TITLE = "ПЛАНИРОВЩИК \u2014 Статьи"
SCHEDULER_SOCIAL_TITLE = "ПЛАНИРОВЩИК \u2014 Соцсети"
SCHEDULER_SELECT_CATEGORY = "Выберите категорию:"
SCHEDULER_SELECT_CONNECTION = "Выберите подключение для настройки расписания:"
SCHEDULE_TITLE = "РАСПИСАНИЕ"
SCHEDULE_SOCIAL_TITLE = "РАСПИСАНИЕ (соцсети)"
SCHEDULE_SET_TITLE = "РАСПИСАНИЕ УСТАНОВЛЕНО"
SCHEDULE_DISABLED = "Расписание отключено."
SCHEDULE_HINT = "Бот будет автоматически создавать и публиковать контент"
SCHEDULE_SOCIAL_HINT = "Бот будет создавать и публиковать посты в соцсети"
SCHEDULE_CURRENT = "Текущее расписание:"
SCHEDULE_SELECT_OPTION = "Выберите вариант:"
SCHEDULE_SELECT_DAYS = "Выберите дни публикации:"
SCHEDULE_SELECT_COUNT = "Сколько постов в день?"
SCHEDULE_SELECT_TIMES = "Выберите {count} временных слотов:"
SCHEDULE_CANCELLED = "Настройка расписания отменена."
SCHEDULE_COST_ESTIMATE = "Ориент. расход: ~{cost} токенов/нед"
SCHEDULE_NO_CATEGORIES = "Сначала создайте категорию в карточке проекта"
SCHEDULE_NO_WP = "Нет WordPress-подключений. Добавьте платформу."
SCHEDULE_NO_SOCIAL = "Нет подключённых соцсетей"

CROSSPOST_TITLE = "Кросс-постинг"
CROSSPOST_COST = "Стоимость: ~10 ток/пост за кросс-пост."
CROSSPOST_PROMPT = "Выберите платформы для автоматической адаптации поста."
CROSSPOST_SAVED = "Кросс-постинг сохранён: {count} платформ."
CROSSPOST_DISABLED = "Кросс-постинг отключён."

# -----------------------------------------------
# Tariffs / Payments
# -----------------------------------------------
TARIFFS_TITLE = "ПАКЕТЫ ТОКЕНОВ"
TARIFF_HINT = "1 токен = 1 рубль. Оплата через Telegram Stars или банковскую карту."
TARIFF_COST_HEADER = "СТОИМОСТЬ ГЕНЕРАЦИИ"
TARIFF_COST_TEXT = "Текст (100 слов) \u2014 10 токенов"
TARIFF_COST_IMAGE = "Изображение \u2014 30 токенов"
TARIFF_BALANCE_LINE = "Ваш баланс: <b>{balance}</b> токенов"
TARIFF_ESTIMATE = "Хватит на ~{articles} статей или ~{posts} постов"

PAYMENT_PACKAGE_SELECT = "Выберите способ оплаты:"
PAYMENT_LINK_TEXT = "Нажмите кнопку для перехода на страницу оплаты."
PAYMENT_PRE_CHECKOUT_ERROR = "Некорректный формат платежа."
PAYMENT_USER_MISMATCH = "Ошибка идентификации пользователя."
PAYMENT_PACKAGE_NOT_FOUND = "Пакет не найден."
PAYMENT_UNKNOWN_TYPE = "Неизвестный тип платежа."
PAYMENT_REFUND_NOT_FOUND = "Платёж не найден."

# -----------------------------------------------
# Admin
# -----------------------------------------------
ADMIN_TITLE = "АДМИН-ПАНЕЛЬ"
ADMIN_ACCESS_DENIED = "Доступ запрещён"
MONITORING_TITLE = "МОНИТОРИНГ"
BROADCAST_TITLE = "РАССЫЛКА"
BROADCAST_AUDIENCE_PROMPT = "Выберите аудиторию:"
BROADCAST_TEXT_PROMPT = "Отправьте текст сообщения:"
BROADCAST_PREVIEW_TITLE = "Предпросмотр рассылки"
BROADCAST_DONE = "Рассылка завершена"
BROADCAST_SENDING = "Рассылка... ({sent}/{total})"
API_COSTS_TITLE = "ЗАТРАТЫ API"
ADMIN_USER_NOT_FOUND = "Пользователь не найден."
ADMIN_USER_LOOKUP_PROMPT = "Отправьте ID (число) или @username:"
ADMIN_BALANCE_INPUT = "Введите сумму для {action} (целое число):"
ADMIN_BALANCE_CREDIT_LABEL = "начисления"
ADMIN_BALANCE_DEBIT_LABEL = "списания"
ADMIN_BALANCE_INPUT_ERROR = "Введите положительное целое число."
ADMIN_BALANCE_DONE = "{verb}: {amount} токенов\nНовый баланс: {balance}"
ADMIN_BLOCK_SELF = "Нельзя заблокировать себя"
ADMIN_NO_PUBLICATIONS = "Публикаций нет."

AUDIENCE_LABELS: dict[str, str] = {
    "all": "Все пользователи",
    "active_7d": "Активные 7 дней",
    "active_30d": "Активные 30 дней",
    "paid": "Оплатившие",
}

# -----------------------------------------------
# Common
# -----------------------------------------------
ERROR_GENERIC = "Что-то пошло не так. Попробуйте через пару минут."
ERROR_NOT_FOUND = "Не найдено."
ERROR_UPDATE = "Ошибка обновления. Попробуйте позже."
ERROR_SERVER_CONFIG = "Ошибка конфигурации сервера. Попробуйте позже."
ERROR_INTERNAL = "Внутренняя ошибка. Попробуйте позже."
CANCELLED = "Отменено."
UNKNOWN_FIELD = "Неизвестное поле."
VALIDATION_NAME_LENGTH = "Название: от 2 до 100 символов."
VALIDATION_URL_INVALID = "Не удалось распознать адрес. Введите в формате: example.com"
VALIDATION_URL_TOO_LONG = "URL слишком длинный (макс. {max} символов)."
VALIDATION_FIELD_LENGTH = "Значение: от {min} до {max} символов."
VALIDATION_LOGIN_LENGTH = "Логин: от 1 до 100 символов."
VALIDATION_TOKEN_INVALID = "Неверный формат токена. Скопируйте его заново из BotFather."  # noqa: S105
VALIDATION_CHANNEL_INVALID = "Неверный формат. Введите @channel, t.me/channel или ID (-100...)."
VALIDATION_PASSWORD_SHORT = (
    "Пароль слишком короткий."  # noqa: S105
    " Скопируйте Application Password из WordPress целиком."
)
FSM_INTERRUPTED = "Предыдущий процесс ({name}) прерван."
FILE_NOT_FOUND = "Файл не найден."
FILE_DOWNLOAD_ERROR = "Не удалось скачать файл. Попробуйте ещё раз."
