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
BALANCE_ZERO_TITLE = "БАЛАНС: 0 ТОКЕНОВ"
BALANCE_ZERO = "Для генерации контента нужно пополнить баланс."
BALANCE_NEGATIVE_TITLE = "БАЛАНС: {balance} ТОКЕНОВ"
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
PROJECTS_LIST_HINT = "Выберите проект или создайте новый"
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
CATEGORIES_LIST_HINT = "Каждая категория = тема для статей"
CATEGORY_CREATE_TITLE = "НОВАЯ КАТЕГОРИЯ"

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
KEYWORDS_CLUSTERS_HINT = "Нажмите на группу чтобы увидеть фразы"
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
DESCRIPTION_REVIEW_HINT = "Прочитайте и отредактируйте если нужно \u2014 AI не всегда попадает в точку"
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
CONNECTIONS_MANAGE_HINT = "Удалите если подключение больше не нужно"
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
VK_PERSONAL_ALREADY = "К проекту уже подключена VK-личная страница."
VK_PERSONAL_CONNECTED = "VK личная страница подключена!"
VK_BOTH_CONNECTED = "К проекту уже подключены и VK-группа, и личная страница."
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

# -----------------------------------------------
# Social Pipeline (POST_* prefix)
# -----------------------------------------------
POST_PROJECT_TITLE = "ПОСТ (1/{total}) \u2014 ПРОЕКТ"
POST_PROJECT_QUESTION = "Для какого проекта?"
POST_PROJECT_CREATE_HINT = "Для начала создадим проект \u2014 это 30 секунд."
POST_PROJECT_CREATE_TITLE = "ПОСТ (1/{total}) \u2014 СОЗДАНИЕ ПРОЕКТА"
POST_PROJECT_CREATE_QUESTION = "Как назов\u0451м проект?"
POST_PROJECT_CREATE_EXAMPLE = "Пример: Мебель Комфорт"
POST_PROJECT_CREATED = "Проект \u00ab{name}\u00bb создан!"
POST_PROJECT_LIMIT = "Достигнут лимит проектов."
POST_CONNECTION_TITLE = "ПОСТ (2/{total}) \u2014 ПОДКЛЮЧЕНИЕ"
POST_CONNECTION_QUESTION = "Куда публикуем?"
POST_CONNECTION_EMPTY = "Подключите соцсеть для публикации."
POST_CONNECTION_PLATFORM_PICK = "Выберите платформу:"
POST_CONNECTION_ALL_CONNECTED = "Все платформы уже подключены."
POST_CONNECTION_TG_TITLE = "ПОСТ (2/{total}) \u2014 ПОДКЛЮЧЕНИЕ ТЕЛЕГРАМ"
POST_CONNECTION_TG_PROMPT = (
    "Введите ID или ссылку на канал.\n"
    "<i>Примеры: @mychannel, t.me/mychannel, -1001234567890</i>"
)
POST_CONNECTION_TG_FORMAT_ERROR = "Неверный формат. Используйте @channel, t.me/channel или -100XXXX."
POST_CONNECTION_TG_DUPLICATE = "У этого проекта уже есть Телеграм-канал. Удалите текущий, чтобы подключить другой."
POST_CONNECTION_TG_GLOBAL_DUP = "Канал {channel} уже подключ\u0451н другим пользователем."
POST_CONNECTION_TG_TOKEN_PROMPT = (
    "Теперь создайте бота через @BotFather и пришлите токен.\n"  # noqa: S105
    "<i>Формат: 123456789:AAABBB...</i>"
)
POST_CONNECTION_TG_TOKEN_FORMAT = (
    "Неверный формат токена. Токен содержит \u00ab:\u00bb и длиннее 30 символов.\n"  # noqa: S105
    "Пришлите корректный токен."
)
POST_CONNECTION_TG_TOKEN_OK = "Токен принят."  # noqa: S105
POST_CONNECTION_TG_VERIFY_HINT = (
    "Добавьте бота админом в канал {channel} "
    "с правом \u00abПубликация сообщений\u00bb и нажмите \u00abПроверить\u00bb."
)
POST_CONNECTION_TG_NOT_ADMIN = (
    "Бот не является администратором канала "
    "или не имеет права \u00abПубликация сообщений\u00bb.\n"
    "Добавьте бота и нажмите \u00abПроверить снова\u00bb."
)
POST_CONNECTION_TG_ADMIN_ERROR = "Не удалось получить список админов канала.\nПроверьте, что бот добавлен в канал."
POST_CONNECTION_TG_BOT_ERROR = "Не удалось подключиться к боту. Проверьте токен."
POST_CONNECTION_TG_CONNECTED = "Телеграм-канал {channel} подключ\u0451н!"
POST_CONNECTION_VK_TITLE = "ПОСТ (2/{total}) \u2014 ПОДКЛЮЧЕНИЕ ВКОНТАКТЕ"
POST_CONNECTION_VK_PROMPT = (
    "Отправьте ссылку на группу VK:\n\n"
    "Примеры:\n"
    "\u2022 https://vk.com/club123456\n"
    "\u2022 https://vk.com/mygroup\n"
    "\u2022 123456 (ID группы)"
)
POST_CONNECTION_VK_PARSE_ERROR = (
    "Не удалось распознать группу.\n\n"
    "Примеры: https://vk.com/club123456, https://vk.com/mygroup, 123456"
)
POST_CONNECTION_VK_FOUND = "Группа найдена: <b>{name}</b>"
POST_CONNECTION_VK_OAUTH_HINT = (
    "Нажмите кнопку ниже, чтобы предоставить доступ на публикацию.\n"
    "Ссылка действительна 30 минут."
)
POST_CONNECTION_PINTEREST_TITLE = "ПОСТ (2/{total}) \u2014 ПОДКЛЮЧЕНИЕ PINTEREST"
POST_CONNECTION_PINTEREST_HINT = "Нажмите кнопку ниже для авторизации.\nСсылка действительна {minutes} минут."
POST_CATEGORY_TITLE = "ПОСТ (3/{total}) \u2014 ТЕМА"
POST_CATEGORY_QUESTION = "Какая тема?"
POST_CATEGORY_CREATE_PROMPT = "О ч\u0451м будет пост? Назовите тему."
POST_CATEGORY_NAME_ERROR = "Введите название темы (от 2 до 100 символов)."
POST_CATEGORY_CREATED = "Тема \u00ab{name}\u00bb создана."
POST_CATEGORY_CREATE_ERROR = "Не удалось создать категорию. Попробуйте снова."
POST_READINESS_TITLE = "ПОСТ (4/{total}) \u2014 ПОДГОТОВКА"
POST_CONFIRM_TITLE = "ПОСТ (5/{total}) \u2014 ПОДТВЕРЖДЕНИЕ"
POST_READY_TITLE = "ПОСТ ГОТОВ"
POST_PUBLISHED_TITLE = "ПОСТ ОПУБЛИКОВАН"
POST_ERROR_TITLE = "НЕ УДАЛОСЬ СГЕНЕРИРОВАТЬ"
POST_ERROR_HINT = "Попробуйте через 5 минут \u2014 обычно помогает"
POST_ERROR_REFUND = "Ошибка генерации поста. Токены возвращены."
POST_CANCELLED = "Пост отмен\u0451н. Токены возвращены."
POST_PIPELINE_CANCELLED = "Публикация отменена."
POST_GENERATION_TITLE = "ГЕНЕРАЦИЯ ПОСТА"
POST_PUBLISH_TITLE = "ПУБЛИКАЦИЯ ПОСТА"
POST_PUBLISH_ERROR = "Ошибка публикации. Попробуйте снова."
POST_PUBLISH_NOT_FOUND = "Подключение не найдено. Проверьте настройки."
POST_PUBLISH_ACCESS_DENIED = "Доступ запрещ\u0451н."
POST_PINTEREST_NO_IMAGE = (
    "Для Pinterest требуется изображение, но оно не было сгенерировано.\n"
    "Попробуйте перегенерировать пост."
)
POST_CROSSPOST_TITLE = "КРОСС-ПОСТ: {keyword}"
POST_CROSSPOST_QUESTION = "На какие платформы адаптировать?"
POST_CROSSPOST_NO_TARGETS = "Нет других подключений для кросс-поста."
POST_CROSSPOST_RUNNING = "Адаптирую посты..."
POST_CROSSPOST_CANCELLED = "Кросс-постинг отмен\u0451н."
POST_CROSSPOST_MIN_ONE = "Выберите хотя бы одну платформу."

