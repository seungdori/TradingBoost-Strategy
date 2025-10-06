import os
from typing import Any

user_keys: dict[str, Any] = {}

from shared.config import settings

REDIS_PASSWORD = settings.REDIS_PASSWORD

cancel_state = False