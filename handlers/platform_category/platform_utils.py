"""
Вспомогательные функции и редиректы для платформ
"""
from loader import bot

# Импортируем основной обработчик из main_menu
from .main_menu import handle_platform_menu


# Обработчик для кнопки "К платформе" из website модуля
@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_menu_manage_"))
def handle_platform_menu_redirect(call):
    """Редирект с platform_menu_manage_ на platform_menu_"""
    # Убираем _manage из callback_data и вызываем основной обработчик
    call.data = call.data.replace("platform_menu_manage_", "platform_menu_")
    handle_platform_menu(call)


print("✅ platform_category/platform_utils.py загружен")
