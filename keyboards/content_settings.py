"""Content settings keyboards: platform tabs, text/image option grids."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.texts.emoji import TOGGLE_ON

__all__ = [
    "project_angle_kb",
    "project_article_format_kb",
    "project_camera_kb",
    "project_content_settings_kb",
    "project_html_style_kb",
    "project_image_count_kb",
    "project_image_menu_kb",
    "project_image_style_kb",
    "project_platform_card_kb",
    "project_preview_format_kb",
    "project_quality_kb",
    "project_text_menu_kb",
    "project_text_on_image_kb",
    "project_text_style_kb",
    "project_tone_kb",
    "project_word_count_kb",
]

# Human-readable platform names
_PLATFORM_NAMES: dict[str, str] = {
    "wordpress": "WordPress",
    "telegram": "Telegram",
    "vk": "VK",
    "pinterest": "Pinterest",
}


def project_content_settings_kb(
    pid: int,
    connected_platforms: list[str] | None = None,
) -> InlineKeyboardMarkup:
    """Main content settings screen: [Text][Images] + platform tabs."""
    p = f"psettings:{pid}:d"
    btn = InlineKeyboardButton
    rows: list[list[InlineKeyboardButton]] = [
        [
            btn(text="Текст", callback_data=f"{p}:text"),
            btn(text="Изображения", callback_data=f"{p}:images"),
        ],
    ]
    # Platform override tabs in pairs
    platforms = connected_platforms or []
    if platforms:
        pair: list[InlineKeyboardButton] = []
        for pt in platforms:
            name = _PLATFORM_NAMES.get(pt, pt.capitalize())
            pair.append(btn(text=name, callback_data=f"psettings:{pid}:{pt}:card"))
            if len(pair) == 2:
                rows.append(pair)
                pair = []
        if pair:
            rows.append(pair)
    rows.append([btn(text="К проекту", callback_data=f"project:{pid}:card")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_platform_card_kb(pid: int, target: str) -> InlineKeyboardMarkup:
    """Platform card: [Text] [Images] / [Reset] [Back]."""
    p = f"psettings:{pid}:{target}"
    back_cb = f"psettings:{pid}:back"
    text_btn = InlineKeyboardButton(
        text="Текст", callback_data=f"{p}:text",
    )
    img_btn = InlineKeyboardButton(
        text="Изображения",
        callback_data=f"{p}:images",
    )
    rows: list[list[InlineKeyboardButton]] = [[text_btn, img_btn]]
    reset_btn = InlineKeyboardButton(
        text="Сбросить",
        callback_data=f"{p}:reset",
    )
    back_btn = InlineKeyboardButton(
        text="Назад",
        callback_data=back_cb,
    )
    rows.append([reset_btn, back_btn])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _multi_select_grid(
    items: list[str],
    selected: set[str],
    cb_prefix: str,
    back_cb: str,
    *,
    cols: int = 2,
) -> InlineKeyboardMarkup:
    """Generic multi-select grid with checkmark prefix."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, item in enumerate(items):
        prefix = TOGGLE_ON if item in selected else ""
        row.append(
            InlineKeyboardButton(
                text=f"{prefix}{item}",
                callback_data=f"{cb_prefix}:{idx}",
            ),
        )
        if len(row) == cols:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Назад", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _single_select_grid(
    items: list[str],
    current: str | None,
    cb_prefix: str,
    back_cb: str,
    *,
    cols: int = 2,
) -> InlineKeyboardMarkup:
    """Generic single-select grid with checkmark prefix."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, item in enumerate(items):
        prefix = TOGGLE_ON if item == current else ""
        row.append(
            InlineKeyboardButton(
                text=f"{prefix}{item}",
                callback_data=f"{cb_prefix}:{idx}",
            ),
        )
        if len(row) == cols:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Назад", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_text_menu_kb(pid: int, target: str = "d") -> InlineKeyboardMarkup:
    """Text settings sub-menu."""
    p = f"psettings:{pid}:{target}"
    back_cb = f"project:{pid}:content_settings" if target == "d" else f"{p}:card"
    btn = InlineKeyboardButton
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(text="Длина", callback_data=f"{p}:words"),
                btn(text="Стиль", callback_data=f"{p}:tstyle"),
            ],
            [btn(text="HTML-верстка", callback_data=f"{p}:html")],
            [btn(text="Назад", callback_data=back_cb)],
        ]
    )


def project_word_count_kb(pid: int, current: int | None, target: str = "d") -> InlineKeyboardMarkup:
    """Word count preset selection."""
    from bot.texts.content_options import WORD_COUNTS

    p = f"psettings:{pid}:{target}"
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for wc in WORD_COUNTS:
        prefix = TOGGLE_ON if wc == current else ""
        row.append(
            InlineKeyboardButton(
                text=f"{prefix}{wc}",
                callback_data=f"{p}:wc:{wc}",
            ),
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Назад", callback_data=f"{p}:text")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_html_style_kb(pid: int, current: str | None, target: str = "d") -> InlineKeyboardMarkup:
    """HTML style single-select grid."""
    from bot.texts.content_options import HTML_STYLES

    p = f"psettings:{pid}:{target}"
    return _single_select_grid(
        HTML_STYLES,
        current,
        f"{p}:hs",
        f"{p}:text",
    )


def project_text_style_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Text style multi-select grid."""
    from bot.texts.content_options import TEXT_STYLES

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        TEXT_STYLES,
        selected,
        f"{p}:ts",
        f"{p}:text",
    )


