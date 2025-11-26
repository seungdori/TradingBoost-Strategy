"""
HYPERRSI Cache Sync Service.

PostgreSQL ↔ Redis 동기화 서비스.
기존 Redis 키 패턴을 유지하여 후방 호환성을 보장합니다.
"""

import json
from typing import Optional, Dict, Any

from shared.logging import get_logger

logger = get_logger(__name__)


class CacheSyncService:
    """
    PostgreSQL ↔ Redis 동기화 서비스.

    PostgreSQL이 SSOT (Source of Truth)이고,
    Redis는 성능을 위한 캐시로 사용됩니다.

    기존 Redis 키 패턴을 유지하여 후방 호환성을 보장:
    - user:{okx_uid}:trading:status
    - user:{okx_uid}:settings
    - user:{okx_uid}:dual_side
    - user:{okx_uid}:position:{symbol}:{side}
    """

    def __init__(self):
        """Initialize cache sync service."""
        self._redis = None

    async def _get_redis(self):
        """Get Redis client (lazy loading)."""
        if self._redis is None:
            from shared.database.redis import get_redis
            self._redis = await get_redis()
        return self._redis

    async def sync_session_start(
        self,
        okx_uid: str,
        symbol: str,
        timeframe: str,
        session_id: int,
        params_settings: dict,
        dual_side_settings: dict
    ) -> None:
        """
        세션 시작 시 Redis 동기화.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            timeframe: 타임프레임
            session_id: 세션 ID
            params_settings: 트레이딩 파라미터
            dual_side_settings: 양방향 설정
        """
        try:
            redis = await self._get_redis()

            # 기존 키 패턴 유지
            status_key = f"user:{okx_uid}:trading:status"
            settings_key = f"user:{okx_uid}:settings"
            dual_side_key = f"user:{okx_uid}:dual_side"
            session_key = f"user:{okx_uid}:session_id"

            async with redis.pipeline() as pipe:
                # 트레이딩 상태
                pipe.set(status_key, "running")

                # 세션 ID
                pipe.set(session_key, str(session_id))

                # 설정값 (JSON)
                pipe.set(settings_key, json.dumps(params_settings))

                # dual_side 설정 (HASH)
                pipe.delete(dual_side_key)
                if dual_side_settings:
                    # HASH에 저장하기 위해 값을 문자열로 변환
                    hash_data = self._prepare_hash_data(dual_side_settings)
                    if hash_data:
                        pipe.hset(dual_side_key, mapping=hash_data)

                await pipe.execute()

            logger.debug(
                f"Session start synced to Redis: okx_uid={okx_uid}, "
                f"symbol={symbol}, session_id={session_id}"
            )

        except Exception as e:
            logger.error(f"Failed to sync session start to Redis: {e}", exc_info=True)
            raise

    async def sync_session_stop(
        self,
        okx_uid: str,
        symbol: str
    ) -> None:
        """
        세션 종료 시 Redis 동기화.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
        """
        try:
            redis = await self._get_redis()

            status_key = f"user:{okx_uid}:trading:status"
            session_key = f"user:{okx_uid}:session_id"

            async with redis.pipeline() as pipe:
                pipe.set(status_key, "stopped")
                pipe.delete(session_key)
                await pipe.execute()

            logger.debug(
                f"Session stop synced to Redis: okx_uid={okx_uid}, symbol={symbol}"
            )

        except Exception as e:
            logger.error(f"Failed to sync session stop to Redis: {e}", exc_info=True)
            raise

    async def sync_position(
        self,
        okx_uid: str,
        symbol: str,
        side: str,
        position_data: Dict[str, Any]
    ) -> None:
        """
        포지션 상태 Redis 동기화.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            side: 포지션 방향 ('long', 'short', 'hedge')
            position_data: 포지션 데이터
        """
        try:
            redis = await self._get_redis()

            if side in ('long', 'short'):
                position_key = f"user:{okx_uid}:position:{symbol}:{side}"
            else:  # hedge
                position_key = f"user:{okx_uid}:{symbol}:dual_side_position"

            # HASH로 저장
            hash_data = self._prepare_hash_data(position_data)
            if hash_data:
                await redis.delete(position_key)
                await redis.hset(position_key, mapping=hash_data)

            logger.debug(
                f"Position synced to Redis: okx_uid={okx_uid}, "
                f"symbol={symbol}, side={side}"
            )

        except Exception as e:
            logger.error(f"Failed to sync position to Redis: {e}", exc_info=True)
            raise

    async def clear_position(
        self,
        okx_uid: str,
        symbol: str,
        side: str
    ) -> None:
        """
        포지션 청산 시 Redis 캐시 정리.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            side: 포지션 방향 ('long', 'short', 'hedge')
        """
        try:
            redis = await self._get_redis()

            if side in ('long', 'short'):
                position_key = f"user:{okx_uid}:position:{symbol}:{side}"
            else:  # hedge
                position_key = f"user:{okx_uid}:{symbol}:dual_side_position"

            await redis.delete(position_key)

            logger.debug(
                f"Position cleared from Redis: okx_uid={okx_uid}, "
                f"symbol={symbol}, side={side}"
            )

        except Exception as e:
            logger.error(f"Failed to clear position from Redis: {e}", exc_info=True)
            raise

    async def sync_settings(
        self,
        okx_uid: str,
        symbol: str,
        params_settings: Optional[Dict[str, Any]] = None,
        dual_side_settings: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        설정 Redis 동기화.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            params_settings: 트레이딩 파라미터 (optional)
            dual_side_settings: 양방향 설정 (optional)
        """
        try:
            redis = await self._get_redis()

            async with redis.pipeline() as pipe:
                if params_settings is not None:
                    settings_key = f"user:{okx_uid}:settings"
                    pipe.set(settings_key, json.dumps(params_settings))

                if dual_side_settings is not None:
                    dual_side_key = f"user:{okx_uid}:dual_side"
                    pipe.delete(dual_side_key)
                    hash_data = self._prepare_hash_data(dual_side_settings)
                    if hash_data:
                        pipe.hset(dual_side_key, mapping=hash_data)

                await pipe.execute()

            logger.debug(
                f"Settings synced to Redis: okx_uid={okx_uid}, symbol={symbol}"
            )

        except Exception as e:
            logger.error(f"Failed to sync settings to Redis: {e}", exc_info=True)
            raise

    async def invalidate_cache(
        self,
        okx_uid: str,
        symbol: Optional[str] = None
    ) -> None:
        """
        Redis 캐시 무효화.

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼 (optional, None이면 사용자 전체)
        """
        try:
            redis = await self._get_redis()

            if symbol:
                # 특정 심볼만 무효화
                keys_to_delete = [
                    f"user:{okx_uid}:position:{symbol}:long",
                    f"user:{okx_uid}:position:{symbol}:short",
                    f"user:{okx_uid}:{symbol}:dual_side_position",
                ]
            else:
                # 사용자 전체 무효화
                keys_to_delete = [
                    f"user:{okx_uid}:trading:status",
                    f"user:{okx_uid}:settings",
                    f"user:{okx_uid}:dual_side",
                    f"user:{okx_uid}:session_id",
                ]

            for key in keys_to_delete:
                await redis.delete(key)

            logger.debug(
                f"Cache invalidated: okx_uid={okx_uid}, symbol={symbol}"
            )

        except Exception as e:
            logger.error(f"Failed to invalidate cache: {e}", exc_info=True)
            raise

    async def get_from_redis(
        self,
        okx_uid: str,
        symbol: str,
        side: str
    ) -> Optional[Dict[str, Any]]:
        """
        Redis에서 포지션 데이터 조회 (fallback용).

        Args:
            okx_uid: OKX 사용자 UID
            symbol: 거래 심볼
            side: 포지션 방향

        Returns:
            Optional[Dict]: 포지션 데이터 (없으면 None)
        """
        try:
            redis = await self._get_redis()

            if side in ('long', 'short'):
                position_key = f"user:{okx_uid}:position:{symbol}:{side}"
            else:
                position_key = f"user:{okx_uid}:{symbol}:dual_side_position"

            data = await redis.hgetall(position_key)

            if not data:
                return None

            # bytes → str 변환 및 타입 복원
            return self._restore_hash_data(data)

        except Exception as e:
            logger.error(f"Failed to get from Redis: {e}", exc_info=True)
            return None

    def _prepare_hash_data(self, data: Dict[str, Any]) -> Dict[str, str]:
        """
        HASH 저장용 데이터 준비 (모든 값을 문자열로 변환).

        Args:
            data: 원본 데이터

        Returns:
            Dict[str, str]: 문자열로 변환된 데이터
        """
        result = {}
        for key, value in data.items():
            if value is None:
                result[key] = ""
            elif isinstance(value, (dict, list)):
                result[key] = json.dumps(value)
            elif isinstance(value, bool):
                result[key] = "1" if value else "0"
            else:
                result[key] = str(value)
        return result

    def _restore_hash_data(self, data: Dict[bytes, bytes]) -> Dict[str, Any]:
        """
        HASH에서 읽은 데이터 복원.

        Args:
            data: Redis에서 읽은 원본 데이터

        Returns:
            Dict[str, Any]: 타입 복원된 데이터
        """
        result = {}
        for key, value in data.items():
            # bytes → str
            k = key.decode() if isinstance(key, bytes) else key
            v = value.decode() if isinstance(value, bytes) else value

            # 타입 복원 시도
            if v == "":
                result[k] = None
            elif v in ("0", "1") and k in (
                'use_dual_side_entry', 'activate_tp_sl_after_all_dca',
                'use_dual_sl', 'break_even_active', 'trailing_active'
            ):
                result[k] = v == "1"
            else:
                try:
                    # JSON 파싱 시도
                    result[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    # 숫자 변환 시도
                    try:
                        if '.' in v:
                            result[k] = float(v)
                        else:
                            result[k] = int(v)
                    except ValueError:
                        result[k] = v

        return result


# Global singleton instance
_cache_sync_service: Optional[CacheSyncService] = None


def get_cache_sync_service() -> CacheSyncService:
    """Get singleton CacheSyncService instance."""
    global _cache_sync_service
    if _cache_sync_service is None:
        _cache_sync_service = CacheSyncService()
    return _cache_sync_service
