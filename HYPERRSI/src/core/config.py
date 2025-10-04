#src/core/config.py

from numpy import dot
from pydantic_settings import BaseSettings
from functools import lru_cache
from dotenv import load_dotenv
import os

load_dotenv()

API_BASE_URL = "/api"
class Settings(BaseSettings):
    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "validate_assignment": True,
        "extra": "allow"
    
    }

    # API 설정
    OKX_API_KEY: str
    OKX_SECRET_KEY: str
    OKX_PASSPHRASE: str
    
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
            print(f"REDIS_URL: {self.REDIS_URL}")

    @property
    def CELERY_BROKER_URL(self) -> str:
        return self.REDIS_URL.replace(f"/{self.REDIS_DB}", "/1")

    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return self.CELERY_BROKER_URL

    # 환경 설정
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    
    # 데이터베이스 설정
    DATABASE_URL: str = os.getenv("DATABASE_URL")
        
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
    TELEGRAM_BOT_TOKEN: str
    OWNER_ID: int
    
    # 데이터베이스 상세 설정
    DB_USER: str = "postgres.pybdkhfbkamagahgyybk"
    DB_PASSWORD: str = "Tmdehfl2014!"
    DB_HOST: str = "aws-0-ap-northeast-2.pooler.supabase.com"
    DB_PORT: str = "6543"
    DB_NAME: str = "postgres"


@lru_cache()
def get_settings():
    s = Settings()
    s.init_redis_url()
    return s

settings = get_settings()