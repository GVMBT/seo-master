"""Inline keyboard builders for projects, categories, settings, tariffs."""

from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import Category, Project, User
from keyboards.pagination import PAGE_SIZE, paginate
from services.payments.packages import PACKAGES, SUBSCRIPTIONS

# ---------------------------------------------------------------------------
# Project fields (15 editable) — order matches USER_FLOWS_AND_UI_MAP.md §2
# ---------------------------------------------------------------------------

PROJECT_FIELDS: list[tuple[str, str]] = [
    ("name", "Название"),
    ("company_name", "Компания"),
    ("specialization", "Специализация"),
    ("website_url", "Сайт"),
    ("company_city", "Город"),
    ("company_address", "Адрес"),
    ("company_phone", "Телефон"),
    ("company_email", "Email"),
    ("company_instagram", "Instagram"),
    ("company_vk", "VK"),
    ("company_pinterest", "Pinterest"),
    ("company_telegram", "Telegram"),
    ("experience", "Опыт работы"),
    ("advantages", "Преимущества"),
    ("description", "Описание"),
]


# ---------------------------------------------------------------------------
# Project keyboards
# ---------------------------------------------------------------------------


def project_list_kb(projects: list[Project], page: int = 0) -> InlineKeyboardBuilder:
    """Paginated project list + [Создать] + [Статистика] + [Главное меню].

    When empty, shows [Создать проект] + [Помощь] (USER_FLOWS_AND_UI_MAP.md level 1).
    """
    if not projects:
        builder = InlineKeyboardBuilder()
        builder.button(text="Создать проект", callback_data="projects:new")
        builder.button(text="Помощь", callback_data="help:main")
        builder.adjust(1)
        return builder

    builder, _, nav_count = paginate(
        items=projects,
        page=page,
        item_text_fn=lambda p: p.name,
        item_callback_fn=lambda p: f"project:{p.id}:card",
        page_callback_fn=lambda pg: f"page:projects:{pg}",
    )
    builder.button(text="Создать проект", callback_data="projects:new")
    builder.button(text="Статистика", callback_data="stats:all")
    builder.button(text="Главное меню", callback_data="menu:main")
    # Rebuild sizes: paginate items + nav row + extra buttons 1-wide
    page_size = PAGE_SIZE
    page_count = len(projects[page * page_size : (page + 1) * page_size])
    sizes = [1] * page_count
    if nav_count:
        sizes.append(nav_count)
    sizes += [1, 1, 1]  # create + stats + menu
    builder.adjust(*sizes)
    return builder


def project_card_kb(project: Project) -> InlineKeyboardBuilder:
    """Project card action buttons (USER_FLOWS_AND_UI_MAP.md level 2, lines 507-516)."""
    builder = InlineKeyboardBuilder()
    tz = project.timezone or "Europe/Moscow"
    # Exact order per spec:
    builder.button(text="Редактировать данные", callback_data=f"project:{project.id}:edit")
    builder.button(text="Управление категориями", callback_data=f"project:{project.id}:categories")
    builder.button(text="Создать категорию", callback_data=f"project:{project.id}:cat:new")
    builder.button(text="Подключения платформ", callback_data=f"project:{project.id}:connections")
    builder.button(text="Планировщик публикаций", callback_data=f"project:{project.id}:scheduler")
    builder.button(text="Анализ сайта", callback_data=f"project:{project.id}:audit")
    builder.button(text=f"Часовой пояс: {tz}", callback_data=f"project:{project.id}:timezone")
    # Destructive + navigation
    builder.button(text="Удалить проект", callback_data=f"project:{project.id}:delete")
    builder.button(text="К списку проектов", callback_data="projects:list")
    builder.adjust(1)
    return builder


def project_edit_fields_kb(project: Project) -> InlineKeyboardBuilder:
    """List of 15 editable fields with current values."""
    builder = InlineKeyboardBuilder()
    for field_name, label in PROJECT_FIELDS:
        value = getattr(project, field_name, None)
        display = f"{label}: {value}" if value else f"{label}: не заполнено"
        if len(display) > 60:
            display = display[:57] + "..."
        builder.button(
            text=display,
            callback_data=f"project:{project.id}:field:{field_name}",
        )
    builder.button(text="Назад", callback_data=f"project:{project.id}:card")
    builder.adjust(1)
    return builder


