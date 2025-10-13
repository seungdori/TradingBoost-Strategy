"""
통합 User ID 변환 유틸리티

텔레그램 ID와 OKX UID 간의 변환을 위한 중앙화된 함수들을 제공합니다.
Redis 클라이언트는 내부적으로 자동으로 관리됩니다.
"""
import logging
from typing import Any, Optional

from shared.database.redis_helper import get_redis_client

logger = logging.getLogger(__name__)


async def get_okx_uid_from_telegram(telegram_id: str) -> Optional[str]:
    """
    텔레그램 ID를 OKX UID로 변환합니다.

    Args:
        telegram_id: 텔레그램 ID

    Returns:
        str: OKX UID 또는 실패 시 None

    Example:
        >>> okx_uid = await get_okx_uid_from_telegram("1234567890")
        >>> print(okx_uid)
        "518796558012178692"
    """
    try:
        redis = await get_redis_client()
        okx_uid = await redis.get(f"user:{telegram_id}:okx_uid")

        if okx_uid:
            # bytes 타입인 경우에만 decode 수행
            if isinstance(okx_uid, bytes):
                return okx_uid.decode('utf-8')
            return str(okx_uid)

        # Redis에 없는 경우 None 반환
        logger.debug(f"OKX UID not found for telegram_id: {telegram_id}")
        return None

    except Exception as e:
        logger.error(f"Error converting telegram_id {telegram_id} to OKX UID: {str(e)}")
        return None


async def get_telegram_id_from_okx_uid(okx_uid: str, timescale_service: Any = None) -> Optional[str]:
    """
    OKX UID를 텔레그램 ID로 변환합니다.

    3단계 조회 전략:
    1. Redis 패턴 스캔으로 매핑 조회 (주요 방식)
    2. 직접 역방향 키 조회 (예비 방식)
    3. TimescaleDB 조회 (마지막 시도, optional)

    Args:
        okx_uid: OKX UID
        timescale_service: TimescaleDB 서비스 (선택사항)

    Returns:
        str: 텔레그램 ID 또는 실패 시 None

    Example:
        >>> telegram_id = await get_telegram_id_from_okx_uid("518796558012178692")
        >>> print(telegram_id)
        "1234567890"
    """
    if not okx_uid:
        logger.warning("get_telegram_id_from_okx_uid called with empty okx_uid")
        return None

    okx_uid_str = str(okx_uid)
    redis = await get_redis_client()

    # --- 1. 주요 방식: Redis 패턴 스캔으로 user:*:okx_uid 키 조회 ---
    try:
        pattern = "user:*:okx_uid"
        keys = await redis.keys(pattern)

        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else str(key)
            stored_uid = await redis.get(key)

            if not stored_uid:
                continue

            stored_uid_str = stored_uid.decode() if isinstance(stored_uid, bytes) else str(stored_uid)

            if stored_uid_str == okx_uid_str:
                parts = key_str.split(':')
                if len(parts) == 3 and parts[0] == 'user' and parts[2] == 'okx_uid':
                    telegram_id = parts[1]
                    # 텔레그램 ID 유효성 검사
                    if telegram_id.isdigit() and 6 <= len(telegram_id) < 15:
                        logger.debug(f"Found telegram_id {telegram_id} for okx_uid {okx_uid_str}")
                        return telegram_id

    except Exception as e:
        logger.error(f"Error during primary method (scan) for OKX UID {okx_uid_str}: {str(e)}")

    # --- 2. 예비 방식: 직접 역방향 키 조회 ---
    try:
        fallback_key = f"okx_uid_to_telegram:{okx_uid_str}"
        telegram_id_bytes = await redis.get(fallback_key)

        if telegram_id_bytes:
            telegram_id = telegram_id_bytes.decode() if isinstance(telegram_id_bytes, bytes) else str(telegram_id_bytes)
            if telegram_id.isdigit() and 6 <= len(telegram_id) < 15:
                logger.debug(f"Fallback method succeeded. Found telegram_id: {telegram_id}")
                return telegram_id
            else:
                # 잘못된 데이터 정리
                await redis.delete(fallback_key)

    except Exception as e:
        logger.error(f"Error during fallback method for OKX UID {okx_uid_str}: {str(e)}")

    # --- 3. TimescaleDB 조회 (마지막 시도) ---
    if timescale_service:
        try:
            record = await timescale_service.fetch_user(okx_uid_str)
            if record:
                telegram_id = None

                # 여러 필드에서 telegram_id 찾기
                if record.api and record.api.get("telegram_id"):
                    telegram_id = str(record.api["telegram_id"])
                elif record.user.get("telegram_id"):
                    telegram_id = str(record.user["telegram_id"])
                elif record.user.get("telegram_userid"):
                    telegram_id = str(record.user["telegram_userid"])

                if telegram_id and telegram_id.isdigit() and 6 <= len(telegram_id) < 15:
                    logger.info(f"Found telegram_id={telegram_id} in TimescaleDB for okx_uid={okx_uid_str}")
                    # Redis에 캐싱
                    await redis.set(f"okx_uid_to_telegram:{okx_uid_str}", telegram_id)
                    return telegram_id

        except Exception as e:
            logger.error(f"Error querying TimescaleDB for okx_uid={okx_uid_str}: {str(e)}")

    # 모든 방법 실패
    logger.warning(f"Could not find telegram_id for okx_uid={okx_uid_str}")
    return None


