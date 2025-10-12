import json
import logging
from typing import Dict, Mapping, Optional, cast

import redis.asyncio as redis

from shared.config import settings
from shared.dtos.exchange import ApiKeyDto, ExchangeApiKeyDto

logger = logging.getLogger(__name__)

# Redis 클라이언트 생성 헬퍼 함수
async def _get_redis_client():
    """Redis 클라이언트를 생성하고 반환합니다."""
    if settings.REDIS_PASSWORD:
        return redis.from_url(
            f"redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
            encoding='utf-8',
            decode_responses=True
        )
    else:
        return redis.from_url(
            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
            encoding='utf-8',
            decode_responses=True
        )

class ApiKeyStore:
    def __init__(self, redis_client: redis.Redis, user_id: str) -> None:
        self.redis_client = redis_client
        self.key_prefix = f"user:{user_id}:exchange:api_keys"

    async def get_binance_keys(self) -> ApiKeyDto:
        """Binance API 키 조회"""
        try:
            key_data = await self.redis_client.hgetall(f"{self.key_prefix}:binance")
            if not key_data:
                # 설정에서 기본값 사용
                return ApiKeyDto(
                    api_key=settings.BINANCE_API_KEY if hasattr(settings, 'BINANCE_API_KEY') else "",
                    secret_key=settings.BINANCE_SECRET_KEY if hasattr(settings, 'BINANCE_SECRET_KEY') else "",
                    password=None
                )
            return ApiKeyDto(
                api_key=key_data.get('api_key', ''),
                secret_key=key_data.get('secret_key', ''),
                password=None
            )
        except Exception as e:
            logger.error(f"Binance API 키 조회 실패: {str(e)}")
            raise
        
    async def get_upbit_keys(self) -> ApiKeyDto:
        """Upbit API 키 조회"""
        try:
            key_data = await self.redis_client.hgetall(f"{self.key_prefix}:upbit")
            if not key_data:
                # 설정에서 기본값 사용
                return ApiKeyDto(
                    api_key=settings.UPBIT_API_KEY if hasattr(settings, 'UPBIT_API_KEY') else "",
                    secret_key=settings.UPBIT_SECRET_KEY if hasattr(settings, 'UPBIT_SECRET_KEY') else "",
                    password=None
                )
            return ApiKeyDto(
                api_key=key_data.get('api_key', ''),
                secret_key=key_data.get('secret_key', ''),
                password=None
            )
        except Exception as e:
            logger.error(f"Upbit API 키 조회 실패: {str(e)}")
            raise

    async def get_bitget_keys(self) -> ApiKeyDto:
        """Bitget API 키 조회"""
        try:
            key_data = await self.redis_client.hgetall(f"{self.key_prefix}:bitget")
            if not key_data:
                # 설정에서 기본값 사용
                return ApiKeyDto(
                    api_key=settings.BITGET_API_KEY if hasattr(settings, 'BITGET_API_KEY') else "",
                    secret_key=settings.BITGET_SECRET_KEY if hasattr(settings, 'BITGET_SECRET_KEY') else "",
                    password=settings.BITGET_PASSPHRASE if hasattr(settings, 'BITGET_PASSPHRASE') else ""
                )
            return ApiKeyDto(
                api_key=key_data.get('api_key', ''),
                secret_key=key_data.get('secret_key', ''),
                password=key_data.get('password', '')
            )
        except Exception as e:
            logger.error(f"Bitget API 키 조회 실패: {str(e)}")
            raise

    async def get_okx_keys(self) -> ApiKeyDto:
        """OKX API 키 조회"""
        try:
            key_data = await self.redis_client.hgetall(f"{self.key_prefix}:okx")
            if not key_data:
                # 설정에서 기본값 사용
                return ApiKeyDto(
                    api_key=settings.OKX_API_KEY if hasattr(settings, 'OKX_API_KEY') else "",
                    secret_key=settings.OKX_SECRET_KEY if hasattr(settings, 'OKX_SECRET_KEY') else "",
                    password=settings.OKX_PASSPHRASE if hasattr(settings, 'OKX_PASSPHRASE') else ""
                )
            return ApiKeyDto(
                api_key=key_data.get('api_key', ''),
                secret_key=key_data.get('secret_key', ''),
                password=key_data.get('password', '')
            )
        except Exception as e:
            logger.error(f"OKX API 키 조회 실패: {str(e)}")
            raise
        
    async def set_binance_keys(self, api_key: str, secret_key: str) -> None:
        """Binance API 키 설정"""
        try:
            await self.redis_client.hset(f"{self.key_prefix}:binance", mapping=cast(Mapping[str | bytes, bytes | float | int | str], {
                'api_key': api_key,
                'secret_key': secret_key
            }))
            logger.info("Binance API 키 설정 완료")
        except Exception as e:
            logger.error(f"Binance API 키 설정 실패: {str(e)}")
            raise

    async def set_upbit_keys(self, api_key: str, secret_key: str) -> None:
        """Upbit API 키 설정"""
        try:
            await self.redis_client.hset(f"{self.key_prefix}:upbit", mapping=cast(Mapping[str | bytes, bytes | float | int | str], {
                'api_key': api_key,
                'secret_key': secret_key
            }))
            logger.info("Upbit API 키 설정 완료")
        except Exception as e:
            logger.error(f"Upbit API 키 설정 실패: {str(e)}")
            raise

    async def set_bitget_keys(self, api_key: str, secret_key: str, password: Optional[str] = None) -> None:
        """Bitget API 키 설정"""
        try:
            await self.redis_client.hset(f"{self.key_prefix}:bitget", mapping=cast(Mapping[str | bytes, bytes | float | int | str], {
                'api_key': api_key,
                'secret_key': secret_key,
                'password': password or ''
            }))
            logger.info("Bitget API 키 설정 완료")
        except Exception as e:
            logger.error(f"Bitget API 키 설정 실패: {str(e)}")
            raise

    async def set_okx_keys(self, api_key: str, secret_key: str, password: Optional[str] = None) -> None:
        """OKX API 키 설정"""
        try:
            await self.redis_client.hset(f"{self.key_prefix}:okx", mapping=cast(Mapping[str | bytes, bytes | float | int | str], {
                'api_key': api_key,
                'secret_key': secret_key,
                'password': password or ''
            }))
            logger.info("OKX API 키 설정 완료")
        except Exception as e:
            logger.error(f"OKX API 키 설정 실패: {str(e)}")
            raise

