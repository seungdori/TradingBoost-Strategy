"""
사용자 ID 변환 유틸리티

텔레그램 ID와 OKX UID 간 변환 기능 제공
"""
import logging
from typing import Optional, Any, Dict, List, cast

logger = logging.getLogger(__name__)


async def get_uid_from_telegramid(redis_client: Any, telegram_id: str) -> Optional[str]:
    """
    텔레그램 ID를 OKX UID로 변환합니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        telegram_id: 텔레그램 ID

    Returns:
        str: OKX UID 또는 실패 시 None
    """
    try:
        # Redis에서 OKX UID 조회
        okx_uid = await redis_client.get(f"user:{telegram_id}:okx_uid")
        if okx_uid:
            # bytes 타입인 경우에만 decode 수행
            if isinstance(okx_uid, bytes):
                return okx_uid.decode('utf-8')
            return str(okx_uid)

        # Redis에 없는 경우 None 반환
        return None
    except Exception as e:
        logger.error(f"텔레그램 ID {telegram_id}를 OKX UID로 변환 중 오류 발생: {str(e)}")
        return None


async def get_telegram_id_from_uid(redis_client: Any, okx_uid: str, timescale_service: Any = None) -> Optional[str]:
    """
    OKX UID를 텔레그램 ID로 변환합니다.
    1. 주요 방식: user:*:okx_uid 키 스캔 및 값 비교 (기존 로직)
    2. 예비 방식: okx_uid_to_telegram:{okx_uid} 키 직접 조회 (새로 추가된 로직)
    3. 추가 방식: TimescaleDB에서 조회 (마지막 시도, optional)

    Args:
        redis_client: Redis 클라이언트 인스턴스
        okx_uid: OKX UID
        timescale_service: TimescaleDB 서비스 (선택사항)

    Returns:
        str: 텔레그램 ID 또는 실패 시 None
    """
    if not okx_uid:
        logger.warning("get_telegram_id_from_uid called with empty okx_uid.")
        return None

    okx_uid_str = str(okx_uid)

    # --- 1. 주요 방식 (기존 로직: 키 스캔) ---
    logger.info(f"Attempting to find Telegram ID for OKX UID {okx_uid_str} using primary method (scan user:*:okx_uid)")
    try:
        pattern = "user:*:okx_uid"
        keys = await redis_client.keys(pattern)
        logger.debug(f"Scan found {len(keys)} keys matching pattern '{pattern}'")

        valid_telegram_ids: List[Dict[str, Any]] = []

        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else str(key)
            stored_uid = await redis_client.get(key)

            if not stored_uid:
                logger.warning(f"Key {key_str} exists but has no value. Skipping.")
                continue

            stored_uid_str = stored_uid.decode() if isinstance(stored_uid, bytes) else str(stored_uid)

            logger.debug(f"Comparing input UID '{okx_uid_str}' with stored UID '{stored_uid_str}' from key '{key_str}'")
            if stored_uid_str == okx_uid_str:
                parts = key_str.split(':')
                if len(parts) == 3 and parts[0] == 'user' and parts[2] == 'okx_uid':
                    user_id = parts[1]
                    # 텔레그램 ID 유효성 검사 강화 (숫자, 적절한 길이)
                    if user_id.isdigit() and 6 <= len(user_id) < 15:
                        # 최근 활동 시간 확인 로직 (선택적)
                        last_activity = 0
                        try:
                            stats_key = f"user:{user_id}:stats"
                            stats = await redis_client.hgetall(stats_key)
                            if stats and (b'last_trade_date' in stats or 'last_trade_date' in stats):
                                last_trade_bytes = stats.get(b'last_trade_date') or stats.get('last_trade_date')
                                if last_trade_bytes:
                                    last_trade_str = last_trade_bytes.decode() if isinstance(last_trade_bytes, bytes) else str(last_trade_bytes)
                                    if last_trade_str.isdigit():
                                        last_activity = int(last_trade_str)
                                    else:
                                        logger.warning(f"Invalid last_trade_date format '{last_trade_str}' in {stats_key}")
                        except Exception as e:
                            logger.error(f"Error fetching stats for {user_id} from {stats_key}: {str(e)}")

                        valid_telegram_ids.append({
                            "telegram_id": user_id,
                            "last_activity": last_activity
                        })
                else:
                    logger.warning(f"Key '{key_str}' matched UID but has unexpected format.")

        if valid_telegram_ids:
            valid_telegram_ids.sort(key=lambda x: cast(int, x["last_activity"]), reverse=True)
            found_telegram_id = str(valid_telegram_ids[0]["telegram_id"])
            return found_telegram_id

    except Exception as e:
        logger.error(f"Error during primary method (scan) for OKX UID {okx_uid_str}: {str(e)}")
        logger.info("Proceeding to fallback method due to error in primary method.")

    # --- 2. 예비 방식 (새로운 로직: 직접 키 조회) ---
    fallback_key = f"okx_uid_to_telegram:{okx_uid_str}"
    logger.info(f"Attempting fallback method: checking direct key '{fallback_key}'")
    try:
        telegram_id_bytes = await redis_client.get(fallback_key)
        if telegram_id_bytes:
            telegram_id = telegram_id_bytes.decode() if isinstance(telegram_id_bytes, bytes) else str(telegram_id_bytes)
            if telegram_id.isdigit():
                logger.info(f"Fallback method succeeded. Found Telegram ID: {telegram_id} for OKX UID {okx_uid_str}")
                return telegram_id
            else:
                logger.warning(f"Value '{telegram_id}' found in fallback key '{fallback_key}' is not a valid Telegram ID format.")
                await redis_client.delete(fallback_key)
        else:
            logger.info(f"Fallback key '{fallback_key}' not found or has no value.")

    except Exception as e:
        logger.error(f"Error during fallback method for OKX UID {okx_uid_str}: {str(e)}")

    # --- 3. TimescaleDB에서 조회 (마지막 시도, optional) ---
    if timescale_service:
        logger.info(f"Attempting to find telegram_id from TimescaleDB for OKX UID {okx_uid_str}")
        try:
            record = await timescale_service.fetch_user(okx_uid_str)
            if record:
                timescale_telegram_id = None

                if record.api and record.api.get("telegram_id"):
                    timescale_telegram_id = str(record.api["telegram_id"])
                elif record.user.get("telegram_id"):
                    timescale_telegram_id = str(record.user["telegram_id"])
                elif record.user.get("telegram_userid"):
                    timescale_telegram_id = str(record.user["telegram_userid"])

                if timescale_telegram_id and timescale_telegram_id.isdigit() and 6 <= len(timescale_telegram_id) < 15:
                    logger.info(f"Found telegram_id={timescale_telegram_id} in TimescaleDB for okx_uid={okx_uid_str}")
                    # Cache in Redis
                    cache_key = f"okx_uid_to_telegram:{okx_uid_str}"
                    await redis_client.set(cache_key, timescale_telegram_id)
                    logger.info(f"Cached telegram_id in Redis key: {cache_key}")
                    return timescale_telegram_id
                else:
                    logger.warning(f"No valid telegram_id found in TimescaleDB for okx_uid={okx_uid_str}")
            else:
                logger.warning(f"TimescaleDB returned no user for okx_uid={okx_uid_str}")

        except Exception as e:
            logger.error(f"Error querying TimescaleDB for okx_uid={okx_uid_str}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

    # 모든 방법으로 찾지 못한 경우
    logger.warning(f"Could not find telegram_id for okx_uid={okx_uid_str} using any method")
    return None


async def get_identifier(redis_client: Any, identifier: str) -> str:
    """
    입력된 식별자가 텔레그램 ID인지 OKX UID인지 판단하여 OKX UID를 반환합니다.
    텔레그램 ID가 입력되면 OKX UID로 변환하고, OKX UID가 입력되면 그대로 반환합니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        identifier: 텔레그램 ID 또는 OKX UID

    Returns:
        str: OKX UID 또는 입력된 식별자
    """
    # 11자리 이하는 텔레그램 ID로 간주
    if len(str(identifier)) <= 11 and str(identifier).isdigit():
        okx_uid = await get_uid_from_telegramid(redis_client, str(identifier))
        if okx_uid:
            return okx_uid

    # OKX UID를 찾지 못하거나 12자리 이상은 그대로 반환
    return str(identifier)
