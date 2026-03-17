"""Centralized custom emoji catalog for Telegram Premium emoji.

Icons from screen/icons/ (hex-shaped cyan/teal on dark background, sticker pack BobbyLightBlue).

Two access patterns:
    E.WALLET            -> '💰'  (Unicode -- safe everywhere including photo captions)
    E.t.WALLET          -> '<tg-emoji emoji-id="...">💰</tg-emoji>'  (text-only screens)

E.* is safe for ALL contexts (edit_text, edit_media captions, buttons).
E.t.* adds <tg-emoji> tags -- use ONLY in text-only screens (edit_text / send_message),
NEVER in edit_media captions (causes ENTITY_TEXT_INVALID).

icon_custom_emoji_id on buttons: deferred to v3 per UX_PIPELINE.md.
"""


def _e(_eid: str, fb: str) -> str:
    """Return Unicode fallback (safe everywhere).

    IDs preserved for E.t.* access and future sticker pack activation.
    """
    return fb


def _tag(eid: str, fb: str) -> str:
    """Return <tg-emoji> HTML tag for text-only screens (edit_text / send_message).

    Does NOT work in edit_media captions -- use E.* (Unicode) for those.
    """
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'


# Toggle prefix for schedule day/time buttons.
# Used in both keyboard builders and scheduler.py parser.
TOGGLE_ON = "\u2713 "
TOGGLE_OFF = ""


class _EmojiTags:
    """<tg-emoji> tagged versions for text-only screens (edit_text / send_message).

    NEVER use in edit_media captions -- causes ENTITY_TEXT_INVALID.
    """

    # Status
    CHECK = _tag("5307785824950064221", "\u2705")
    CLOSE = _tag("5305803070477736537", "\u274c")
    WARNING = _tag("5307912109873470997", "\u26a0")
    INFO = _tag("5308040099898890918", "\u2139")

    # Finance
    WALLET = _tag("5305791598620088158", "\U0001f4b0")
    PRICE = _tag("5305729132615735033", "\U0001f3f7")

    # Content
    PEN = _tag("5305682317472208455", "\u270f")
    DOC = _tag("5305634269673066495", "\U0001f4c4")
    IMAGE = _tag("5305545582893373314", "\U0001f5bc")
    HASHTAG = _tag("5305725232785429716", "#")

    # Navigation
    FOLDER = _tag("5305514796567795035", "\U0001f4c1")
    CHART = _tag("5305266994134685124", "\U0001f4c8")
    ANALYTICS = _tag("5305290642224617388", "\U0001f4ca")
    SCHEDULE = _tag("5305462853233318552", "\U0001f4c5")
    GEAR = _tag("5305392175251496829", "\u2699")
    SLIDERS = _tag("5305307637410206511", "\U0001f39b")
    ROCKET = _tag("5305703826668428473", "\U0001f680")
    BELL = _tag("5305509505168086814", "\U0001f514")

    # Users
    USER = _tag("5305247692551657115", "\U0001f464")
    TRANSFER = _tag("5305514796567795035", "\U0001f500")  # same icon as FOLDER (Transfer_*.png)

    # Platforms
    WORDPRESS = _tag("5305702774401439462", "\U0001f310")
    TELEGRAM = _tag("5305643301989290953", "\u2708")
    VK = _tag("5305396259765394964", "\U0001f535")
    PINTEREST = _tag("5305654597753279465", "\U0001f4cc")

    # Security
    LOCK = _tag("5305748374069221919", "\U0001f512")
    KEY = _tag("5305635128666526830", "\U0001f511")

    # Communication (IDs from screen/icons/ filenames)
    CROWN = _tag("5305801511404608340", "\U0001f451")
    MEGAPHONE = _tag("5305734415425508393", "\U0001f4e2")
    EDIT_DOC = _tag("5305731383178600199", "\U0001f4dd")
    AI_BRAIN = _tag("5305649795979842306", "\U0001f9e0")
    DATABASE = _tag("5305554731173713720", "\U0001f4be")
    PULSE = _tag("5307799074924173933", "\U0001f4a1")
    SUPPORT = _tag("5305724683029617153", "\U0001f6e0")

    # Extra platforms (IDs from screen/icons/ filenames)
    INSTAGRAM = _tag("5305780118172503416", "\U0001f4f7")
    YOUTUBE = _tag("5305504784999028033", "\U0001f3ac")
    TIKTOK = _tag("5305386733527931209", "\U0001f3b5")
    FACEBOOK = _tag("5305315673294016776", "\U0001f30d")
    TWITTER = _tag("5305724236353017800", "\U0001f426")
    TELEGRAPH = _tag("5307794002567797158", "\U0001f4e8")

    # Misc
    LINK = _tag("5305560855797077870", "\U0001f517")
    LIGHTBULB = _tag("5305729815515533141", "\U0001f4a1")
    UPLOAD = _tag("5305761263266078951", "\U0001f4e4")


class E:
    """Custom emoji constants.

    Two access patterns:
        E.WALLET        -> Unicode fallback (safe everywhere)
        E.t.WALLET      -> '<tg-emoji emoji-id="...">...</tg-emoji>' (text-only screens)
    """

    # Sub-accessor for <tg-emoji> tagged versions
    t = _EmojiTags

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

    # Communication
    CROWN = _e("5305266994134685124", "\U0001f451")
    MEGAPHONE = _e("5305703826668428473", "\U0001f4e2")
    EDIT_DOC = _e("5305634269673066495", "\U0001f4dd")
    AI_BRAIN = _e("5305729815515533141", "\U0001f9e0")
    DATABASE = _e("5305514796567795035", "\U0001f4be")
    PULSE = _e("5305462853233318552", "\U0001f4a1")
    SUPPORT = _e("5305509505168086814", "\U0001f6e0")

    # Extra platforms
    INSTAGRAM = _e("5305654597753279465", "\U0001f4f7")
    YOUTUBE = _e("5305643301989290953", "\U0001f3ac")
    TIKTOK = _e("5305396259765394964", "\U0001f3b5")
    FACEBOOK = _e("5305702774401439462", "\U0001f30d")
    TWITTER = _e("5305643301989290953", "\U0001f426")
    TELEGRAPH = _e("5305560855797077870", "\U0001f4e8")

    # Misc
    LINK = _e("5305560855797077870", "\U0001f517")
    LIGHTBULB = _e("5305729815515533141", "\U0001f4a1")
    UPLOAD = _e("5305761263266078951", "\U0001f4e4")