# ExchangeStore 클래스 정의
class ExchangeStore:
    def __init__(self, redis_client: redis.Redis) -> None:
        self._key_store = ApiKeyStore(redis_client, user_id="default")

    def get_key_store(self) -> ApiKeyStore:
        return self._key_store

# 전역 인스턴스 생성 (redis_client는 외부에서 주입받아야 함)
# exchange_store = ExchangeStore(redis_client)  # 사용 시 redis_client를 전달받아야 함

async def get_exchange_api_keys(exchange_name: str, redis_client: Optional[redis.Redis] = None) -> ApiKeyDto:
    """
    거래소 이름에 따라 API 키 정보를 조회합니다.

    Args:
        exchange_name (str): 거래소 이름 (binance, upbit, bitget, okx 등)
        redis_client: Redis 클라이언트 인스턴스 (선택사항, None이면 자동 생성)

    Returns:
        ApiKeys: API 키 정보 객체

    Raises:
        Exception: 알 수 없는 거래소 이름일 경우
    """
    # Redis 클라이언트가 없으면 자동 생성
    if redis_client is None:
        redis_client = await _get_redis_client()
        should_close = True
    else:
        should_close = False

    try:
        exchange_store = ExchangeStore(redis_client)
        key_store: ApiKeyStore = exchange_store.get_key_store()

        if exchange_name == "binance":
            result = await key_store.get_binance_keys()
        elif exchange_name == "binance_spot":
            result = await key_store.get_binance_keys()
        elif exchange_name == "upbit":
            result = await key_store.get_upbit_keys()
        elif exchange_name == "bitget":
            result = await key_store.get_bitget_keys()
        elif exchange_name == "okx":
            result = await key_store.get_okx_keys()
        elif exchange_name == "bitget_spot":
            result = await key_store.get_bitget_keys()
        elif exchange_name == "okx_spot":
            result = await key_store.get_okx_keys()
        else:
            raise Exception('Unknown exchange')

        return result
    finally:
        # 자동 생성한 클라이언트는 닫기
        if should_close and redis_client:
            await redis_client.close()

