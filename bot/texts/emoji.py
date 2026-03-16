"""Centralized custom emoji catalog for Telegram Premium emoji.

Icons are hex-shaped cyan/teal on dark background, stored in screen/icons/.
Filename format: {Name}_{telegram_custom_emoji_id}.png

Usage in HTML messages (parse_mode="HTML"):
    from bot.texts.emoji import Emoji
    text = f"{Emoji.WALLET} <b>Баланс: 1500 токенов</b>"

Renders as custom emoji for Premium users, fallback emoji for others.
"""


def _e(emoji_id: str | int, fallback: str) -> str:
    """Build tg-emoji HTML tag with fallback."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


class Emoji:
    """Custom emoji constants grouped by semantic category."""

    # --- Actions & Status ---
    CHECKMARK = _e("5307785824950064221", "\u2705")
    CLOSE = _e("5305803070477736537", "\u274c")
    WARNING = _e("5307912109873470997", "\u26a0\ufe0f")
    INFO = _e("5308040099898890918", "\u2139\ufe0f")
    LIGHTNING = _e("5305745874398254843", "\u26a1")
    ROCKET = _e("5305703826668428473", "\U0001f680")
    BELL = _e("5305509505168086814", "\U0001f514")

    # --- Navigation ---
    ARROW_LEFT = _e("5305264309780127055", "\u2b05\ufe0f")
    ARROW_RIGHT = _e("5305258825106887009", "\u27a1\ufe0f")

    # --- Finance & Tokens ---
    WALLET = _e("5305791598620088158", "\U0001f4b0")
    PRICE_TAG = _e("5305729132615735033", "\U0001f3f7\ufe0f")
    CART_ADD = _e("5305273054333539601", "\U0001f6d2")
    CREDIT_CARD = _e("5305548086859307554", "\U0001f4b3")
    DISCOUNT = _e("5305685195100297603", "\U0001f381")
    CROWN = _e("5305801511404608340", "\U0001f451")
    RUB = _e("5305389396407655659", "\U0001f4b1")

    # --- Content & AI ---
    AI_BRAIN = _e("5305649795979842306", "\U0001f9e0")
    DOCUMENT = _e("5305634269673066495", "\U0001f4c4")
    PEN = _e("5305682317472208455", "\u270f\ufe0f")
    EDIT_DOC = _e("5305731383178600199", "\U0001f4dd")
    IMAGE = _e("5305545582893373314", "\U0001f5bc\ufe0f")
    LIGHTBULB = _e("5305729815515533141", "\U0001f4a1")
    HASHTAG = _e("5305725232785429716", "#\ufe0f\u20e3")
    SEARCH_CHECK = _e("5308019247832666616", "\U0001f50d")
    AI_TREE = _e("5305457205351323979", "\U0001f333")

    # --- Publishing & Upload ---
    UPLOAD = _e("5305761263266078951", "\U0001f4e4")
    CLOUD_UPLOAD = _e("5305322304723523078", "\u2601\ufe0f")
    MEGAPHONE = _e("5305734415425508393", "\U0001f4e2")
    SCHEDULE = _e("5305462853233318552", "\U0001f4c5")
    FUNNEL = _e("5305424507765300412", "\U0001f3af")

    # --- Analytics ---
    CHART_UP = _e("5305266994134685124", "\U0001f4c8")
    ANALYTICS = _e("5305290642224617388", "\U0001f4ca")
    HISTORY = _e("5305660924240109869", "\U0001f4dc")
    PULSE = _e("5307799074924173933", "\U0001f49a")

    # --- Settings & Security ---
    GEAR = _e("5305392175251496829", "\u2699\ufe0f")
    SLIDERS = _e("5305307637410206511", "\U0001f39b\ufe0f")
    KEY = _e("5305635128666526830", "\U0001f511")
    LOCK = _e("5305748374069221919", "\U0001f512")
    EYE = _e("5305627152912268717", "\U0001f441\ufe0f")
    EXIT = _e("5305743318892713894", "\U0001f6aa")
    SYNC = _e("5307669985387122104", "\U0001f504")

    # --- Users ---
    USER = _e("5305247692551657115", "\U0001f464")
    USER_ID = _e("5305249358998970079", "\U0001f194")
    SUPPORT = _e("5305724683029617153", "\U0001f6e0\ufe0f")

    # --- Data & Connections ---
    DATABASE = _e("5305554731173713720", "\U0001f5c4\ufe0f")
    DB_CONNECT = _e("5305560855797077870", "\U0001f517")
    TRANSFER = _e("5305514796567795035", "\U0001f500")
    BOOK_LOCK = _e("5305241847101168153", "\U0001f4d5")
    BRACKETS = _e("5307828156147734550", "\U0001f4bb")

    # --- Platforms ---
    TELEGRAM = _e("5305643301989290953", "\u2708\ufe0f")
    VK = _e("5305396259765394964", "\U0001f535")
    INSTAGRAM = _e("5305780118172503416", "\U0001f4f7")
    PINTEREST = _e("5305654597753279465", "\U0001f4cc")
    YOUTUBE = _e("5305504784999028033", "\u25b6\ufe0f")
    TIKTOK = _e("5305386733527931209", "\U0001f3b5")
    FACEBOOK = _e("5305315673294016776", "\U0001f310")
    TWITTER = _e("5305724236353017800", "\U0001f426")
    TELEGRAPH = _e("5307794002567797158", "\U0001f4f0")
    WORDPRESS = _e("5305702774401439462", "\U0001f310")

    # --- Numbered steps ---
    NUM_1 = _e("5305338243347157769", "1\ufe0f\u20e3")
    NUM_2 = _e("5307730153583972349", "2\ufe0f\u20e3")
    NUM_3 = _e("5305563909518825468", "3\ufe0f\u20e3")
    NUM_4 = _e("5305799131992730110", "4\ufe0f\u20e3")
    NUM_5 = _e("5307500080775863670", "5\ufe0f\u20e3")
    NUM_6 = _e("5305660219865475178", "6\ufe0f\u20e3")
    NUM_7 = _e("5305459314180267467", "7\ufe0f\u20e3")
    NUM_8 = _e("5305560258796622929", "8\ufe0f\u20e3")
    NUM_9 = _e("5307869993424165092", "9\ufe0f\u20e3")

    # --- Decorative ---
    LEAF = _e("5314551832960340192", "\U0001f343")
    HEX_OUTLINE = _e("5314640562689709593", "\u2b21")
    HEX_FILLED = _e("5314700142476039173", "\u2b22")
    CUBE = _e("5314511924124227603", "\U0001f4e6")
