# src/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from functools import lru_cache
from pathlib import Path

# 프로젝트 루트 경로 찾기
PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

class Settings(BaseSettings):
    # OKX API 설정
    OKX_API_KEY: str
    OKX_SECRET_KEY: str
    OKX_PASSPHRASE: str

    # Telegram 설정
    TELEGRAM_BOT_TOKEN: str
    OWNER_ID: int

    # 데이터베이스 설정
    DATABASE_URL: str
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_PORT: int
    DB_NAME: str

    # Redis 설정
    REDIS_URL: Optional[str] = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: str = "6379"
    REDIS_DB: str = "0"
    REDIS_PASSWORD: Optional[str] = None

    # Order Backend 설정
    ORDER_BACKEND: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding='utf-8',
        case_sensitive=True,
        extra='allow'
    )
@lru_cache()
def get_settings() -> Settings:
    """캐시된 설정 가져오기"""
    return Settings()  # type: ignore[call-arg]

# 설정 인스턴스 생성
settings = get_settings()

# 다른 모듈에서 사용할 변수들
OKX_API_KEY = settings.OKX_API_KEY
OKX_SECRET_KEY = settings.OKX_SECRET_KEY
OKX_PASSPHRASE = settings.OKX_PASSPHRASE

# Telegram 설정
TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
OWNER_ID = settings.OWNER_ID

# 데이터베이스 URL 구성
DATABASE_URL = settings.DATABASE_URL

# Redis URL
REDIS_URL = settings.REDIS_URL
if not REDIS_URL:
    if settings.REDIS_PASSWORD:
        REDIS_URL = f"redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    else:
        REDIS_URL = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
print(f"REDIS_URL: {REDIS_URL}")