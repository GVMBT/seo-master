"""Centralized custom emoji catalog for Telegram Premium emoji.

Icons from screen/icons/ (hex-shaped cyan/teal on dark background).
Usage: from bot.texts.emoji import E
       text = f"{E.WALLET} <b>Баланс: 1500</b>"

Renders as premium emoji for Premium users, Unicode fallback for others.
"""


def _e(eid: str, fb: str) -> str:
    """Return emoji fallback.

    <tg-emoji> tags cause ENTITY_TEXT_INVALID when used in edit_media captions.
    Using plain Unicode until custom emoji sticker pack is configured for the bot.
    IDs are preserved for future activation.
    """
    _ = eid
    return fb


class E:
    """Custom emoji constants."""

    # Status
    CHECK = _e("5307785824950064221", "\u2705")
    CLOSE = _e("5305803070477736537", "\u274c")
    WARNING = _e("5307912109873470997", "\u26a0")
    INFO = _e("5308040099898890918", "\u2139")

    # Finance
    WALLET = _e("5305791598620088158", "\U0001f4b0")
    PRICE = _e("5305729132615735033", "\U0001f3f7")

    # Content
    PEN = _e("5305682317472208455", "\u270f")
    DOC = _e("5305634269673066495", "\U0001f4c4")
    IMAGE = _e("5305545582893373314", "\U0001f5bc")
    HASHTAG = _e("5305725232785429716", "#")

    # Navigation
    FOLDER = _e("5305514796567795035", "\U0001f4c1")
    CHART = _e("5305266994134685124", "\U0001f4c8")
    ANALYTICS = _e("5305290642224617388", "\U0001f4ca")
    SCHEDULE = _e("5305462853233318552", "\U0001f4c5")
    GEAR = _e("5305392175251496829", "\u2699")
    SLIDERS = _e("5305307637410206511", "\U0001f39b")
    ROCKET = _e("5305703826668428473", "\U0001f680")
    BELL = _e("5305509505168086814", "\U0001f514")

    # Users
    USER = _e("5305247692551657115", "\U0001f464")
    TRANSFER = _e("5305514796567795035", "\U0001f500")

    # Platforms
    WORDPRESS = _e("5305702774401439462", "\U0001f310")
    TELEGRAM = _e("5305643301989290953", "\u2708")
    VK = _e("5305396259765394964", "\U0001f535")
    PINTEREST = _e("5305654597753279465", "\U0001f4cc")

    # Security
    LOCK = _e("5305748374069221919", "\U0001f512")
    KEY = _e("5305635128666526830", "\U0001f511")

    # Numbers
    N1 = _e("5305338243347157769", "1")
    N2 = _e("5307730153583972349", "2")
    N3 = _e("5305563909518825468", "3")
    N4 = _e("5305799131992730110", "4")
    N5 = _e("5307500080775863670", "5")

    # Misc
    LINK = _e("5305560855797077870", "\U0001f517")
    LIGHTBULB = _e("5305729815515533141", "\U0001f4a1")
    UPLOAD = _e("5305761263266078951", "\U0001f4e4")