# Article pipeline step strings (Screen builder)
ARTICLE_STEP1_TITLE = "СТАТЬЯ (1/5) \u2014 ПРОЕКТ"
ARTICLE_STEP1_PROMPT = "Выберите проект для публикации"
ARTICLE_STEP1_NO_PROJECTS = "Для начала создадим проект \u2014 это 30 секунд"
ARTICLE_STEP2_TITLE = "СТАТЬЯ (2/5) \u2014 САЙТ"
ARTICLE_STEP2_PROMPT = "На какой сайт опубликуем?"
ARTICLE_STEP2_NO_WP = "Для публикации нужен WordPress-сайт. Подключим?"
ARTICLE_STEP3_TITLE = "СТАТЬЯ (3/5) \u2014 ТЕМА"
ARTICLE_STEP3_PROMPT = "О ч\u0451м будет статья?"
ARTICLE_STEP3_WHICH = "Какая тема?"
ARTICLE_CREATE_PROJECT_TITLE = "СТАТЬЯ (1/5) \u2014 НОВЫЙ ПРОЕКТ"

PIPELINE_READINESS_TITLE = "СТАТЬЯ (4/5) \u2014 ПОДГОТОВКА"
PIPELINE_CONFIRM_TITLE = "СТАТЬЯ (5/5) \u2014 ПОДТВЕРЖДЕНИЕ"
PIPELINE_COST_GOD = "Стоимость: ~{cost} ток. (GOD_MODE \u2014 бесплатно)"
PIPELINE_COST_NORMAL = "Стоимость: ~{cost} ток."
PIPELINE_SESSION_EXPIRED = "Данные сессии устарели."
PIPELINE_CATEGORY_NOT_SET = "Категория не выбрана. Начните заново."
PIPELINE_NO_KEYWORDS = "Нет доступных ключевых фраз. Добавьте их в категорию."
PIPELINE_INSUFFICIENT_BALANCE = "Недостаточно токенов."

