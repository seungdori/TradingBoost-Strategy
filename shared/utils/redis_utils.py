"""Redis 유틸리티 함수

공통적으로 사용되는 Redis 관련 유틸리티 함수들
"""
import json
import logging
from typing import Any

from redis.asyncio import Redis as AsyncRedis

logger = logging.getLogger(__name__)


async def set_redis_data(redis_client: AsyncRedis, key: str, data: Any, expiry: int = 144000) -> None:
    """
    Redis에 데이터를 저장합니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        key: Redis 키
        data: 저장할 데이터 (JSON 직렬화 가능한 객체)
        expiry: 만료 시간 (초 단위, 기본값: 144000초 = 40시간)
    """
    await redis_client.set(key, json.dumps(data), ex=expiry)


async def get_redis_data(redis_client: AsyncRedis, key: str) -> Any | None:
    """
    Redis에서 데이터를 가져옵니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        key: Redis 키

    Returns:
        저장된 데이터 또는 None (데이터가 없는 경우)
    """
    data = await redis_client.get(key)
    return json.loads(data) if data else None


async def delete_redis_data(redis_client: AsyncRedis, key: str) -> bool:
    """
    Redis에서 데이터를 삭제합니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        key: Redis 키

    Returns:
        삭제 성공 여부
    """
    result: int = await redis_client.delete(key)
    return result > 0


async def exists_redis_key(redis_client: AsyncRedis, key: str) -> bool:
    """
    Redis 키가 존재하는지 확인합니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        key: Redis 키

    Returns:
        키 존재 여부
    """
    exists_result: int = await redis_client.exists(key)
    return exists_result > 0


# ============================================================================
# 사용자 설정 관련
# ============================================================================

async def get_user_settings(redis_client: AsyncRedis, user_id: str) -> dict[str, Any]:
    """
    사용자의 설정 정보를 가져옵니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        user_id: 사용자 ID

    Returns:
        dict: 사용자 설정 정보
    """
    try:
        settings_key = f"user:{user_id}:settings"
        settings_data = await redis_client.get(settings_key)

        if settings_data:
            settings_dict: dict[str, Any] = json.loads(settings_data)
            return settings_dict
        else:
            # 기본 설정값
            return {
                'use_sl': True,
                'use_break_even': False,
                'use_break_even_tp2': False,
                'use_break_even_tp3': False
            }
    except Exception as e:
        logger.error(f"Error getting settings for user {user_id}: {str(e)}")
        return {
            'use_sl': True,
            'use_break_even': False,
            'use_break_even_tp2': False,
            'use_break_even_tp3': False
        }


async def set_user_settings(redis_client: AsyncRedis, user_id: str, settings: dict[str, Any], expiry: int = 86400 * 30) -> bool:
    """
    사용자 설정을 저장합니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        user_id: 사용자 ID
        settings: 설정 딕셔너리
        expiry: 만료 시간 (기본 30일)

    Returns:
        bool: 저장 성공 여부
    """
    try:
        settings_key = f"user:{user_id}:settings"
        await redis_client.set(settings_key, json.dumps(settings), ex=expiry)
        return True
    except Exception as e:
        logger.error(f"Error setting user settings for {user_id}: {str(e)}")
        return False


# ============================================================================
# 최근 심볼 관리
# ============================================================================

async def add_recent_symbol(redis_client: AsyncRedis, user_id: str, symbol: str, max_symbols: int = 10) -> None:
    """
    사용자의 최근 거래 심볼을 Redis에 추가합니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        user_id: 사용자 ID (OKX UID)
        symbol: 거래 심볼
        max_symbols: 최대 저장 개수 (기본 10개)
    """
    try:
        recent_symbols_key = f"user:{user_id}:recent_symbols"

        # 기존 최근 심볼 목록 조회
        recent_symbols_data = await redis_client.get(recent_symbols_key)
        recent_symbols: list[str] = json.loads(recent_symbols_data) if recent_symbols_data else []

        # 이미 있는 심볼이면 맨 앞으로 이동
        if symbol in recent_symbols:
            recent_symbols.remove(symbol)

        # 맨 앞에 추가
        recent_symbols.insert(0, symbol)

        # 최대 개수까지만 유지
        recent_symbols = recent_symbols[:max_symbols]

        # Redis에 저장
        await redis_client.set(recent_symbols_key, json.dumps(recent_symbols), ex=86400 * 30)  # 30일 TTL

    except Exception as e:
        logger.error(f"최근 심볼 추가 중 오류: {str(e)}")


async def get_recent_symbols(redis_client: AsyncRedis, user_id: str, default_symbols: list[str] | None = None) -> list[str]:
    """
    사용자의 최근 거래 심볼 목록을 조회합니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        user_id: 사용자 ID (OKX UID)
        default_symbols: 기본 심볼 목록

    Returns:
        list: 최근 거래 심볼 목록
    """
    try:
        recent_symbols_key = f"user:{user_id}:recent_symbols"
        recent_symbols_data = await redis_client.get(recent_symbols_key)

        if recent_symbols_data:
            symbols_list: list[str] = json.loads(recent_symbols_data)
            return symbols_list

        # 데이터가 없으면 기본 심볼 반환
        return default_symbols if default_symbols else []

    except Exception as e:
        logger.error(f"최근 심볼 조회 중 오류: {str(e)}")
        return default_symbols if default_symbols else []


# ============================================================================
# 포지션 및 주문 관리
# ============================================================================

async def get_position(redis_client: AsyncRedis, user_id: str, symbol: str, side: str | None = None) -> dict[str, Any] | None:
    """
    포지션 정보를 조회합니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        user_id: 사용자 ID
        symbol: 심볼
        side: 포지션 사이드 (선택)

    Returns:
        포지션 데이터 또는 None
    """
    try:
        if side:
            key = f"user:{user_id}:position:{symbol}:{side}"
        else:
            key = f"position:{user_id}:{symbol}"

        data = await redis_client.get(key)
        if data:
            position_dict: dict[str, Any] = json.loads(data)
            return position_dict
        return None
    except Exception as e:
        logger.error(f"포지션 조회 중 오류: {str(e)}")
        return None


async def set_position(redis_client: AsyncRedis, user_id: str, symbol: str, position_data: dict[str, Any], side: str | None = None, expiry: int = 300) -> bool:
    """
    포지션 정보를 저장합니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        user_id: 사용자 ID
        symbol: 심볼
        position_data: 포지션 데이터
        side: 포지션 사이드 (선택)
        expiry: 만료 시간 (기본 300초)

    Returns:
        bool: 저장 성공 여부
    """
    try:
        if side:
            key = f"user:{user_id}:position:{symbol}:{side}"
        else:
            key = f"position:{user_id}:{symbol}"

        await redis_client.set(key, json.dumps(position_data), ex=expiry)
        return True
    except Exception as e:
        logger.error(f"포지션 저장 중 오류: {str(e)}")
        return False


async def delete_position(redis_client: AsyncRedis, user_id: str, symbol: str, side: str | None = None) -> bool:
    """
    포지션 정보를 삭제합니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        user_id: 사용자 ID
        symbol: 심볼
        side: 포지션 사이드 (선택)

    Returns:
        bool: 삭제 성공 여부
    """
    try:
        if side:
            key = f"user:{user_id}:position:{symbol}:{side}"
        else:
            key = f"position:{user_id}:{symbol}"

        result: int = await redis_client.delete(key)
        return result > 0
    except Exception as e:
        logger.error(f"포지션 삭제 중 오류: {str(e)}")
        return False
