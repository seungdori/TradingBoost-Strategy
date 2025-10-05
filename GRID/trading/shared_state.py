import os

user_keys = {}

from shared.config import settings

REDIS_PASSWORD = settings.REDIS_PASSWORD

cancel_state = False