def project_delete_confirm_kb(project_id: int) -> InlineKeyboardBuilder:
    """Delete confirmation: [Да, удалить] + [Отмена]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, удалить", callback_data=f"project:{project_id}:delete:confirm")
    builder.button(text="Отмена", callback_data=f"project:{project_id}:card")
    builder.adjust(2)
    return builder


# ---------------------------------------------------------------------------
# Category keyboards
# ---------------------------------------------------------------------------


def category_list_kb(
    categories: list[Category], project_id: int, page: int = 0
) -> InlineKeyboardBuilder:
    """Paginated category list + [Добавить] + [К проекту]."""
    builder, _, nav_count = paginate(
        items=categories,
        page=page,
        item_text_fn=lambda c: c.name,
        item_callback_fn=lambda c: f"category:{c.id}:card",
        page_callback_fn=lambda pg: f"page:categories:{project_id}:{pg}",
    )
    builder.button(text="Добавить категорию", callback_data=f"project:{project_id}:cat:new")
    builder.button(text="К проекту", callback_data=f"project:{project_id}:card")
    # Rebuild sizes: paginate items + nav row + extra buttons 1-wide
    page_count = len(categories[page * PAGE_SIZE : (page + 1) * PAGE_SIZE])
    sizes = [1] * page_count
    if nav_count:
        sizes.append(nav_count)
    sizes += [1, 1]  # add + back
    builder.adjust(*sizes)
    return builder


def category_card_kb(category: Category) -> InlineKeyboardBuilder:
    """Category card action buttons (stubs for Phase 10 features)."""
    builder = InlineKeyboardBuilder()
    # Phase 10 stubs
    builder.button(text="Ключевые фразы", callback_data=f"category:{category.id}:keywords")
    builder.button(text="Описание", callback_data=f"category:{category.id}:description")
    builder.button(text="Цены", callback_data=f"category:{category.id}:prices")
    builder.button(text="Отзывы", callback_data=f"category:{category.id}:reviews")
    builder.button(text="Медиа", callback_data=f"category:{category.id}:media")
    builder.button(text="Настройки изображений", callback_data=f"category:{category.id}:img_settings")
    builder.button(text="Настройки текста", callback_data=f"category:{category.id}:text_settings")
    # Actions
    builder.button(text="Удалить категорию", callback_data=f"category:{category.id}:delete")
    builder.button(
        text="К списку категорий",
        callback_data=f"project:{category.project_id}:categories",
    )
    builder.adjust(1)
    return builder


def category_delete_confirm_kb(category: Category) -> InlineKeyboardBuilder:
    """Category delete confirmation."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, удалить", callback_data=f"category:{category.id}:delete:confirm")
    builder.button(text="Отмена", callback_data=f"category:{category.id}:card")
    builder.adjust(2)
    return builder


# ---------------------------------------------------------------------------
# Settings keyboards
# ---------------------------------------------------------------------------


