import logging
from HYPERRSI.src.core.database import redis_client

from typing import Optional

logger = logging.getLogger(__name__)

async def get_uid_from_telegramid(telegram_id: str) -> str:
    """
    텔레그램 ID를 OKX UID로 변환합니다.
    
    Args:
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
            return okx_uid
        
        # Redis에 없는 경우 None 반환
        return None
    except Exception as e:
        logger.error(f"텔레그램 ID {telegram_id}를 OKX UID로 변환 중 오류 발생: {str(e)}")
        return None
    
async def get_telegram_id_from_uid(okx_uid: str) -> Optional[str]: # 반환 타입 Optional[str]로 명시
    """
    OKX UID를 텔레그램 ID로 변환합니다.
    1. 주요 방식: user:*:okx_uid 키 스캔 및 값 비교 (기존 로직)
    2. 예비 방식: okx_uid_to_telegram:{okx_uid} 키 직접 조회 (새로 추가된 로직)
    3. 추가 방식: Supabase 데이터베이스에서 조회 (마지막 시도)

    Args:
        okx_uid: OKX UID

    Returns:
        str: 텔레그램 ID 또는 실패 시 None
    """
    if not okx_uid: # 입력값이 없는 경우 처리
        logger.warning("get_telegram_id_from_uid called with empty okx_uid.")
        return None

    okx_uid_str = str(okx_uid) # 문자열로 확실하게 변환

    # --- 1. 주요 방식 (기존 로직: 키 스캔) ---
    logger.info(f"Attempting to find Telegram ID for OKX UID {okx_uid_str} using primary method (scan user:*:okx_uid)")
    try:
        pattern = "user:*:okx_uid"
        keys = await redis_client.keys(pattern)
        logger.debug(f"Scan found {len(keys)} keys matching pattern '{pattern}'")

        valid_telegram_ids = []

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
                    if user_id.isdigit() and 6 <= len(user_id) < 15: # 일반적인 텔레그램 ID 길이 범위 고려
                        #logger.info(f"Primary method found match: OKX UID {okx_uid_str} -> Telegram ID {user_id} from key {key_str}")
                        # 최근 활동 시간 확인 로직 (선택적) - 필요하다면 유지
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
            valid_telegram_ids.sort(key=lambda x: x["last_activity"], reverse=True)
            found_telegram_id = valid_telegram_ids[0]["telegram_id"]
            #logger.info(f"Primary method succeeded. Returning most recent Telegram ID: {found_telegram_id} for OKX UID {okx_uid_str}")
            return found_telegram_id

        #logger.info(f"Primary method (scan) did not find a matching Telegram ID for OKX UID: {okx_uid_str}. Proceeding to fallback.")

    except Exception as e:
        logger.error(f"Error during primary method (scan) for OKX UID {okx_uid_str}: {str(e)}")
        logger.info("Proceeding to fallback method due to error in primary method.")
        # 기본 방식에서 에러가 나도 예비 방식으로 넘어갑니다.

    # --- 2. 예비 방식 (새로운 로직: 직접 키 조회) ---
    fallback_key = f"okx_uid_to_telegram:{okx_uid_str}"
    logger.info(f"Attempting fallback method: checking direct key '{fallback_key}'")
    try:
        telegram_id_bytes = await redis_client.get(fallback_key)
        if telegram_id_bytes:
            telegram_id = telegram_id_bytes.decode() if isinstance(telegram_id_bytes, bytes) else str(telegram_id_bytes)
            # 조회된 텔레그램 ID가 유효한지 간단히 확인 (숫자)
            if telegram_id.isdigit():
                 logger.info(f"Fallback method succeeded. Found Telegram ID: {telegram_id} for OKX UID {okx_uid_str} using key {fallback_key}")
                 return telegram_id
            else:
                 logger.warning(f"Value '{telegram_id}' found in fallback key '{fallback_key}' is not a valid Telegram ID format.")
                 # 유효하지 않은 값이 저장되어 있다면 제거 (선택적)
                 await redis_client.delete(fallback_key)
        else:
            logger.info(f"Fallback key '{fallback_key}' not found or has no value.")

    except Exception as e:
        logger.error(f"Error during fallback method for OKX UID {okx_uid_str} using key {fallback_key}: {str(e)}")
        # 예비 방식 중 에러 발생해도 Supabase 방식으로 넘어감

    # --- 3. Supabase에서 조회 (마지막 시도) ---
    logger.info(f"Attempting to find telegram_id from Supabase for OKX UID {okx_uid_str}")
    try:
        # Supabase 연결 정보
        SUPABASE_URL = "https://fsobvtcxqndccnekasqw.supabase.co"
        SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZzb2J2dGN4cW5kY2NuZWthc3F3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTczMDY0MTIyNywiZXhwIjoyMDQ2MjE3MjI3fQ.Pni49lbWfdQBt7azJE_I_-1rM5jjp7Ri1L44I3F_hNQ"
        
        import httpx
        
        # Supabase API 헤더 설정
        headers = {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        
        # 쿼리 URL 구성 - okx_uid로 검색하고 telegram_linked가 true인 사용자 조회
        url = f"{SUPABASE_URL}/rest/v1/users?okx_uid=eq.{okx_uid_str}&telegram_linked=eq.true&select=*"
        logger.info(f"Querying Supabase: {url}")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            
            # 응답 처리
            if response.status_code == 200 and response.json():
                users = response.json()
                logger.info(f"Supabase returned {len(users)} users for okx_uid={okx_uid_str}")
                
                # 첫 번째 일치하는 사용자의 telegram_id 가져오기
                if users and 'telegram_id' in users[0] and users[0]['telegram_id']:
                    supabase_telegram_id = str(users[0]['telegram_id'])
                    
                    # telegram_id가 유효한지 확인 (숫자형태, 적절한 길이)
                    if supabase_telegram_id.isdigit() and 6 <= len(supabase_telegram_id) < 15:
                        logger.info(f"Found telegram_id={supabase_telegram_id} in Supabase for okx_uid={okx_uid_str}")
                        
                        # Redis에 결과 캐싱 - 다음 조회 시 빠르게 접근하기 위함
                        cache_key = f"okx_uid_to_telegram:{okx_uid_str}"
                        await redis_client.set(cache_key, supabase_telegram_id)
                        logger.info(f"Cached telegram_id in Redis key: {cache_key}")
                        
                        return supabase_telegram_id
                    else:
                        logger.warning(f"Found invalid telegram_id format in Supabase: {supabase_telegram_id}")
            else:
                logger.warning(f"No valid user found in Supabase for okx_uid={okx_uid_str}. Status: {response.status_code}")
                if response.status_code != 200:
                    logger.error(f"Supabase API error: {response.text}")

    except Exception as e:
        logger.error(f"Error querying Supabase for okx_uid={okx_uid_str}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    # 모든 방법으로 찾지 못한 경우
    logger.warning(f"Could not find telegram_id for okx_uid={okx_uid_str} using any method")
    return None


async def get_identifier(identifier: str) -> str:
    """
    입력된 식별자가 텔레그램 ID인지 OKX UID인지 판단하여 OKX UID를 반환합니다.
    텔레그램 ID가 입력되면 OKX UID로 변환하고, OKX UID가 입력되면 그대로 반환합니다.
    
    Args:
        identifier: 텔레그램 ID 또는 OKX UID
        
    Returns:
        str: OKX UID 또는 입력된 식별자
    """
    # 11자리 이하는 텔레그램 ID로 간주
    if len(str(identifier)) <= 11 and str(identifier).isdigit():
        okx_uid = await get_uid_from_telegramid(str(identifier))
        if okx_uid:
            return okx_uid
    
    # OKX UID를 찾지 못하거나 12자리 이상은 그대로 반환
    return str(identifier)


# 테스트를 위한 메인 함수
import asyncio
import sys
import os
import logging

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

async def test_get_telegram_id():
    """
    Supabase 연동을 테스트하기 위한 함수
    """
    logger.info("===== Supabase 연동 테스트 시작 =====")
    
    # 테스트할 OKX UID (실제 존재하는 UID로 변경해주세요)
    test_okx_uid = "587662504768345929"  # 예시 OKX UID
    
    logger.info(f"테스트 OKX UID: {test_okx_uid}")
    
    # 1. 먼저 Redis 캐시를 비워서 Supabase 호출이 확실히 일어나도록 함
    cache_key = f"okx_uid_to_telegram:{test_okx_uid}"
    await redis_client.delete(cache_key)
    logger.info(f"Redis 캐시 키 {cache_key} 삭제됨")
    
    # 2. 함수 호출 테스트
    logger.info("get_telegram_id_from_uid 함수 호출 중...")
    telegram_id = await get_telegram_id_from_uid(test_okx_uid)
    
    # 3. 결과 출력
    if telegram_id:
        logger.info(f"성공! OKX UID {test_okx_uid}에 대한 텔레그램 ID: {telegram_id}")
        
        # 캐시가 잘 설정되었는지 확인
        cached_value = await redis_client.get(cache_key)
        if cached_value:
            cached_telegram_id = cached_value.decode() if isinstance(cached_value, bytes) else str(cached_value)
            logger.info(f"Redis 캐시 확인: {cache_key} = {cached_telegram_id}")
            logger.info(f"캐싱 성공? {cached_telegram_id == telegram_id}")
        else:
            logger.warning(f"Redis 캐시 키 {cache_key}가 존재하지 않음")
    else:
        logger.error(f"실패: OKX UID {test_okx_uid}에 대한 텔레그램 ID를 찾을 수 없음")
    
    logger.info("===== Supabase 연동 테스트 완료 =====")
    
    return telegram_id

# 이 파일이 직접 실행될 때만 테스트 함수 실행
if __name__ == "__main__":
    try:
        # src 디렉토리를 Python 경로에 추가 (필요한 경우)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        src_dir = os.path.abspath(os.path.join(current_dir, '../..'))
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)
        
        # 테스트 실행
        asyncio.run(test_get_telegram_id())
    except Exception as e:
        logger.error(f"테스트 실행 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
