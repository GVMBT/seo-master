# -*- coding: utf-8 -*-
"""
VK Integration Package
"""
from .vk_config import VK_APP_ID, VK_REDIRECT_URI, get_vk_auth_url
from .vk_oauth import VKOAuth
from .vk_telegram_handler import *

__all__ = ['VK_APP_ID', 'VK_REDIRECT_URI', 'get_vk_auth_url', 'VKOAuth']

