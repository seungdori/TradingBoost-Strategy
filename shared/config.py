"""Shared configuration for TradingBoost-Strategy projects"""

from pydantic_settings import BaseSettings
from functools import lru_cache
from dotenv import load_dotenv
import os

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

    # Redis 설정
    REDIS_HOST: str = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.environ.get("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str | None = os.environ.get("REDIS_PASSWORD", None)
    REDIS_PURE_URL: str = f"redis://{REDIS_HOST}:{REDIS_PORT}"
    REDIS_DB: int = 0
    REDIS_URL: str = f"redis://{REDIS_HOST}:{REDIS_PORT}"

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
