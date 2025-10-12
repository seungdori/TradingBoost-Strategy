from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ExchangeKeys(BaseModel):
    api_key: str
    api_secret: str
    passphrase: Optional[str] = None  # OKX의 경우 필요
    exchange: str = "okx"  # 기본값 okx
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)

class TradingPreferences(BaseModel):
    leverage: float = 5.0
    risk_per_trade: float = 1.0  # 거래당 위험 비율 (%)
    max_positions: int = 1
    allowed_symbols: list[str] = ["BTC-USDT", "ETH-USDT"]
    auto_trading: bool = False

class UserState(BaseModel):
    is_active: bool = False
    last_trade_time: Optional[datetime] = None
    current_position: Optional[dict] = None
    pnl_today: float = 0.0
    total_trades: int = 0
    entry_trade: int = 0

class User(BaseModel):
    telegram_id: int
    okx_uid: Optional[str] = None
    username: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    is_admin: bool = False
    exchange_keys: Optional[ExchangeKeys] = None
    preferences: TradingPreferences = Field(default_factory=TradingPreferences)
    state: UserState = Field(default_factory=UserState)

    model_config = {
        "json_schema_extra": {
            "example": {
                "telegram_id": 123456789,
                "okx_uid": "646396755365762614",
                "username": "trading_user",
                "exchange_keys": {
                    "api_key": "your-api-key",
                    "api_secret": "your-api-secret",
                    "passphrase": "your-passphrase",
                    "exchange": "okx"
                },
                "preferences": {
                    "leverage": 3,
                    "risk_per_trade": 1.0,
                    "max_positions": 1,
                    "allowed_symbols": ["BTC-USDT", "ETH-USDT"],
                    "auto_trading": False
                }
            }
        }
    }


