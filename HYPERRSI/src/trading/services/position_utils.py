import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from shared.logging import get_logger
from shared.utils import get_minimum_qty, get_tick_size_from_redis, round_to_qty
