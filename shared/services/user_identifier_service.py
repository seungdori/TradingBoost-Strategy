"""
User Identifier Service with Redis caching.

이 서비스는 user_id, telegram_id, okx_uid 간의 변환을 제공합니다.
Redis 캐싱을 사용하여 빠른 조회를 지원하며, 캐시 미스 시 데이터베이스에서 조회합니다.
"""

import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.models import UserIdentifierMapping
from shared.logging import get_logger

logger = get_logger(__name__)

# Redis 캐시 키 패턴
CACHE_KEY_USER_ID = "user_identifier:user_id:{user_id}"
CACHE_KEY_TELEGRAM_ID = "user_identifier:telegram_id:{telegram_id}"
CACHE_KEY_OKX_UID = "user_identifier:okx_uid:{okx_uid}"

# 캐시 TTL (초): 1시간
CACHE_TTL = 3600


class UserIdentifierService:
    """
    사용자 식별자 변환 서비스.

    Redis 캐싱과 데이터베이스 조회를 결합하여 빠르고 신뢰성 있는 식별자 변환을 제공합니다.
    """

    def __init__(self, db_session: AsyncSession, redis_client: Any):
        """
        Initialize UserIdentifierService.

        Args:
            db_session: SQLAlchemy async session
            redis_client: Redis client instance
        """
        self.db = db_session
        self.redis = redis_client

    async def get_telegram_id_by_user_id(self, user_id: str) -> Optional[int]:
        """
        user_id로 telegram_id를 조회합니다.

        Args:
            user_id: 사용자 식별자

        Returns:
            Optional[int]: telegram_id 또는 None
        """
        # 1. Redis 캐시 확인
        cache_key = CACHE_KEY_USER_ID.format(user_id=user_id)
        cached = await self.redis.get(cache_key)

        if cached:
            try:
                data = json.loads(cached)
                logger.debug(f"Cache hit for user_id={user_id}: telegram_id={data['telegram_id']}")
                return data["telegram_id"]
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"캐시 데이터 파싱 실패: {e}")
                await self.redis.delete(cache_key)

        # 2. 데이터베이스 조회
        stmt = select(UserIdentifierMapping).where(
            UserIdentifierMapping.user_id == user_id,
            UserIdentifierMapping.is_active == 1
        )
        result = await self.db.execute(stmt)
        mapping = result.scalar_one_or_none()

        if not mapping:
            logger.debug(f"user_id={user_id}에 대한 매핑을 찾을 수 없습니다.")
            return None

        # 3. Redis에 캐시
        await self._cache_mapping(mapping)

        return mapping.telegram_id

    async def get_user_id_by_telegram_id(self, telegram_id: int) -> Optional[str]:
        """
        telegram_id로 user_id를 조회합니다.

        Args:
            telegram_id: 텔레그램 사용자 ID

        Returns:
            Optional[str]: user_id 또는 None
        """
        # 1. Redis 캐시 확인
        cache_key = CACHE_KEY_TELEGRAM_ID.format(telegram_id=telegram_id)
        cached = await self.redis.get(cache_key)

        if cached:
            try:
                data = json.loads(cached)
                logger.debug(f"Cache hit for telegram_id={telegram_id}: user_id={data['user_id']}")
                return data["user_id"]
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"캐시 데이터 파싱 실패: {e}")
                await self.redis.delete(cache_key)

        # 2. 데이터베이스 조회
        stmt = select(UserIdentifierMapping).where(
            UserIdentifierMapping.telegram_id == telegram_id,
            UserIdentifierMapping.is_active == 1
        )
        result = await self.db.execute(stmt)
        mapping = result.scalar_one_or_none()

        if not mapping:
            logger.debug(f"telegram_id={telegram_id}에 대한 매핑을 찾을 수 없습니다.")
            return None

        # 3. Redis에 캐시
        await self._cache_mapping(mapping)

        return mapping.user_id

    async def get_telegram_id_by_okx_uid(self, okx_uid: str) -> Optional[int]:
        """
        okx_uid로 telegram_id를 조회합니다.

        Args:
            okx_uid: OKX UID

        Returns:
            Optional[int]: telegram_id 또는 None
        """
        # 1. Redis 캐시 확인
        cache_key = CACHE_KEY_OKX_UID.format(okx_uid=okx_uid)
        cached = await self.redis.get(cache_key)

        if cached:
            try:
                data = json.loads(cached)
                logger.debug(f"Cache hit for okx_uid={okx_uid}: telegram_id={data['telegram_id']}")
                return data["telegram_id"]
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"캐시 데이터 파싱 실패: {e}")
                await self.redis.delete(cache_key)

        # 2. 데이터베이스 조회
        stmt = select(UserIdentifierMapping).where(
            UserIdentifierMapping.okx_uid == okx_uid,
            UserIdentifierMapping.is_active == 1
        )
        result = await self.db.execute(stmt)
        mapping = result.scalar_one_or_none()

        if not mapping:
            logger.debug(f"okx_uid={okx_uid}에 대한 매핑을 찾을 수 없습니다.")
            return None

        # 3. Redis에 캐시
        await self._cache_mapping(mapping)

        return mapping.telegram_id

    async def create_mapping(
        self,
        user_id: str,
        telegram_id: int,
        okx_uid: Optional[str] = None
    ) -> UserIdentifierMapping:
        """
        새로운 사용자 식별자 매핑을 생성합니다.

        Args:
            user_id: 사용자 식별자
            telegram_id: 텔레그램 ID
            okx_uid: OKX UID (선택적)

        Returns:
            UserIdentifierMapping: 생성된 매핑

        Raises:
            IntegrityError: 중복된 식별자가 있는 경우
        """
        mapping = UserIdentifierMapping(
            user_id=user_id,
            telegram_id=telegram_id,
            okx_uid=okx_uid,
            is_active=1
        )

        self.db.add(mapping)
        await self.db.commit()
        await self.db.refresh(mapping)

        # Redis에 캐시
        await self._cache_mapping(mapping)

        logger.info(f"새로운 매핑 생성: user_id={user_id}, telegram_id={telegram_id}, okx_uid={okx_uid}")

        return mapping

    async def update_okx_uid(self, user_id: str, okx_uid: str) -> bool:
        """
        기존 매핑의 okx_uid를 업데이트합니다.

        Args:
            user_id: 사용자 식별자
            okx_uid: 새로운 OKX UID

        Returns:
            bool: 성공 여부
        """
        stmt = select(UserIdentifierMapping).where(
            UserIdentifierMapping.user_id == user_id,
            UserIdentifierMapping.is_active == 1
        )
        result = await self.db.execute(stmt)
        mapping = result.scalar_one_or_none()

        if not mapping:
            logger.warning(f"user_id={user_id}에 대한 매핑을 찾을 수 없습니다.")
            return False

        # 기존 OKX UID 캐시 삭제
        if mapping.okx_uid:
            old_cache_key = CACHE_KEY_OKX_UID.format(okx_uid=mapping.okx_uid)
            await self.redis.delete(old_cache_key)

        # OKX UID 업데이트
        mapping.okx_uid = okx_uid
        await self.db.commit()
        await self.db.refresh(mapping)

        # Redis에 새로운 캐시
        await self._cache_mapping(mapping)

        logger.info(f"OKX UID 업데이트: user_id={user_id}, new_okx_uid={okx_uid}")

        return True

    async def deactivate_mapping(self, user_id: str) -> bool:
        """
        매핑을 비활성화합니다.

        Args:
            user_id: 사용자 식별자

        Returns:
            bool: 성공 여부
        """
        stmt = select(UserIdentifierMapping).where(
            UserIdentifierMapping.user_id == user_id
        )
        result = await self.db.execute(stmt)
        mapping = result.scalar_one_or_none()

        if not mapping:
            logger.warning(f"user_id={user_id}에 대한 매핑을 찾을 수 없습니다.")
            return False

        # 비활성화
        mapping.is_active = 0
        await self.db.commit()

        # Redis 캐시 삭제
        await self._invalidate_cache(mapping)

        logger.info(f"매핑 비활성화: user_id={user_id}")

        return True

    async def _cache_mapping(self, mapping: UserIdentifierMapping) -> None:
        """
        매핑 데이터를 Redis에 캐싱합니다.

        Args:
            mapping: 캐싱할 매핑 객체
        """
        data = {
            "user_id": mapping.user_id,
            "telegram_id": mapping.telegram_id,
            "okx_uid": mapping.okx_uid
        }
        data_json = json.dumps(data)

        # 3개의 키로 캐싱 (user_id, telegram_id, okx_uid)
        await self.redis.setex(
            CACHE_KEY_USER_ID.format(user_id=mapping.user_id),
            CACHE_TTL,
            data_json
        )

        await self.redis.setex(
            CACHE_KEY_TELEGRAM_ID.format(telegram_id=mapping.telegram_id),
            CACHE_TTL,
            data_json
        )

        if mapping.okx_uid:
            await self.redis.setex(
                CACHE_KEY_OKX_UID.format(okx_uid=mapping.okx_uid),
                CACHE_TTL,
                data_json
            )

    async def _invalidate_cache(self, mapping: UserIdentifierMapping) -> None:
        """
        매핑 데이터의 Redis 캐시를 무효화합니다.

        Args:
            mapping: 캐시를 무효화할 매핑 객체
        """
        await self.redis.delete(CACHE_KEY_USER_ID.format(user_id=mapping.user_id))
        await self.redis.delete(CACHE_KEY_TELEGRAM_ID.format(telegram_id=mapping.telegram_id))

        if mapping.okx_uid:
            await self.redis.delete(CACHE_KEY_OKX_UID.format(okx_uid=mapping.okx_uid))
