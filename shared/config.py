"""
DEPRECATED: This file is kept for backward compatibility only.

The canonical configuration is now in shared/config/settings.py.
When you import 'from shared.config import settings', it uses shared/config/__init__.py
which re-exports from shared/config/settings.py.

Do NOT import directly from this file (shared/config.py).
Use: from shared.config import settings, get_settings, Settings
"""

import warnings
warnings.warn(
    "shared/config.py is deprecated. Use 'from shared.config import settings' which uses shared/config/settings.py",
    DeprecationWarning,
    stacklevel=2
)

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Load .env from project root
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_file = os.path.join(project_root, '.env')
load_dotenv(env_file)


class Settings(BaseSettings):
    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "validate_assignment": True,
        "extra": "allow"
    }

    # API 설정
    OKX_API_KEY: str = ""
    OKX_SECRET_KEY: str = ""
    OKX_PASSPHRASE: str = ""

    # 관리자 API 설정 (초대자 확인용)
    ADMIN_OKX_API_KEY: str = ""
    ADMIN_OKX_SECRET_KEY: str = ""
    ADMIN_OKX_PASSPHRASE: str = ""

    # Security 설정
    ENCRYPTION_KEY: str | None = os.environ.get("ENCRYPTION_KEY", None)

    # Redis 설정
    REDIS_HOST: str = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.environ.get("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str | None = os.environ.get("REDIS_PASSWORD", None)
    REDIS_PURE_URL: str = f"redis://{REDIS_HOST}:{REDIS_PORT}"
    REDIS_DB: int = 0
    REDIS_URL: str = f"redis://{REDIS_HOST}:{REDIS_PORT}"
    REDIS_MAX_CONNECTIONS: int = int(os.environ.get("REDIS_MAX_CONNECTIONS", "200"))
    REDIS_HEALTH_CHECK_INTERVAL: int = 15

    # Redis Migration Feature Flags (for safe phased rollout)
    REDIS_MIGRATION_ENABLED: bool = False
    REDIS_MIGRATION_PERCENTAGE: int = 0
    REDIS_MIGRATION_USER_WHITELIST: str = ""  # Comma-separated user IDs

    # Multi-Symbol Trading Feature Flags
    PRESET_SYSTEM_ENABLED: bool = True  # Phase 1: 프리셋 시스템 활성화
    MULTI_SYMBOL_ENABLED: bool = True   # Phase 2: 멀티심볼 지원 활성화
    MAX_SYMBOLS_PER_USER: int = 99      # 사용자당 최대 동시 트레이딩 심볼 수 (실질적 무제한)

    # Signal Bot 설정
    # OKX Signal Bot Webhook URL (https://www.okx.com/algo/signal/trigger)
    SIGNAL_BOT_WEBHOOK_URL: str = os.environ.get(
        "SIGNAL_BOT_WEBHOOK_URL",
        "https://www.okx.com/algo/signal/trigger"
    )
    # Signal Bot 최대 지연 시간 (초) - 시그널 유효 시간
    SIGNAL_BOT_MAX_LAG: int = int(os.environ.get("SIGNAL_BOT_MAX_LAG", "60"))

    def init_redis_url(self):
        if not self.REDIS_URL:
            if self.REDIS_PASSWORD:
                auth = f":{self.REDIS_PASSWORD}@"
            else:
                auth = ""
            self.REDIS_URL = f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def CELERY_BROKER_URL(self) -> str:
        return self.REDIS_URL.replace(f"/{self.REDIS_DB}", "/1")

    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return self.CELERY_BROKER_URL

    # 환경 설정
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # 데이터베이스 상세 설정
    DB_USER: str = os.getenv("DB_USER", "")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_HOST: str = os.getenv("DB_HOST", "")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_NAME: str = os.getenv("DB_NAME", "")

    # 데이터베이스 설정 (동적 구성)
    @property
    def DATABASE_URL(self) -> str:
        """Construct DATABASE_URL from individual components"""
        env_url = os.getenv("DATABASE_URL", "")
        # If DATABASE_URL is already set and doesn't contain ${}, use it
        if env_url and "${" not in env_url:
            return env_url
        # Otherwise, construct from components
        if self.DB_USER and self.DB_PASSWORD and self.DB_HOST and self.DB_NAME:
            return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        return ""

    @property
    def db_url(self) -> str:
        """Alias for DATABASE_URL for backward compatibility"""
        return self.DATABASE_URL

    # 데이터베이스 풀 설정
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True

    # 로깅 설정
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # 웹소켓 설정
    WEBSOCKET_PING_INTERVAL: int = 30
    WEBSOCKET_PING_TIMEOUT: int = 10

    # API 요청 설정
    API_REQUEST_TIMEOUT: int = 30
    API_RETRY_COUNT: int = 5

    # Telegram 설정
    TELEGRAM_BOT_TOKEN: str = ""
    OWNER_ID: int = 0

    # TimescaleDB 설정
    TIMESCALE_HOST: str = os.getenv("TIMESCALE_HOST", "")
    TIMESCALE_PORT: int = int(os.getenv("TIMESCALE_PORT", "5432"))
    TIMESCALE_DATABASE: str = os.getenv("TIMESCALE_DATABASE", "")
    TIMESCALE_USER: str = os.getenv("TIMESCALE_USER", "")
    TIMESCALE_PASSWORD: str = os.getenv("TIMESCALE_PASSWORD", "")

    # CandlesDB 설정 (OHLCV market data)
    CANDLES_HOST: str = os.getenv("CANDLES_HOST", "158.247.251.34")
    CANDLES_PORT: int = int(os.getenv("CANDLES_PORT", "5432"))
    CANDLES_DATABASE: str = os.getenv("CANDLES_DATABASE", "candlesdb")
    CANDLES_USER: str = os.getenv("CANDLES_USER", "tradeuser")
    CANDLES_PASSWORD: str = os.getenv("CANDLES_PASSWORD", "SecurePassword123")
    CANDLES_SCHEMA: str = os.getenv("CANDLES_SCHEMA", "public")


@lru_cache()
def get_settings():
    s = Settings()
    s.init_redis_url()
    return s


settings = get_settings()

# 다른 모듈에서 사용할 변수들
OKX_API_KEY = settings.OKX_API_KEY
OKX_SECRET_KEY = settings.OKX_SECRET_KEY
OKX_PASSPHRASE = settings.OKX_PASSPHRASE
TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
OWNER_ID = settings.OWNER_ID
DATABASE_URL = settings.DATABASE_URL
REDIS_URL = settings.REDIS_URL
REDIS_HOST = settings.REDIS_HOST
REDIS_PORT = settings.REDIS_PORT
REDIS_PASSWORD = settings.REDIS_PASSWORD
