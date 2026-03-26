"""Centralized custom emoji catalog — sticker pack PVNDORA 2.

Icons from screen/icons/ (hex-shaped cyan/teal on dark background).

Usage:
    from bot.texts.emoji import E
    text = f"{E.WALLET} <b>Balance: 1500</b>"

Renders as premium custom emoji via <tg-emoji> HTML tags.
Works in edit_text / send_message / photo captions with parse_mode="HTML".
"""

from typing import ClassVar


def _e(eid: str, fb: str) -> str:
    """Return <tg-emoji> HTML tag with custom emoji from PVNDORA 2 sticker pack."""
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'


# Toggle prefix for schedule day/time buttons.
# Used in both keyboard builders and scheduler.py parser.
TOGGLE_ON = "\u2713 "
TOGGLE_OFF = ""


class E:
    """Custom emoji constants from PVNDORA 2 sticker pack.

    Each constant returns '<tg-emoji emoji-id="ID">fallback</tg-emoji>'.
    IDs extracted from screen/icons/ filenames.
    """

    # Status
    CHECK = _e("5307785824950064221", "\u2705")
    CLOSE = _e("5305803070477736537", "\u274c")
    WARNING = _e("5307912109873470997", "\u26a0\ufe0f")
    INFO = _e("5308040099898890918", "\u2139\ufe0f")

    # Finance
    WALLET = _e("5305791598620088158", "\U0001f4b0")
    PRICE = _e("5305729132615735033", "\U0001f3f7")
    CART_ADD = _e("5305273054333539601", "\U0001f6d2")
    DISCOUNT = _e("5305685195100297603", "\U0001f4b8")
    CREDIT_CARD = _e("5305548086859307554", "\U0001f4b3")
    DOLLAR = _e("5307994719274437815", "\U0001f4b2")
    CROWN = _e("5305801511404608340", "\U0001f451")

    # Content
    PEN = _e("5305682317472208455", "\u270f\ufe0f")
    DOC = _e("5305634269673066495", "\U0001f4c4")
    EDIT_DOC = _e("5305731383178600199", "\U0001f4dd")
    IMAGE = _e("5305545582893373314", "\U0001f5bc\ufe0f")
    HASHTAG = _e("5305725232785429716", "#\ufe0f\u20e3")
    MEGAPHONE = _e("5305734415425508393", "\U0001f4e3")

    # Navigation
    FOLDER = _e("5305514796567795035", "\U0001f4c1")
    CHART = _e("5305266994134685124", "\U0001f4c8")
    CHART_UP = _e("5305266994134685124", "\U0001f4c8")
    ANALYTICS = _e("5305290642224617388", "\U0001f4ca")
    SCHEDULE = _e("5305462853233318552", "\U0001f4c5")
    GEAR = _e("5305392175251496829", "\u2699\ufe0f")
    SLIDERS = _e("5305307637410206511", "\U0001f39b\ufe0f")
    ROCKET = _e("5305703826668428473", "\U0001f680")
    BELL = _e("5305509505168086814", "\U0001f514")

    # Users
    USER = _e("5305247692551657115", "\U0001f464")
    USER_ID = _e("5305249358998970079", "\U0001f194")
    TRANSFER = _e("5305514796567795035", "\U0001f500")
    SUPPORT = _e("5305724683029617153", "\U0001f4ac")

    # Platforms
    WORDPRESS = _e("5305702774401439462", "\U0001f310")
    TELEGRAM = _e("5305643301989290953", "\u2708\ufe0f")
    VK = _e("5305396259765394964", "\U0001f535")
    PINTEREST = _e("5305654597753279465", "\U0001f4cc")
    INSTAGRAM = _e("5305780118172503416", "\U0001f4f7")
    YOUTUBE = _e("5305504784999028033", "\u25b6\ufe0f")
    TIKTOK = _e("5305386733527931209", "\U0001f3b5")
    FACEBOOK = _e("5305315673294016776", "\U0001f535")
    TWITTER = _e("5305724236353017800", "\U0001f426")
    TELEGRAPH = _e("5307794002567797158", "\U0001f4f0")

    # Security
    LOCK = _e("5305748374069221919", "\U0001f512")
    KEY = _e("5305635128666526830", "\U0001f511")
    BOOK_LOCK = _e("5305241847101168153", "\U0001f4d5")
    EYE = _e("5305627152912268717", "\U0001f441\ufe0f")

    # Infrastructure
    DATABASE = _e("5305554731173713720", "\U0001f5c4")
    DATABASE_CONNECT = _e("5305560855797077870", "\U0001f517")
    PULSE = _e("5307799074924173933", "\U0001f4a0")
    CLOUD_UPLOAD = _e("5305322304723523078", "\u2601\ufe0f")
    UPLOAD = _e("5305761263266078951", "\U0001f4e4")

    # AI
    AI_BRAIN = _e("5305649795979842306", "\U0001f9e0")
    AI_TREE = _e("5305457205351323979", "\U0001f333")
    LIGHTNING = _e("5305745874398254843", "\u26a1")
    LIGHTBULB = _e("5305729815515533141", "\U0001f4a1")

    # Numbers
    N1 = _e("5305338243347157769", "1\ufe0f\u20e3")
    N2 = _e("5307730153583972349", "2\ufe0f\u20e3")
    N3 = _e("5305563909518825468", "3\ufe0f\u20e3")
    N4 = _e("5305799131992730110", "4\ufe0f\u20e3")
    N5 = _e("5307500080775863670", "5\ufe0f\u20e3")

    # Number list (up to 5)
    _NUMBERS: ClassVar[list[str]] = [N1, N2, N3, N4, N5]

    @classmethod
    def num(cls, i: int) -> str:
        """Return custom emoji number for 1-5, plain digit for >5."""
        if 1 <= i <= 5:
            return cls._NUMBERS[i - 1]
        return f"{i}."

    # Misc
    LINK = _e("5305560855797077870", "\U0001f517")
    LEAF = _e("5314551832960340192", "\U0001f33f")
    SYNC = _e("5307669985387122104", "\U0001f504")
    SEARCH_CHECK = _e("5308019247832666616", "\U0001f50d")