def settings_main_kb() -> InlineKeyboardBuilder:
    """Settings menu with sub-sections."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Уведомления", callback_data="settings:notifications")
    builder.button(text="Техподдержка", callback_data="settings:support")
    builder.button(text="О боте", callback_data="settings:about")
    builder.button(text="Главное меню", callback_data="menu:main")
    builder.adjust(1)
    return builder


# ---------------------------------------------------------------------------
# Profile keyboards (USER_FLOWS_AND_UI_MAP.md §Profile)
# ---------------------------------------------------------------------------


def profile_main_kb() -> InlineKeyboardBuilder:
    """Profile action buttons."""
    builder = InlineKeyboardBuilder()
    builder.button(text="История расходов", callback_data="profile:history")
    builder.button(text="Пополнить", callback_data="tariffs:main")
    builder.button(text="Реферальная программа", callback_data="profile:referral")
    builder.button(text="Главное меню", callback_data="menu:main")
    builder.adjust(1)
    return builder


def profile_history_kb() -> InlineKeyboardBuilder:
    """Back button for expense history."""
    builder = InlineKeyboardBuilder()
    builder.button(text="К профилю", callback_data="profile:main")
    builder.adjust(1)
    return builder


def profile_referral_kb(user_id: int, bot_username: str) -> InlineKeyboardBuilder:
    """Referral program with share button."""
    builder = InlineKeyboardBuilder()
    # Share button sends a pre-formatted invite message
    ref_url = f"https://t.me/{bot_username}?start=ref_{user_id}"
    builder.button(text="Поделиться", url=ref_url)
    builder.button(text="К профилю", callback_data="profile:main")
    builder.adjust(1)
    return builder


def settings_notifications_kb(user: User) -> InlineKeyboardBuilder:
    """Notification toggles for 3 types."""
    builder = InlineKeyboardBuilder()

    pub_status = "ВКЛ" if user.notify_publications else "ВЫКЛ"
    bal_status = "ВКЛ" if user.notify_balance else "ВЫКЛ"
    news_status = "ВКЛ" if user.notify_news else "ВЫКЛ"

    builder.button(text=f"Публикации: {pub_status}", callback_data="settings:notify:publications")
    builder.button(text=f"Баланс: {bal_status}", callback_data="settings:notify:balance")
    builder.button(text=f"Новости: {news_status}", callback_data="settings:notify:news")
    builder.button(text="Назад", callback_data="settings:main")
    builder.adjust(1)
    return builder


# ---------------------------------------------------------------------------
# Tariffs keyboards (USER_FLOWS_AND_UI_MAP.md §1: Тарифы)
# ---------------------------------------------------------------------------


def tariffs_main_kb(has_subscription: bool = False) -> InlineKeyboardBuilder:
    """Main tariffs screen: top-up button, subscriptions, manage, navigation."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Пополнить баланс", callback_data="tariffs:topup")
    for name, sub in SUBSCRIPTIONS.items():
        label = f"Подписка {name.capitalize()}: {sub.price_rub} руб/мес"
        builder.button(text=label, callback_data=f"sub:{name}:select")
    if has_subscription:
        builder.button(text="Моя подписка", callback_data="sub:manage")
    builder.button(text="Главное меню", callback_data="menu:main")
    builder.adjust(1)
    return builder


def package_list_kb() -> InlineKeyboardBuilder:
    """Package selection screen: 5 packages + back."""
    builder = InlineKeyboardBuilder()
    for name, pkg in PACKAGES.items():
        bonus = f" + {pkg.bonus} бонус" if pkg.bonus else ""
        label = f"{name.capitalize()}: {pkg.price_rub} руб → {pkg.tokens} токенов{bonus}"
        builder.button(text=label, callback_data=f"tariff:{name}:select")
    builder.button(text="Назад", callback_data="tariffs:main")
    builder.adjust(1)
    return builder


def package_pay_kb(package_name: str, show_savings: bool = False) -> InlineKeyboardBuilder:
    """Payment method choice for a package: Stars / YooKassa."""
    builder = InlineKeyboardBuilder()
    pkg = PACKAGES[package_name]
    builder.button(text=f"Оплатить Stars ⭐ ({pkg.stars} Stars)", callback_data=f"tariff:{package_name}:stars")
    yk_label = "Оплатить картой (ЮKassa)"
    if show_savings:
        # For Business/Enterprise, show approximate savings
        savings = int(pkg.price_rub * 0.35)
        yk_label = f"Оплатить картой (~{savings} руб. экономии)"
    builder.button(text=yk_label, callback_data=f"tariff:{package_name}:yk")
    builder.button(text="Назад", callback_data="tariffs:topup")
    builder.adjust(1)
    return builder


def subscription_pay_kb(sub_name: str) -> InlineKeyboardBuilder:
    """Payment method choice for subscription: Stars / YooKassa."""
    builder = InlineKeyboardBuilder()
    sub = SUBSCRIPTIONS[sub_name]
    builder.button(text=f"Оплатить Stars ⭐ ({sub.stars} Stars)", callback_data=f"sub:{sub_name}:stars")
    builder.button(text="Оплатить картой (ЮKassa)", callback_data=f"sub:{sub_name}:yk")
    builder.button(text="Назад", callback_data="tariffs:main")
    builder.adjust(1)
    return builder


def subscription_manage_kb() -> InlineKeyboardBuilder:
    """Active subscription management: change plan, cancel, back."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Изменить тариф", callback_data="tariffs:main")
    builder.button(text="Отменить подписку", callback_data="sub:cancel")
    builder.button(text="К тарифам", callback_data="tariffs:main")
    builder.adjust(1)
    return builder


def subscription_cancel_confirm_kb() -> InlineKeyboardBuilder:
    """2-step cancel confirmation."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, отменить", callback_data="sub:cancel:confirm")
    builder.button(text="Оставить", callback_data="sub:manage")
    builder.adjust(2)
    return builder