async def store_user_id_mapping(telegram_id: str, okx_uid: str) -> None:
    """
    텔레그램 ID와 OKX UID의 매핑을 Redis에 저장합니다.
    양방향 조회를 위해 두 가지 키를 모두 저장합니다.

    Args:
        telegram_id: 텔레그램 ID
        okx_uid: OKX UID

    Example:
        >>> await store_user_id_mapping("1234567890", "518796558012178692")
    """
    try:
        redis = await get_redis_client()

        # 텔레그램 ID → OKX UID 매핑
        await redis.set(f"user:{telegram_id}:okx_uid", okx_uid)

        # OKX UID → 텔레그램 ID 역방향 매핑
        await redis.set(f"okx_uid_to_telegram:{okx_uid}", telegram_id)

        logger.debug(f"Stored mapping: telegram_id={telegram_id} <-> okx_uid={okx_uid}")

    except Exception as e:
        logger.error(f"Error storing user ID mapping: {str(e)}")
        raise


async def resolve_user_identifier(identifier: str) -> str:
    """
    입력된 식별자가 텔레그램 ID인지 OKX UID인지 자동 판단하여 OKX UID를 반환합니다.

    - 11자리 이하 숫자: 텔레그램 ID로 간주하고 OKX UID로 변환 시도
    - 12자리 이상 숫자: OKX UID로 간주하고 그대로 반환

    Args:
        identifier: 텔레그램 ID 또는 OKX UID

    Returns:
        str: OKX UID

    Example:
        >>> # 텔레그램 ID 입력 → OKX UID 반환
        >>> okx_uid = await resolve_user_identifier("1234567890")
        >>> print(okx_uid)
        "518796558012178692"

        >>> # OKX UID 입력 → 그대로 반환
        >>> okx_uid = await resolve_user_identifier("518796558012178692")
        >>> print(okx_uid)
        "518796558012178692"
    """
    identifier_str = str(identifier)

    # 11자리 이하이고 숫자인 경우 텔레그램 ID로 간주
    if len(identifier_str) <= 11 and identifier_str.isdigit():
        okx_uid = await get_okx_uid_from_telegram(identifier_str)
        if okx_uid:
            logger.debug(f"Resolved telegram_id {identifier_str} to okx_uid {okx_uid}")
            return okx_uid

    # OKX UID를 찾지 못하거나 12자리 이상인 경우 그대로 반환
    return identifier_str


async def is_telegram_id(identifier: str) -> bool:
    """
    주어진 식별자가 텔레그램 ID 형식인지 확인합니다.

    Args:
        identifier: 확인할 식별자

    Returns:
        bool: 텔레그램 ID 형식이면 True, 아니면 False

    Example:
        >>> is_telegram_id("1234567890")
        True
        >>> is_telegram_id("518796558012178692")
        False
    """
    identifier_str = str(identifier)
    return len(identifier_str) <= 11 and identifier_str.isdigit()


async def is_okx_uid(identifier: str) -> bool:
    """
    주어진 식별자가 OKX UID 형식인지 확인합니다.

    Args:
        identifier: 확인할 식별자

    Returns:
        bool: OKX UID 형식이면 True, 아니면 False

    Example:
        >>> is_okx_uid("518796558012178692")
        True
        >>> is_okx_uid("1234567890")
        False
    """
    identifier_str = str(identifier)
    return len(identifier_str) > 11 and identifier_str.isdigit()
