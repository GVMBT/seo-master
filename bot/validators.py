"""Shared validators and regex patterns used across routers."""

import re

# URL validation — accepts with or without scheme
URL_RE = re.compile(
    r"^(?:https?://)?[\w][\w.-]*\.[a-z]{2,}(?:[/\w.\-?#=&%]*)?$",
    re.IGNORECASE,
)

# Telegram channel formats: @channel, t.me/channel, -100XXXX
TG_CHANNEL_RE = re.compile(r"^(?:@[\w]{5,}|(?:https?://)?t\.me/[\w]{5,}|-100\d{10,13})$")