async def update_exchange_api_keys(dto: ExchangeApiKeyDto, redis_client: Optional[redis.Redis] = None) -> ApiKeyDto:
    """
    거래소 API 키 정보를 업데이트합니다.

    Args:
        dto (ExchangeApiKeyDto): API 키 정보 DTO
        redis_client: Redis 클라이언트 인스턴스 (선택사항, None이면 자동 생성)

    Returns:
        ApiKeys: 업데이트된 API 키 정보

    Raises:
        Exception: 알 수 없는 거래소 이름일 경우
    """
    # Redis 클라이언트가 없으면 자동 생성
    if redis_client is None:
        redis_client = await _get_redis_client()
        should_close = True
    else:
        should_close = False

    try:
        exchange_name = dto.exchange_name
        api_key = dto.api_key
        secret = dto.secret_key
        password = dto.password
        exchange_store = ExchangeStore(redis_client)
        key_store: ApiKeyStore = exchange_store.get_key_store()

        if exchange_name == 'binance':
            await key_store.set_binance_keys(api_key=api_key, secret_key=secret)
            result = await key_store.get_binance_keys()
        elif exchange_name == 'upbit':
            await key_store.set_upbit_keys(api_key=api_key, secret_key=secret)
            result = await key_store.get_upbit_keys()
        elif exchange_name == 'bitget':
            await key_store.set_bitget_keys(api_key=api_key, secret_key=secret, password=password)
            result = await key_store.get_bitget_keys()
        elif exchange_name == 'okx':
            await key_store.set_okx_keys(api_key=api_key, secret_key=secret, password=password)
            result = await key_store.get_okx_keys()
        elif exchange_name == 'binance_spot':
            await key_store.set_binance_keys(api_key=api_key, secret_key=secret)
            result = await key_store.get_binance_keys()
        elif exchange_name == 'bitget_spot':
            await key_store.set_bitget_keys(api_key=api_key, secret_key=secret, password=password)
            result = await key_store.get_bitget_keys()
        elif exchange_name == 'okx_spot':
            await key_store.set_okx_keys(api_key=api_key, secret_key=secret, password=password)
            result = await key_store.get_okx_keys()
        else:
            raise Exception('Unknown exchange')

        return result
    finally:
        # 자동 생성한 클라이언트는 닫기
        if should_close and redis_client:
            await redis_client.close()

# 사용자별 API 키 관리 함수
async def get_user_api_keys(user_id: str, redis_client: Optional[redis.Redis] = None) -> dict[str, str]:
    """
    사용자 ID를 기반으로 Redis에서 API 키를 가져오는 함수

    Args:
        user_id (str): 사용자 ID
        redis_client: Redis 클라이언트 인스턴스 (선택사항, None이면 자동 생성)

    Returns:
        Dict[str, str]: API 키 정보
    """
    # Redis 클라이언트가 없으면 자동 생성
    if redis_client is None:
        redis_client = await _get_redis_client()
        should_close = True
    else:
        should_close = False

    try:
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        return api_keys
    except Exception as e:
        logger.error(f"사용자 API 키 조회 실패: {str(e)}")
        raise
    finally:
        # 자동 생성한 클라이언트는 닫기
        if should_close and redis_client:
            await redis_client.close()