PIPELINE_PROGRESS_TITLE = "ГЕНЕРАЦИЯ СТАТЬИ"
PIPELINE_PUBLISH_TITLE = "ПУБЛИКАЦИЯ"
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

PIPELINE_TOPIC_TITLE = "СТАТЬЯ (3/5) \u2014 ТЕМА"
PIPELINE_TOPIC_QUESTION = "О чём будет статья? Назовите тему."
PIPELINE_TOPIC_WHICH = "Какая тема?"

# -----------------------------------------------
# Scheduler
# -----------------------------------------------
SCHEDULER_TITLE = "ПЛАНИРОВЩИК"
SCHEDULER_TYPE_PROMPT = "Выберите тип контента:"
SCHEDULER_ARTICLES_TITLE = "ПЛАНИРОВЩИК \u2014 СТАТЬИ"
SCHEDULER_SOCIAL_TITLE = "ПЛАНИРОВЩИК \u2014 СОЦСЕТИ"
SCHEDULER_SELECT_CATEGORY = "Выберите категорию:"
SCHEDULER_SELECT_CONNECTION = "Выберите подключение для настройки расписания:"
SCHEDULE_TITLE = "РАСПИСАНИЕ"
SCHEDULE_SOCIAL_TITLE = "РАСПИСАНИЕ (СОЦСЕТИ)"
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
SCHEDULE_DAYS_HINT = "Рекомендуем 3 дня в неделю для стабильного SEO-эффекта"
SCHEDULE_TIMES_HINT = "Лучшее время \u2014 утро (8-10) или обед (12-14)"
SCHEDULE_COUNT_HINT = "1 пост в день \u2014 оптимально для большинства сайтов"
SCHEDULE_ARTICLES_CONN_TITLE = "СТАТЬИ \u2014 ПОДКЛЮЧЕНИЯ"
SCHEDULE_SOCIAL_CONN_TITLE = "СОЦСЕТИ \u2014 ПОДКЛЮЧЕНИЯ"
SCHEDULE_COST_ESTIMATE = "Ориент. расход: ~{cost} токенов/нед"
SCHEDULE_NO_CATEGORIES = "Сначала создайте категорию в карточке проекта"
SCHEDULE_NO_WP = "Нет WordPress-подключений. Добавьте платформу."
SCHEDULE_NO_SOCIAL = "Нет подключённых соцсетей"

