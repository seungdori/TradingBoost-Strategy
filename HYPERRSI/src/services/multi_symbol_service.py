# src/services/multi_symbol_service.py
"""
Multi-Symbol Trading Service - 멀티심볼 트레이딩 관리 서비스

사용자당 최대 3개의 심볼을 동시에 트레이딩할 수 있도록 지원합니다.
Feature Flag로 활성화/비활성화됩니다.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from shared.config import settings as app_settings
from shared.database.redis_patterns import redis_context, RedisTimeout
from shared.logging import get_logger

logger = get_logger(__name__)

# Redis 키 상수 (trading_tasks.py와 동일하게 유지)
REDIS_KEY_ACTIVE_SYMBOLS = "user:{okx_uid}:active_symbols"
REDIS_KEY_SYMBOL_TASK_ID = "user:{okx_uid}:symbol:{symbol}:task_id"
REDIS_KEY_SYMBOL_TASK_RUNNING = "user:{okx_uid}:symbol:{symbol}:task_running"
REDIS_KEY_SYMBOL_PRESET_ID = "user:{okx_uid}:symbol:{symbol}:preset_id"
REDIS_KEY_SYMBOL_TIMEFRAME = "user:{okx_uid}:symbol:{symbol}:timeframe"
REDIS_KEY_SYMBOL_STARTED_AT = "user:{okx_uid}:symbol:{symbol}:started_at"
REDIS_KEY_SYMBOL_STATUS = "user:{okx_uid}:symbol:{symbol}:status"
# REDIS_KEY_TRADING_STATUS 제거 - 심볼별 상태 관리로 완전히 전환

# Signal Bot 모드용 Redis 키 상수 (signal_token별 관리)
REDIS_KEY_SIGNAL_BOT_ACTIVE = "user:{okx_uid}:signal_bots"  # SET: 활성 signal_token 목록
REDIS_KEY_SIGNAL_BOT_TASK_ID = "user:{okx_uid}:signal_bot:{signal_token}:task_id"
REDIS_KEY_SIGNAL_BOT_SYMBOL = "user:{okx_uid}:signal_bot:{signal_token}:symbol"
REDIS_KEY_SIGNAL_BOT_TIMEFRAME = "user:{okx_uid}:signal_bot:{signal_token}:timeframe"
REDIS_KEY_SIGNAL_BOT_STATUS = "user:{okx_uid}:signal_bot:{signal_token}:status"
REDIS_KEY_SIGNAL_BOT_STARTED_AT = "user:{okx_uid}:signal_bot:{signal_token}:started_at"


class MaxSymbolsReachedError(Exception):
    """최대 심볼 수 초과 예외"""
    def __init__(self, active_symbols: List[str], max_symbols: int):
        self.active_symbols = active_symbols
        self.max_symbols = max_symbols
        super().__init__(
            f"최대 {max_symbols}개 심볼까지 동시 트레이딩 가능합니다. "
            f"현재 활성: {', '.join(active_symbols)}"
        )


class SymbolAlreadyActiveError(Exception):
    """이미 활성화된 심볼 예외"""
    pass


class MultiSymbolService:
    """멀티심볼 트레이딩 관리 서비스"""

    @property
    def is_enabled(self) -> bool:
        """멀티심볼 모드 활성화 여부"""
        return app_settings.MULTI_SYMBOL_ENABLED

    @property
    def max_symbols(self) -> int:
        """사용자당 최대 심볼 수"""
        return app_settings.MAX_SYMBOLS_PER_USER

    async def get_active_symbols(self, okx_uid: str) -> List[str]:
        """
        사용자의 활성 심볼 목록 조회

        Args:
            okx_uid: 사용자 OKX UID

        Returns:
            활성 심볼 리스트
        """
        async with redis_context(timeout=RedisTimeout.FAST_OPERATION) as redis:
            key = REDIS_KEY_ACTIVE_SYMBOLS.format(okx_uid=okx_uid)
            symbols = await redis.smembers(key)

            result = []
            for symbol in symbols:
                if isinstance(symbol, bytes):
                    symbol = symbol.decode('utf-8')
                result.append(symbol)

            return result

    async def can_add_symbol(self, okx_uid: str, symbol: str) -> Tuple[bool, Optional[str]]:
        """
        새 심볼 추가 가능 여부 확인

        Args:
            okx_uid: 사용자 OKX UID
            symbol: 추가할 심볼

        Returns:
            (추가 가능 여부, 오류 메시지 또는 None)
        """
        if not self.is_enabled:
            # 레거시 모드에서는 항상 허용 (기존 로직 유지)
            return True, None

        active_symbols = await self.get_active_symbols(okx_uid)

        # 이미 활성화된 심볼인지 확인
        if symbol in active_symbols:
            return True, None  # 이미 활성화됨 - OK

        # 최대 심볼 수 확인
        if len(active_symbols) >= self.max_symbols:
            return False, f"MAX_SYMBOLS_REACHED:{','.join(active_symbols)}"

        return True, None

    async def add_symbol(
        self,
        okx_uid: str,
        symbol: str,
        timeframe: str,
        preset_id: Optional[str] = None,
        task_id: Optional[str] = None
    ) -> bool:
        """
        활성 심볼 추가

        Args:
            okx_uid: 사용자 OKX UID
            symbol: 추가할 심볼
            timeframe: 타임프레임
            preset_id: 프리셋 ID (없으면 기본 프리셋)
            task_id: Celery Task ID

        Returns:
            성공 여부

        Raises:
            MaxSymbolsReachedError: 최대 심볼 수 초과
        """
        if not self.is_enabled:
            # 레거시 모드에서는 기존 로직 유지
            return True

        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            active_key = REDIS_KEY_ACTIVE_SYMBOLS.format(okx_uid=okx_uid)

            # 현재 활성 심볼 확인
            active_symbols = await redis.smembers(active_key)
            active_list = [s.decode('utf-8') if isinstance(s, bytes) else s for s in active_symbols]

            # 이미 활성화된 심볼인지 확인
            if symbol in active_list:
                logger.info(f"[{okx_uid}] {symbol} 이미 활성화됨 - 업데이트")
            elif len(active_list) >= self.max_symbols:
                raise MaxSymbolsReachedError(active_list, self.max_symbols)

            # 심볼 추가
            await redis.sadd(active_key, symbol)

            # 심볼별 설정 저장
            await redis.set(
                REDIS_KEY_SYMBOL_TIMEFRAME.format(okx_uid=okx_uid, symbol=symbol),
                timeframe
            )
            await redis.set(
                REDIS_KEY_SYMBOL_STATUS.format(okx_uid=okx_uid, symbol=symbol),
                "running"
            )
            await redis.set(
                REDIS_KEY_SYMBOL_STARTED_AT.format(okx_uid=okx_uid, symbol=symbol),
                str(datetime.now().timestamp())
            )

            if preset_id:
                await redis.set(
                    REDIS_KEY_SYMBOL_PRESET_ID.format(okx_uid=okx_uid, symbol=symbol),
                    preset_id
                )

            if task_id:
                await redis.set(
                    REDIS_KEY_SYMBOL_TASK_ID.format(okx_uid=okx_uid, symbol=symbol),
                    task_id
                )

            logger.info(f"[{okx_uid}] 심볼 추가: {symbol}, timeframe={timeframe}, preset={preset_id}")
            return True

    async def remove_symbol(self, okx_uid: str, symbol: str) -> bool:
        """
        활성 심볼 제거

        Args:
            okx_uid: 사용자 OKX UID
            symbol: 제거할 심볼

        Returns:
            성공 여부
        """
        if not self.is_enabled:
            return True

        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            active_key = REDIS_KEY_ACTIVE_SYMBOLS.format(okx_uid=okx_uid)

            # 심볼 제거
            await redis.srem(active_key, symbol)

            # 심볼별 키 삭제
            keys_to_delete = [
                REDIS_KEY_SYMBOL_TIMEFRAME.format(okx_uid=okx_uid, symbol=symbol),
                REDIS_KEY_SYMBOL_STATUS.format(okx_uid=okx_uid, symbol=symbol),
                REDIS_KEY_SYMBOL_STARTED_AT.format(okx_uid=okx_uid, symbol=symbol),
                REDIS_KEY_SYMBOL_PRESET_ID.format(okx_uid=okx_uid, symbol=symbol),
                REDIS_KEY_SYMBOL_TASK_ID.format(okx_uid=okx_uid, symbol=symbol),
                REDIS_KEY_SYMBOL_TASK_RUNNING.format(okx_uid=okx_uid, symbol=symbol),
            ]

            for key in keys_to_delete:
                try:
                    await redis.delete(key)
                except Exception as e:
                    logger.warning(f"[{okx_uid}] 키 삭제 중 오류 (무시됨): {key}, {e}")

            logger.info(f"[{okx_uid}] 심볼 제거: {symbol}")
            return True

    async def get_symbol_info(self, okx_uid: str, symbol: str) -> Optional[Dict[str, Any]]:
        """
        심볼 상세 정보 조회

        Args:
            okx_uid: 사용자 OKX UID
            symbol: 심볼

        Returns:
            심볼 정보 딕셔너리 또는 None
        """
        async with redis_context(timeout=RedisTimeout.FAST_OPERATION) as redis:
            active_key = REDIS_KEY_ACTIVE_SYMBOLS.format(okx_uid=okx_uid)

            # 활성 심볼인지 확인
            is_active = await redis.sismember(active_key, symbol)
            if not is_active:
                return None

            # 심볼 정보 조회
            timeframe = await redis.get(
                REDIS_KEY_SYMBOL_TIMEFRAME.format(okx_uid=okx_uid, symbol=symbol)
            )
            status = await redis.get(
                REDIS_KEY_SYMBOL_STATUS.format(okx_uid=okx_uid, symbol=symbol)
            )
            preset_id = await redis.get(
                REDIS_KEY_SYMBOL_PRESET_ID.format(okx_uid=okx_uid, symbol=symbol)
            )
            task_id = await redis.get(
                REDIS_KEY_SYMBOL_TASK_ID.format(okx_uid=okx_uid, symbol=symbol)
            )
            started_at = await redis.get(
                REDIS_KEY_SYMBOL_STARTED_AT.format(okx_uid=okx_uid, symbol=symbol)
            )

            def decode(val):
                if isinstance(val, bytes):
                    return val.decode('utf-8')
                return val

            return {
                "symbol": symbol,
                "timeframe": decode(timeframe),
                "status": decode(status),
                "preset_id": decode(preset_id),
                "task_id": decode(task_id),
                "started_at": decode(started_at),
            }

    async def list_symbols_with_info(self, okx_uid: str) -> List[Dict[str, Any]]:
        """
        사용자의 모든 활성 심볼 정보 조회

        Args:
            okx_uid: 사용자 OKX UID

        Returns:
            심볼 정보 리스트
        """
        active_symbols = await self.get_active_symbols(okx_uid)

        result = []
        for symbol in active_symbols:
            info = await self.get_symbol_info(okx_uid, symbol)
            if info:
                result.append(info)

        return result

    async def set_symbol_task_running(
        self,
        okx_uid: str,
        symbol: str,
        running: bool = True,
        expiry: int = 60
    ) -> None:
        """
        심볼별 태스크 실행 상태 설정

        Args:
            okx_uid: 사용자 OKX UID
            symbol: 심볼
            running: 실행 중 여부
            expiry: 만료 시간(초)
        """
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            key = REDIS_KEY_SYMBOL_TASK_RUNNING.format(okx_uid=okx_uid, symbol=symbol)

            if running:
                current_time = datetime.now().timestamp()
                await redis.delete(key)
                await redis.hset(key, mapping={
                    "status": "running",
                    "started_at": str(current_time)
                })
                await redis.expire(key, expiry)
                logger.debug(f"[{okx_uid}] {symbol} 태스크 상태를 'running'으로 설정")
            else:
                await redis.delete(key)
                logger.debug(f"[{okx_uid}] {symbol} 태스크 상태 삭제")

    async def save_symbol_task_id(self, okx_uid: str, symbol: str, task_id: str) -> None:
        """심볼별 Task ID 저장"""
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            await redis.set(
                REDIS_KEY_SYMBOL_TASK_ID.format(okx_uid=okx_uid, symbol=symbol),
                task_id
            )

    async def get_symbol_task_id(self, okx_uid: str, symbol: str) -> Optional[str]:
        """심볼별 Task ID 조회"""
        async with redis_context(timeout=RedisTimeout.FAST_OPERATION) as redis:
            task_id = await redis.get(
                REDIS_KEY_SYMBOL_TASK_ID.format(okx_uid=okx_uid, symbol=symbol)
            )
            if isinstance(task_id, bytes):
                task_id = task_id.decode('utf-8')
            return task_id

    async def stop_all_symbols(self, okx_uid: str) -> List[str]:
        """
        사용자의 모든 심볼 중지

        Args:
            okx_uid: 사용자 OKX UID

        Returns:
            중지된 심볼 리스트
        """
        active_symbols = await self.get_active_symbols(okx_uid)

        stopped_symbols = []
        for symbol in active_symbols:
            await self.remove_symbol(okx_uid, symbol)
            stopped_symbols.append(symbol)

        logger.info(f"[{okx_uid}] 모든 심볼 중지: {stopped_symbols}")
        return stopped_symbols

    # ==================== Signal Bot 모드 메서드 ====================

    async def can_add_signal_bot(
        self,
        okx_uid: str,
        signal_token: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Signal Bot 추가 가능 여부 확인

        Signal Bot 모드에서는:
        - 같은 signal_token이 이미 실행 중인지만 확인
        - 한 종목에 여러 signal_token 동시 실행 가능

        Args:
            okx_uid: 사용자 OKX UID
            signal_token: Signal Bot 토큰

        Returns:
            (추가 가능 여부, 오류 메시지 또는 None)
        """
        async with redis_context(timeout=RedisTimeout.FAST_OPERATION) as redis:
            # 해당 signal_token이 이미 활성화되어 있는지 확인
            active_key = REDIS_KEY_SIGNAL_BOT_ACTIVE.format(okx_uid=okx_uid)
            is_active = await redis.sismember(active_key, signal_token)

            if is_active:
                return False, "SIGNAL_BOT_ALREADY_ACTIVE"

            return True, None

    async def add_signal_bot(
        self,
        okx_uid: str,
        signal_token: str,
        symbol: str,
        timeframe: str,
        task_id: Optional[str] = None
    ) -> bool:
        """
        Signal Bot 등록

        Args:
            okx_uid: 사용자 OKX UID
            signal_token: Signal Bot 토큰
            symbol: 거래 심볼
            timeframe: 타임프레임
            task_id: Celery Task ID

        Returns:
            성공 여부
        """
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            # 활성 signal_bot 목록에 추가
            active_key = REDIS_KEY_SIGNAL_BOT_ACTIVE.format(okx_uid=okx_uid)
            await redis.sadd(active_key, signal_token)

            # Signal Bot 상세 정보 저장
            await redis.set(
                REDIS_KEY_SIGNAL_BOT_SYMBOL.format(okx_uid=okx_uid, signal_token=signal_token),
                symbol
            )
            await redis.set(
                REDIS_KEY_SIGNAL_BOT_TIMEFRAME.format(okx_uid=okx_uid, signal_token=signal_token),
                timeframe
            )
            await redis.set(
                REDIS_KEY_SIGNAL_BOT_STATUS.format(okx_uid=okx_uid, signal_token=signal_token),
                "running"
            )
            await redis.set(
                REDIS_KEY_SIGNAL_BOT_STARTED_AT.format(okx_uid=okx_uid, signal_token=signal_token),
                str(datetime.now().timestamp())
            )

            if task_id:
                await redis.set(
                    REDIS_KEY_SIGNAL_BOT_TASK_ID.format(okx_uid=okx_uid, signal_token=signal_token),
                    task_id
                )

            logger.info(f"[{okx_uid}] Signal Bot 등록: token={signal_token[:8]}..., symbol={symbol}")
            return True

    async def remove_signal_bot(self, okx_uid: str, signal_token: str) -> bool:
        """
        Signal Bot 제거

        Args:
            okx_uid: 사용자 OKX UID
            signal_token: Signal Bot 토큰

        Returns:
            성공 여부
        """
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            # 활성 목록에서 제거
            active_key = REDIS_KEY_SIGNAL_BOT_ACTIVE.format(okx_uid=okx_uid)
            await redis.srem(active_key, signal_token)

            # 관련 키 삭제
            keys_to_delete = [
                REDIS_KEY_SIGNAL_BOT_SYMBOL.format(okx_uid=okx_uid, signal_token=signal_token),
                REDIS_KEY_SIGNAL_BOT_TIMEFRAME.format(okx_uid=okx_uid, signal_token=signal_token),
                REDIS_KEY_SIGNAL_BOT_STATUS.format(okx_uid=okx_uid, signal_token=signal_token),
                REDIS_KEY_SIGNAL_BOT_STARTED_AT.format(okx_uid=okx_uid, signal_token=signal_token),
                REDIS_KEY_SIGNAL_BOT_TASK_ID.format(okx_uid=okx_uid, signal_token=signal_token),
            ]

            for key in keys_to_delete:
                try:
                    await redis.delete(key)
                except Exception as e:
                    logger.warning(f"[{okx_uid}] Signal Bot 키 삭제 중 오류 (무시됨): {key}, {e}")

            logger.info(f"[{okx_uid}] Signal Bot 제거: token={signal_token[:8]}...")
            return True

    async def get_active_signal_bots(self, okx_uid: str) -> List[str]:
        """
        사용자의 활성 Signal Bot 토큰 목록 조회

        Args:
            okx_uid: 사용자 OKX UID

        Returns:
            활성 signal_token 리스트
        """
        async with redis_context(timeout=RedisTimeout.FAST_OPERATION) as redis:
            active_key = REDIS_KEY_SIGNAL_BOT_ACTIVE.format(okx_uid=okx_uid)
            tokens = await redis.smembers(active_key)

            result = []
            for token in tokens:
                if isinstance(token, bytes):
                    token = token.decode('utf-8')
                result.append(token)

            return result

    async def get_signal_bot_info(self, okx_uid: str, signal_token: str) -> Optional[Dict[str, Any]]:
        """
        Signal Bot 상세 정보 조회

        Args:
            okx_uid: 사용자 OKX UID
            signal_token: Signal Bot 토큰

        Returns:
            Signal Bot 정보 딕셔너리 또는 None
        """
        async with redis_context(timeout=RedisTimeout.FAST_OPERATION) as redis:
            active_key = REDIS_KEY_SIGNAL_BOT_ACTIVE.format(okx_uid=okx_uid)

            # 활성 Signal Bot인지 확인
            is_active = await redis.sismember(active_key, signal_token)
            if not is_active:
                return None

            # 정보 조회
            symbol = await redis.get(
                REDIS_KEY_SIGNAL_BOT_SYMBOL.format(okx_uid=okx_uid, signal_token=signal_token)
            )
            timeframe = await redis.get(
                REDIS_KEY_SIGNAL_BOT_TIMEFRAME.format(okx_uid=okx_uid, signal_token=signal_token)
            )
            status = await redis.get(
                REDIS_KEY_SIGNAL_BOT_STATUS.format(okx_uid=okx_uid, signal_token=signal_token)
            )
            task_id = await redis.get(
                REDIS_KEY_SIGNAL_BOT_TASK_ID.format(okx_uid=okx_uid, signal_token=signal_token)
            )
            started_at = await redis.get(
                REDIS_KEY_SIGNAL_BOT_STARTED_AT.format(okx_uid=okx_uid, signal_token=signal_token)
            )

            def decode(val):
                if isinstance(val, bytes):
                    return val.decode('utf-8')
                return val

            return {
                "signal_token": signal_token,
                "symbol": decode(symbol),
                "timeframe": decode(timeframe),
                "status": decode(status),
                "task_id": decode(task_id),
                "started_at": decode(started_at),
                "execution_mode": "signal_bot"
            }

    async def get_signal_bot_task_id(self, okx_uid: str, signal_token: str) -> Optional[str]:
        """Signal Bot의 Task ID 조회"""
        async with redis_context(timeout=RedisTimeout.FAST_OPERATION) as redis:
            task_id = await redis.get(
                REDIS_KEY_SIGNAL_BOT_TASK_ID.format(okx_uid=okx_uid, signal_token=signal_token)
            )
            if isinstance(task_id, bytes):
                task_id = task_id.decode('utf-8')
            return task_id

    async def stop_all_signal_bots(self, okx_uid: str) -> List[str]:
        """
        사용자의 모든 Signal Bot 중지

        Args:
            okx_uid: 사용자 OKX UID

        Returns:
            중지된 signal_token 리스트
        """
        active_tokens = await self.get_active_signal_bots(okx_uid)

        stopped_tokens = []
        for token in active_tokens:
            await self.remove_signal_bot(okx_uid, token)
            stopped_tokens.append(token)

        logger.info(f"[{okx_uid}] 모든 Signal Bot 중지: {len(stopped_tokens)}개")
        return stopped_tokens


# 싱글톤 인스턴스
multi_symbol_service = MultiSymbolService()