def project_image_menu_kb(pid: int, target: str = "d") -> InlineKeyboardMarkup:
    """Image settings sub-menu (2x5 grid)."""
    p = f"psettings:{pid}:{target}"
    back_cb = f"project:{pid}:content_settings" if target == "d" else f"{p}:card"
    btn = InlineKeyboardButton
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(text="Стиль", callback_data=f"{p}:istyle"),
             btn(text="Количество", callback_data=f"{p}:icount")],
            [btn(text="Превью", callback_data=f"{p}:pfmt"),
             btn(text="Форматы", callback_data=f"{p}:afmts")],
            [btn(text="Камера", callback_data=f"{p}:camera"),
             btn(text="Ракурс", callback_data=f"{p}:angle")],
            [btn(text="Качество", callback_data=f"{p}:quality"),
             btn(text="Тональность", callback_data=f"{p}:tone")],
            [btn(text="Текст/фото", callback_data=f"{p}:tximg"),
             btn(text="Назад", callback_data=back_cb)],
        ]
    )


def project_preview_format_kb(pid: int, current: str | None, target: str = "d") -> InlineKeyboardMarkup:
    """Preview format single-select (aspect ratios)."""
    from bot.texts.content_options import ASPECT_RATIOS

    p = f"psettings:{pid}:{target}"
    return _single_select_grid(
        ASPECT_RATIOS,
        current,
        f"{p}:pf",
        f"{p}:images",
        cols=5,
    )


def project_article_format_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Article format multi-select (aspect ratios)."""
    from bot.texts.content_options import ASPECT_RATIOS

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        ASPECT_RATIOS,
        selected,
        f"{p}:af",
        f"{p}:images",
        cols=5,
    )


def project_image_style_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Image style multi-select grid."""
    from bot.texts.content_options import IMAGE_STYLES

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        IMAGE_STYLES,
        selected,
        f"{p}:is",
        f"{p}:images",
    )


def project_image_count_kb(pid: int, current: int | None, target: str = "d") -> InlineKeyboardMarkup:
    """Image count selection 0-10."""
    p = f"psettings:{pid}:{target}"
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for n in range(11):
        prefix = TOGGLE_ON if n == current else ""
        row.append(
            InlineKeyboardButton(
                text=f"{prefix}{n}",
                callback_data=f"{p}:ic:{n}",
            ),
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Назад", callback_data=f"{p}:images")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_text_on_image_kb(pid: int, current: int | None, target: str = "d") -> InlineKeyboardMarkup:
    """Text-on-image percentage selection."""
    from bot.texts.content_options import TEXT_ON_IMAGE

    p = f"psettings:{pid}:{target}"
    rows: list[list[InlineKeyboardButton]] = []
    for pct in TEXT_ON_IMAGE:
        prefix = TOGGLE_ON if pct == current else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{prefix}{pct}%",
                callback_data=f"{p}:to:{pct}",
            ),
        ])
    rows.append([InlineKeyboardButton(text="Назад", callback_data=f"{p}:images")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_camera_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Camera multi-select grid."""
    from bot.texts.content_options import CAMERAS

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        CAMERAS,
        selected,
        f"{p}:cm",
        f"{p}:images",
    )


def project_angle_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Angle multi-select grid."""
    from bot.texts.content_options import ANGLES

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        ANGLES,
        selected,
        f"{p}:an",
        f"{p}:images",
    )


def project_quality_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Quality multi-select grid."""
    from bot.texts.content_options import QUALITY

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        QUALITY,
        selected,
        f"{p}:ql",
        f"{p}:images",
        cols=3,
    )


def project_tone_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Tone multi-select grid."""
    from bot.texts.content_options import TONES

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        TONES,
        selected,
        f"{p}:tn",
        f"{p}:images",
        cols=3,
    )