CROSSPOST_TITLE = "КРОСС-ПОСТИНГ"
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
PAYMENT_SUCCESS_TITLE = "ОПЛАТА ПРОШЛА"
PAYMENT_SUCCESS_TEXT = "Начислено: <b>{tokens}</b> токенов\nБаланс: <b>{balance}</b> токенов"
PAYMENT_ERROR = "Ошибка обработки платежа. Попробуйте позже."
PAYMENT_REFUND_TITLE = "ВОЗВРАТ ОБРАБОТАН"
PAYMENT_REFUND_TEXT = (
    "Списано: <b>{tokens}</b> токенов\n"
    "Ваш баланс отрицателен ({balance} токенов) из-за возврата средств.\n"
    "Пополните баланс для продолжения работы."
)

# -----------------------------------------------
# Exit Protection
# -----------------------------------------------
EXIT_CONFIRM_TITLE = "ПРЕРВАТЬ ПУБЛИКАЦИЮ?"
EXIT_CONFIRM_TEXT = "Прогресс сохранится на 24 часа."
EXIT_CONFIRMED = "Публикация приостановлена. Продолжить можно из /start."

# -----------------------------------------------
# Connection Success
# -----------------------------------------------
CONN_CONNECTED_TITLE = "ПОДКЛЮЧЕНО"
CONN_WP_SUCCESS = "WordPress ({identifier}) успешно подключ\u0451н к проекту."
CONN_WP_HINT = "Теперь можно публиковать статьи на сайт"
CONN_TG_SUCCESS = "Telegram-канал {channel} подключ\u0451н!"
CONN_TG_HINT = "Теперь можно публиковать посты в канал"
CONN_VK_NOT_ADMIN = (
    "Бот @{username} не является администратором канала {channel}.\n"
    "Добавьте бота в канал и назначьте администратором."
)
CONN_TG_VERIFY_ERROR = (
    "Не удалось проверить канал {channel}.\n"
    "Убедитесь, что канал существует и бот добавлен как администратор."
)
CONN_TG_INVALID_TOKEN = "Недействительный токен. Проверьте и попробуйте ещё раз."  # noqa: S105  # UI text
CONN_TG_GLOBAL_DUP = (
    "Канал {channel} уже подключ\u0451н другим пользователем.\n"
    "Один канал может быть привязан только к одному проекту."
)
CONN_TG_ALREADY_SHORT = (
    "К проекту уже подключ\u0451н Telegram-канал.\n"
    "Для другого канала создайте новый проект."
)
CONN_WP_ALREADY_SHORT = (
    "К проекту уже подключ\u0451н WordPress-сайт.\n"
    "Для другого сайта создайте новый проект."
)
CONN_DELETE_SUCCESS = "Подключение {platform} ({identifier}) удалено."
CONN_DELETE_ERROR = "Ошибка удаления подключения."

