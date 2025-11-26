# src/services/preset_service.py
"""
Preset Service - 트레이딩 프리셋 관리 서비스

프리셋 CRUD 및 즉시 적용 기능을 제공합니다.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from shared.database.redis_patterns import redis_context, RedisTimeout
from shared.logging import get_logger

from HYPERRSI.src.core.models.preset import (
    TradingPreset,
    PresetSummary,
    CreatePresetRequest,
    UpdatePresetRequest,
)
from shared.constants.default_settings import DEFAULT_PARAMS_SETTINGS

logger = get_logger(__name__)

# Redis 키 패턴
REDIS_KEY_PRESET = "preset:{okx_uid}:{preset_id}"
REDIS_KEY_PRESET_LIST = "preset:{okx_uid}:list"
REDIS_KEY_PRESET_DEFAULT = "preset:{okx_uid}:default"
REDIS_KEY_ACTIVE_SYMBOLS = "user:{okx_uid}:active_symbols"
REDIS_KEY_SYMBOL_PRESET = "user:{okx_uid}:symbol:{symbol}:preset_id"


class PresetService:
    """프리셋 관리 서비스"""

    async def create_preset(
        self,
        okx_uid: str,
        request: CreatePresetRequest,
    ) -> TradingPreset:
        """
        새 프리셋 생성

        Args:
            okx_uid: 사용자 OKX UID
            request: 프리셋 생성 요청

        Returns:
            생성된 TradingPreset
        """
        # 기존 settings와 병합
        settings = {**DEFAULT_PARAMS_SETTINGS}
        if request.settings:
            settings.update(request.settings)

        # 프리셋 생성
        preset = TradingPreset.from_settings(
            owner_id=okx_uid,
            name=request.name,
            settings=settings,
            is_default=request.is_default,
        )

        if request.description:
            preset.description = request.description

        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            # 프리셋 저장
            preset_key = REDIS_KEY_PRESET.format(
                okx_uid=okx_uid, preset_id=preset.preset_id
            )
            await redis.set(preset_key, json.dumps(preset.to_redis_dict()))

            # 프리셋 목록에 추가
            list_key = REDIS_KEY_PRESET_LIST.format(okx_uid=okx_uid)
            await redis.sadd(list_key, preset.preset_id)

            # 기본 프리셋으로 설정 (요청된 경우)
            if request.is_default:
                await self._set_default_preset(okx_uid, preset.preset_id, redis)

            logger.info(f"[{okx_uid}] 프리셋 생성 완료: {preset.name} ({preset.preset_id})")

        return preset

    async def get_preset(
        self, okx_uid: str, preset_id: str
    ) -> Optional[TradingPreset]:
        """
        프리셋 조회

        Args:
            okx_uid: 사용자 OKX UID
            preset_id: 프리셋 ID

        Returns:
            TradingPreset 또는 None
        """
        async with redis_context(timeout=RedisTimeout.FAST_OPERATION) as redis:
            preset_key = REDIS_KEY_PRESET.format(okx_uid=okx_uid, preset_id=preset_id)
            data = await redis.get(preset_key)

            if not data:
                return None

            preset_data = json.loads(data)
            return TradingPreset.from_redis_dict(preset_data)

    async def list_presets(self, okx_uid: str) -> List[PresetSummary]:
        """
        사용자의 모든 프리셋 목록 조회

        Args:
            okx_uid: 사용자 OKX UID

        Returns:
            PresetSummary 리스트
        """
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            list_key = REDIS_KEY_PRESET_LIST.format(okx_uid=okx_uid)
            preset_ids = await redis.smembers(list_key)

            if not preset_ids:
                return []

            summaries = []
            for preset_id in preset_ids:
                preset = await self.get_preset(okx_uid, preset_id)
                if preset:
                    summaries.append(
                        PresetSummary(
                            preset_id=preset.preset_id,
                            name=preset.name,
                            description=preset.description,
                            is_default=preset.is_default,
                            created_at=preset.created_at,
                            updated_at=preset.updated_at,
                            leverage=preset.leverage,
                            direction=preset.direction,
                            pyramiding_limit=preset.pyramiding_limit,
                        )
                    )

            # 생성일 기준 정렬 (최신순)
            summaries.sort(key=lambda x: x.created_at, reverse=True)
            return summaries

    async def update_preset(
        self,
        okx_uid: str,
        preset_id: str,
        request: UpdatePresetRequest,
    ) -> Optional[TradingPreset]:
        """
        프리셋 수정 및 즉시 적용

        Args:
            okx_uid: 사용자 OKX UID
            preset_id: 프리셋 ID
            request: 수정 요청

        Returns:
            수정된 TradingPreset 또는 None
        """
        preset = await self.get_preset(okx_uid, preset_id)
        if not preset:
            return None

        # 필드 업데이트
        if request.name is not None:
            preset.name = request.name
        if request.description is not None:
            preset.description = request.description
        if request.settings:
            # 설정 부분 업데이트
            current_settings = preset.to_settings_dict()
            current_settings.update(request.settings)

            # 새 설정으로 프리셋 재생성 (validation 포함)
            updated_preset = TradingPreset.from_settings(
                owner_id=preset.owner_id,
                name=preset.name,
                settings=current_settings,
                is_default=preset.is_default,
            )
            updated_preset.preset_id = preset.preset_id
            updated_preset.description = preset.description
            updated_preset.created_at = preset.created_at
            preset = updated_preset

        # updated_at 갱신
        preset.updated_at = datetime.utcnow()

        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            # 프리셋 저장
            preset_key = REDIS_KEY_PRESET.format(okx_uid=okx_uid, preset_id=preset_id)
            await redis.set(preset_key, json.dumps(preset.to_redis_dict()))

            # 즉시 적용: 이 프리셋을 사용 중인 심볼들에 알림
            await self._notify_preset_update(okx_uid, preset_id, redis)

            logger.info(f"[{okx_uid}] 프리셋 수정 완료: {preset.name} ({preset_id})")

        return preset

    async def delete_preset(self, okx_uid: str, preset_id: str) -> bool:
        """
        프리셋 삭제

        Args:
            okx_uid: 사용자 OKX UID
            preset_id: 프리셋 ID

        Returns:
            삭제 성공 여부
        """
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            preset_key = REDIS_KEY_PRESET.format(okx_uid=okx_uid, preset_id=preset_id)

            # 존재 여부 확인
            exists = await redis.exists(preset_key)
            if not exists:
                return False

            # 사용 중인 심볼이 있는지 확인
            active_symbols = await self._get_symbols_using_preset(
                okx_uid, preset_id, redis
            )
            if active_symbols:
                logger.warning(
                    f"[{okx_uid}] 프리셋 삭제 불가 - 사용 중인 심볼: {active_symbols}"
                )
                raise ValueError(
                    f"프리셋이 다음 심볼에서 사용 중입니다: {', '.join(active_symbols)}"
                )

            # 기본 프리셋인지 확인
            default_key = REDIS_KEY_PRESET_DEFAULT.format(okx_uid=okx_uid)
            default_preset_id = await redis.get(default_key)
            if default_preset_id == preset_id:
                await redis.delete(default_key)

            # 프리셋 삭제
            await redis.delete(preset_key)

            # 목록에서 제거
            list_key = REDIS_KEY_PRESET_LIST.format(okx_uid=okx_uid)
            await redis.srem(list_key, preset_id)

            logger.info(f"[{okx_uid}] 프리셋 삭제 완료: {preset_id}")
            return True

    async def get_default_preset(self, okx_uid: str) -> Optional[TradingPreset]:
        """
        기본 프리셋 조회

        Args:
            okx_uid: 사용자 OKX UID

        Returns:
            기본 TradingPreset 또는 None
        """
        async with redis_context(timeout=RedisTimeout.FAST_OPERATION) as redis:
            default_key = REDIS_KEY_PRESET_DEFAULT.format(okx_uid=okx_uid)
            preset_id = await redis.get(default_key)

            if not preset_id:
                return None

            return await self.get_preset(okx_uid, preset_id)

    async def set_default_preset(self, okx_uid: str, preset_id: str) -> bool:
        """
        기본 프리셋 설정

        Args:
            okx_uid: 사용자 OKX UID
            preset_id: 기본으로 설정할 프리셋 ID

        Returns:
            설정 성공 여부
        """
        # 프리셋 존재 확인
        preset = await self.get_preset(okx_uid, preset_id)
        if not preset:
            return False

        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            await self._set_default_preset(okx_uid, preset_id, redis)

        return True

    async def create_default_from_settings(
        self, okx_uid: str, settings: Optional[Dict[str, Any]] = None
    ) -> TradingPreset:
        """
        기존 settings에서 기본 프리셋 생성 (마이그레이션용)

        Args:
            okx_uid: 사용자 OKX UID
            settings: 기존 트레이딩 설정 (없으면 기본값 사용)

        Returns:
            생성된 TradingPreset
        """
        request = CreatePresetRequest(
            name="Default",
            description="자동 생성된 기본 프리셋",
            settings=settings,
            is_default=True,
        )
        return await self.create_preset(okx_uid, request)

    async def get_preset_settings(
        self, okx_uid: str, preset_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        프리셋의 트레이딩 설정만 조회 (메타데이터 제외)

        Args:
            okx_uid: 사용자 OKX UID
            preset_id: 프리셋 ID

        Returns:
            트레이딩 설정 딕셔너리 또는 None
        """
        preset = await self.get_preset(okx_uid, preset_id)
        if not preset:
            return None
        return preset.to_settings_dict()

    # ===== Private Helper Methods =====

    async def _set_default_preset(self, okx_uid: str, preset_id: str, redis) -> None:
        """기본 프리셋 설정 (내부용)"""
        # 기존 기본 프리셋의 is_default 해제
        old_default = await redis.get(REDIS_KEY_PRESET_DEFAULT.format(okx_uid=okx_uid))
        if old_default and old_default != preset_id:
            old_preset = await self.get_preset(okx_uid, old_default)
            if old_preset:
                old_preset.is_default = False
                old_key = REDIS_KEY_PRESET.format(
                    okx_uid=okx_uid, preset_id=old_default
                )
                await redis.set(old_key, json.dumps(old_preset.to_redis_dict()))

        # 새 기본 프리셋 설정
        default_key = REDIS_KEY_PRESET_DEFAULT.format(okx_uid=okx_uid)
        await redis.set(default_key, preset_id)

        # 프리셋의 is_default 플래그 업데이트
        preset = await self.get_preset(okx_uid, preset_id)
        if preset:
            preset.is_default = True
            preset_key = REDIS_KEY_PRESET.format(okx_uid=okx_uid, preset_id=preset_id)
            await redis.set(preset_key, json.dumps(preset.to_redis_dict()))

        logger.info(f"[{okx_uid}] 기본 프리셋 설정: {preset_id}")

    async def _get_symbols_using_preset(
        self, okx_uid: str, preset_id: str, redis
    ) -> List[str]:
        """특정 프리셋을 사용 중인 심볼 목록 조회"""
        active_symbols_key = REDIS_KEY_ACTIVE_SYMBOLS.format(okx_uid=okx_uid)
        active_symbols = await redis.smembers(active_symbols_key)

        using_symbols = []
        for symbol in active_symbols:
            symbol_preset_key = REDIS_KEY_SYMBOL_PRESET.format(
                okx_uid=okx_uid, symbol=symbol
            )
            symbol_preset_id = await redis.get(symbol_preset_key)
            if symbol_preset_id == preset_id:
                using_symbols.append(symbol)

        return using_symbols

    async def _notify_preset_update(
        self, okx_uid: str, preset_id: str, redis
    ) -> None:
        """
        프리셋 수정 시 사용 중인 심볼들에 알림 (즉시 적용)

        Redis PUB/SUB를 통해 실행 중인 Task에 설정 변경을 알립니다.
        """
        using_symbols = await self._get_symbols_using_preset(okx_uid, preset_id, redis)

        for symbol in using_symbols:
            channel = f"preset:update:{okx_uid}:{symbol}"
            message = json.dumps({"preset_id": preset_id, "action": "reload"})
            await redis.publish(channel, message)
            logger.info(f"[{okx_uid}] 프리셋 업데이트 알림 전송: {symbol}")


# 싱글톤 인스턴스
preset_service = PresetService()
