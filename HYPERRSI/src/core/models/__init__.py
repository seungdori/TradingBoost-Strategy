"""
HYPERRSI Core Models.

SQLAlchemy ORM models for HYPERRSI trading bot.
"""

# Database models (existing)
from HYPERRSI.src.core.models.database import (
    UserModel,
    ExchangeKeysModel,
    UserPreferencesModel,
    UserStateModel,
    TickSizeModel,
)

# Session management models (new)
from HYPERRSI.src.core.models.session import HyperrsiSession
from HYPERRSI.src.core.models.current_state import HyperrsiCurrent
from HYPERRSI.src.core.models.state_change import (
    HyperrsiStateChange,
    ChangeType,
    TriggeredBy,
)

# Trade record models (new)
from HYPERRSI.src.core.models.trade import (
    HyperrsiTrade,
    HyperrsiDailyStats,
    CloseType,
)

__all__ = [
    # Existing models
    "UserModel",
    "ExchangeKeysModel",
    "UserPreferencesModel",
    "UserStateModel",
    "TickSizeModel",
    # Session management models
    "HyperrsiSession",
    "HyperrsiCurrent",
    "HyperrsiStateChange",
    "ChangeType",
    "TriggeredBy",
    # Trade record models
    "HyperrsiTrade",
    "HyperrsiDailyStats",
    "CloseType",
]