# -----------------------------------------------
# Admin
# -----------------------------------------------
ADMIN_TITLE = "АДМИН-ПАНЕЛЬ"
ADMIN_ACCESS_DENIED = "Доступ запрещён"
MONITORING_TITLE = "МОНИТОРИНГ"
BROADCAST_TITLE = "РАССЫЛКА"
BROADCAST_AUDIENCE_PROMPT = "Выберите аудиторию:"
BROADCAST_TEXT_PROMPT = "Отправьте текст сообщения:"
BROADCAST_PREVIEW_TITLE = "ПРЕДПРОСМОТР РАССЫЛКИ"
BROADCAST_DONE = "Рассылка завершена"
BROADCAST_SENDING = "Рассылка... ({sent}/{total})"
API_COSTS_TITLE = "ЗАТРАТЫ API"
ADMIN_USER_NOT_FOUND = "Пользователь не найден."
ADMIN_USER_LOOKUP_TITLE = "ПОИСК ПОЛЬЗОВАТЕЛЯ"
ADMIN_USER_ACTIVITY_TITLE = "АКТИВНОСТЬ"
BROADCAST_AUDIENCE_TEXT = "Аудитория: {label}\nПолучателей: ~{count}"
BROADCAST_PREVIEW_PROMPT = "Проверьте текст перед отправкой"
BROADCAST_DONE_TEXT = "Отправлено: {sent}\nОшибок: {failed}"
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
# Content Settings
# -----------------------------------------------
CONTENT_SETTINGS_TITLE = "СТИЛЬ СТАТЕЙ"
CONTENT_SETTINGS_DESC = "Настройки по умолчанию для всех площадок.\nДля отдельной площадки \u2014 выберите ниже."
CONTENT_SETTINGS_HINT = "Настройки влияют на генерацию текста и изображений"
CONTENT_DEFAULT_TITLE = "ПО УМОЛЧАНИЮ"
CONTENT_DEFAULT_HINT = "Применяется ко всем площадкам, если не переопределено"
CONTENT_PLATFORM_HINT = "Переопределяет настройки по умолчанию для этой площадки"
CONTENT_TEXT_TITLE = "НАСТРОЙКИ ТЕКСТА"
CONTENT_TEXT_PROMPT = "Выберите параметр для настройки:"
CONTENT_IMAGE_TITLE = "НАСТРОЙКИ ИЗОБРАЖЕНИЙ"
CONTENT_IMAGE_PROMPT = "Выберите параметр для настройки:"
CONTENT_WORD_COUNT_TITLE = "ДЛИНА СТАТЬИ"
CONTENT_WORD_COUNT_PROMPT = "Выберите количество слов:"
CONTENT_WORD_COUNT_HINT = "Рекомендуем 1500\u20132000 слов для SEO"
CONTENT_HTML_TITLE = "HTML-ВЕРСТКА"
CONTENT_HTML_DESC = "Определяет визуальный стиль статьи на сайте."
CONTENT_TEXT_STYLE_TITLE = "СТИЛЬ ТЕКСТА"
CONTENT_TEXT_STYLE_DESC = "Определяет тон и подачу текста."
CONTENT_TEXT_STYLE_MULTI = "Выберите один или несколько:"
CONTENT_IMAGE_STYLE_TITLE = "СТИЛЬ ИЗОБРАЖЕНИЙ"
CONTENT_IMAGE_COUNT_TITLE = "КОЛИЧЕСТВО ИЗОБРАЖЕНИЙ"
CONTENT_IMAGE_COUNT_DESC = "Сколько AI-изображений добавить в статью:"
CONTENT_IMAGE_COUNT_HINT = "Каждое изображение стоит 30 токенов"
CONTENT_PREVIEW_TITLE = "ФОРМАТ ПРЕВЬЮ"
CONTENT_PREVIEW_DESC = "Соотношение сторон главного изображения:"
CONTENT_ARTICLE_FMT_TITLE = "ФОРМАТЫ В СТАТЬЕ"
CONTENT_ARTICLE_FMT_DESC = "Соотношения сторон для внутренних изображений."
CONTENT_CAMERA_TITLE = "КАМЕРА"
CONTENT_CAMERA_DESC = "Имитация стиля съёмки для AI-изображений:"
CONTENT_ANGLE_TITLE = "РАКУРС"
CONTENT_ANGLE_DESC = "Угол съёмки для AI-изображений:"
CONTENT_QUALITY_TITLE = "КАЧЕСТВО"
CONTENT_QUALITY_DESC = "Уровень детализации изображений:"
CONTENT_TONE_TITLE = "ТОНАЛЬНОСТЬ"
CONTENT_TONE_DESC = "Цветовая гамма изображений:"
CONTENT_TEXT_ON_IMAGE_TITLE = "ТЕКСТ НА ИЗОБРАЖЕНИИ"
CONTENT_TEXT_ON_IMAGE_DESC = "Процент текста поверх изображения:"
CONTENT_RESET_DONE = "Настройки сброшены"

