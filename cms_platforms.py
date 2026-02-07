"""
CMS Platforms Support
====================
Поддержка различных CMS для интеграции
"""

# Поддерживаемые CMS платформы
SUPPORTED_CMS = {
    'wordpress': {
        'name': 'WordPress',
        'icon': '🌐',
        'description': 'Популярная система управления контентом',
        'api_type': 'REST API',
        'requires': ['url', 'username', 'application_password']
    },
    'tilda': {
        'name': 'Tilda',
        'icon': '🎨',
        'description': 'Конструктор сайтов',
        'api_type': 'API',
        'requires': ['public_key', 'secret_key']
    },
    'shopify': {
        'name': 'Shopify',
        'icon': '🛍️',
        'description': 'E-commerce платформа',
        'api_type': 'REST API',
        'requires': ['store_url', 'api_key', 'api_secret']
    }
}


def get_cms_list():
    """
    Возвращает список всех поддерживаемых CMS
    
    Returns:
        dict: Словарь CMS {id: info}
    """
    return SUPPORTED_CMS


def get_cms_info(cms_id):
    """
    Получает информацию о конкретной CMS
    
    Args:
        cms_id: ID CMS (например 'wordpress')
    
    Returns:
        dict: Информация о CMS или None
    """
    return SUPPORTED_CMS.get(cms_id)


def get_cms_instruction(cms_id):
    """
    Возвращает инструкцию по подключению CMS
    
    Args:
        cms_id: ID CMS
    
    Returns:
        str: Текст инструкции
    """
    instructions = {
        'wordpress': """
📝 <b>ИНСТРУКЦИЯ: WordPress</b>

1️⃣ Войдите в админ-панель WordPress
2️⃣ Перейдите в Пользователи → Профиль
3️⃣ Прокрутите до раздела "Application Passwords"
4️⃣ Создайте новый пароль для приложения
5️⃣ Скопируйте сгенерированный пароль

<b>Вам понадобится:</b>
• URL сайта (например: https://mysite.com)
• Имя пользователя WordPress
• Application Password
        """,
        
        'tilda': """
📝 <b>ИНСТРУКЦИЯ: Tilda</b>

1️⃣ Войдите в личный кабинет Tilda
2️⃣ Перейдите в Настройки → API
3️⃣ Включите доступ к API
4️⃣ Скопируйте Public Key и Secret Key

<b>Вам понадобится:</b>
• Public Key
• Secret Key
        """,
        
        'shopify': """
📝 <b>ИНСТРУКЦИЯ: Shopify</b>

1️⃣ Войдите в админ-панель Shopify
2️⃣ Перейдите в Apps → Develop apps
3️⃣ Create an app
4️⃣ Configure Admin API scopes (нужны права на posts)
5️⃣ Install app и скопируйте API credentials

<b>Вам понадобится:</b>
• Store URL (например: mystore.myshopify.com)
• Admin API access token
        """
    }
    
    return instructions.get(cms_id, "Инструкция не найдена")


# Для обратной совместимости
def validate_cms_credentials(cms_id, credentials):
    """
    Проверяет корректность учётных данных CMS
    
    Args:
        cms_id: ID CMS
        credentials: Словарь с учётными данными
    
    Returns:
        tuple: (success: bool, message: str)
    """
    cms_info = get_cms_info(cms_id)
    
    if not cms_info:
        return False, "Неизвестная CMS"
    
    # Проверяем наличие всех необходимых полей
    required = cms_info.get('requires', [])
    missing = [field for field in required if field not in credentials]
    
    if missing:
        return False, f"Отсутствуют поля: {', '.join(missing)}"
    
    return True, "Учётные данные корректны"