# -----------------------------------------------
# Autopublish notification templates (api/publish.py)
# -----------------------------------------------
AUTOPUB_INSUFFICIENT_BALANCE = (
    "Автопубликация пропущена: недостаточно токенов. Расписание приостановлено.\n"
    "Пополните баланс через /start."
)
AUTOPUB_NO_KEYWORDS = (
    "Автопубликация пропущена: нет ключевых фраз в категории.\n"
    "Добавьте фразы через карточку категории."
)
AUTOPUB_CONNECTION_INACTIVE = (
    "Автопубликация не удалась: платформа не отвечает.\n"
    "Проверьте подключение в настройках проекта."
)
AUTOPUB_VALIDATION_FAILED = "Автопубликация пропущена: контент не прошёл проверку качества. Токены возвращены."
AUTOPUB_AI_UNAVAILABLE = "Автопубликация отложена: AI-сервис временно недоступен. Повторим через 1 час."
AUTOPUB_NO_AVAILABLE_KEYWORD = (
    "Автопубликация пропущена: все ключевые фразы уже использованы.\n"
    "Добавьте новые фразы в категорию."
)
AUTOPUB_SUCCESS = "Автопубликация выполнена: <b>{keyword}</b>"

# -----------------------------------------------
# Keyword wizard progress (shared)
# -----------------------------------------------
KW_PROGRESS_TITLE = "ПОДБОР КЛЮЧЕВИКОВ"
KW_STEP_FETCH = "Получение фраз из DataForSEO"
KW_STEP_FETCH_DONE = "Фразы получены"
KW_STEP_CLUSTER = "Группировка по интенту"
KW_STEP_CLUSTER_DONE = "Группировка завершена"
KW_STEP_ENRICH = "Обогащение данными"
KW_STEP_ENRICH_DONE = "Данные обогащены"
KW_RESULT_ADDED = "Добавлено: {clusters} групп, {phrases} фраз"
KW_RESULT_UPLOADED = "Загружено: {clusters} групп, {phrases} фраз"

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

# -----------------------------------------------
# OAuth deep-link strings
# -----------------------------------------------
OAUTH_EXPIRED = "Авторизация не найдена или истекла. Попробуйте ещё раз."
OAUTH_SESSION_MISSING = "Данные сессии не найдены. Попробуйте подключить заново."
OAUTH_DATA_ERROR = "Ошибка данных. Попробуйте ещё раз."
OAUTH_CONN_EXISTS = "Не удалось создать подключение. Возможно, оно уже существует."
VK_NO_GROUPS = "У вас нет групп VK, в которых вы администратор или редактор."
VK_GROUP_PICK = "VK-авторизация успешна!\n\nВыберите группу для подключения:"
VK_GROUP_NO_ID = "Ошибка: не указан ID группы. Попробуйте подключить VK заново."
VK_GROUP_CONNECTED = 'VK-группа \u00ab{group_name}\u00bb подключена!'
VK_GROUP_ACCESS_PROMPT = (
    "Отлично! Теперь нужно дать доступ к группе \u00ab{group_name}\u00bb.\n\n"
    "Нажмите кнопку ниже \u2014 VK попросит подтвердить права на публикацию."
)
PINTEREST_AUTH_FAILED = (
    "Не удалось подключить Pinterest.\nАвторизация была отклонена или произошла ошибка."
)
PINTEREST_CONNECTED = 'Pinterest подключён к проекту \u00ab{project_name}\u00bb!'
CONSENT_ACCEPTED = "Условия приняты!"
DASHBOARD_ACTION_PROMPT = "Выберите действие:"

# -----------------------------------------------
# Pipeline: prices sub-flow (readiness)
# -----------------------------------------------
PIPELINE_PRICES_TEXT_FALLBACK = "Введите прайс-лист текстом или нажмите Отмена."
PIPELINE_PRICES_TOO_LONG = "Текст слишком длинный. Максимум 50 000 символов."
PIPELINE_PRICES_MAX_ROWS = "Максимум {max} строк. Сейчас: {count}."
PIPELINE_PRICES_CAT_MISSING = "Категория не найдена. Начните заново."
PIPELINE_FILE_NOT_FOUND = "Файл не найден."
PIPELINE_FILE_WRONG_FORMAT = "Нужен .xlsx файл."
PIPELINE_FILE_TOO_BIG = "Файл слишком большой (макс. 5 МБ)."
PIPELINE_FILE_DOWNLOAD_ERROR = "Не удалось загрузить файл."
PIPELINE_FILE_EMPTY = "Файл пустой. Добавьте данные."
PIPELINE_FILE_EXTRACT_ERROR = "Не удалось извлечь данные из файла."
PIPELINE_FILE_TOO_MANY_ROWS = "Превышен лимит: максимум {max} строк."
PIPELINE_FILE_READ_ERROR = "Ошибка чтения файла."

# -----------------------------------------------
# Tariffs: callback.answer strings
# -----------------------------------------------
TARIFF_PACKAGE_NOT_FOUND = "Пакет не найден. Попробуйте снова."
TARIFF_YOOKASSA_UNAVAILABLE = "ЮKassa не настроена. Используйте Telegram Stars."
TARIFF_PAYMENT_ERROR = "Ошибка создания платежа. Попробуйте позже."

# -----------------------------------------------
# Content settings: validation
# -----------------------------------------------
CONTENT_INVALID_VALUE = "Недопустимое значение"
CONTENT_UNKNOWN_STYLE = "Неизвестный стиль"

# -----------------------------------------------
# Scheduler: callback.answer strings
# -----------------------------------------------
SCHEDULE_ERROR_CREATE = "Ошибка создания расписания"
SCHEDULE_SELECT_DAY = "Выберите хотя бы один день"
SCHEDULE_CONN_NOT_FOUND = "Категория или подключение не найдены"
SCHEDULE_CANCELLED_FALLBACK = "Настройка расписания отменена."

# -----------------------------------------------
# Admin: broadcast progress
# -----------------------------------------------
BROADCAST_PROGRESS = "Рассылка... ({sent}/{total})\nОтправлено: {ok}, ошибок: {failed}"
BROADCAST_PROGRESS_INIT = "Рассылка... (0/{total})"
BROADCAST_TEXT_EXPECT = "Отправьте текст сообщения (не файл/стикер)."
ADMIN_USER_INPUT_PROMPT = "Отправьте ID (число) или @username."
ADMIN_BALANCE_NO_TARGET = "Ошибка: нет данных о пользователе."
ADMIN_BALANCE_ADJUST_ERROR = "Ошибка при корректировке баланса."
ADMIN_ROLE_CHANGE_ERROR = "Ошибка при смене роли"

# -----------------------------------------------
# Social pipeline resume (hardcoded -> S.*)
# -----------------------------------------------
POST_RESUME_NO_PROJECTS = "Для начала создадим проект \u2014 это 30 секунд."
POST_RESUME_PROJECT_PROMPT = "Для какого проекта?"
POST_RESUME_CATEGORY_PROMPT = "О чём будет пост? Назовите тему."
POST_RESUME_CATEGORY_WHICH = "Какая тема?"

# -----------------------------------------------
# Hints (§2 — consistent hint lines)
# -----------------------------------------------
SCHEDULER_TYPE_HINT = "Статьи публикуются на сайт, посты \u2014 в соцсети"
SCHEDULER_CAT_HINT = "Выберите тему для настройки расписания"
SCHEDULER_CONN_HINT = "Выберите площадку для публикации"
SCHEDULE_SET_HINT = "Расписание можно изменить в любой момент"
CONTENT_TEXT_HINT = "Настройки влияют на генерацию текста"
PAYMENT_REFUND_HINT = "Пополните баланс для продолжения работы"
CROSSPOST_CONFIG_HINT = "Каждый кросс-пост адаптируется под платформу"

# -----------------------------------------------
# Platform display names (canonical map)
# -----------------------------------------------
PLATFORM_DISPLAY: dict[str, str] = {
    "wordpress": "WordPress",
    "telegram": "Telegram",
    "vk": "\u0412\u041a\u043e\u043d\u0442\u0430\u043a\u0442\u0435",
    "pinterest": "Pinterest",
}
