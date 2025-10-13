import asyncio
import datetime as dt
import json
import logging
import os
import time
import traceback
from typing import Optional

import dotenv
import httpx
import telegram
from telegram.ext.filters import TEXT

from HYPERRSI.src.services.timescale_service import TimescaleUserService
from shared.database.redis_helper import get_redis_client
from shared.helpers.user_id_converter import get_telegram_id_from_uid

# Dynamic redis_client access

# 순환 참조 제거
# from HYPERRSI.src.trading.monitoring import get_okx_uid_from_telegram_id
dotenv.load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ERROR_TELEGRAM_ID = os.getenv("ERROR_TELEGRAM_ID")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api")

# 메시지 큐 관련 키 형식
MESSAGE_QUEUE_KEY = "telegram:message_queue:{okx_uid}"  # 사용자별 메시지가 저장되는 Redis List 키
MESSAGE_PROCESSING_FLAG = "telegram:processing_flag:{okx_uid}"  # 메시지 처리 상태를 나타내는 키
# 메시지는 Redis List에 저장됨: LRANGE telegram:message_queue:{okx_uid} 0 -1 명령으로 조회 가능

# 로그 관련 키 형식
LOG_SET_KEY = "telegram:logs:{user_id}"  # 사용자별 로그가 저장되는 Redis Sorted Set 키
LOG_CHANNEL_KEY = "telegram:log_channel:{user_id}"  # 로그 이벤트가 발행되는 Redis Pub/Sub 채널
# 로그는 Redis Sorted Set에 저장됨: ZRANGE telegram:logs:{user_id} 0 -1 명령으로 조회 가능
# Redis-CLI 또는 Redis 관리 도구를 통해 해당 키로 로그 검색 가능

# 텔레그램 ID를 OKX UID로 변환하는 함수 직접 구현
async def get_okx_uid_from_telegram_id(telegram_id: str) -> str | None:
    """
    텔레그램 ID를 OKX UID로 변환합니다.

    Args:
        telegram_id: 텔레그램 ID

    Returns:
        str | None: OKX UID or None if not found
    """
    try:
        redis = await get_redis_client()
        # Redis에서 OKX UID 조회
        okx_uid = await redis.get(f"user:{telegram_id}:okx_uid")
        if okx_uid:
            # bytes 타입인 경우에만 decode 수행
            if isinstance(okx_uid, bytes):
                return okx_uid.decode('utf-8')
            return str(okx_uid) if okx_uid else None

        # Redis에 없으면 API 호출
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE_URL}/user/telegram/{telegram_id}/okx")
            if response.status_code == 200:
                data = response.json()
                okx_uid = data.get("okx_uid")
                if okx_uid:
                    # Redis에 저장
                    await redis.set(f"user:{telegram_id}:okx_uid", okx_uid)
                    return str(okx_uid)

        logger.error(f"텔레그램 ID {telegram_id}에 대한 OKX UID를 찾을 수 없습니다.")
        return None
    except Exception as e:
        logger.error(f"텔레그램 ID {telegram_id}를 OKX UID로 변환 중 오류 발생: {str(e)}")
        return None

# 메시지 카테고리 분류 함수
def determine_message_category(message: str) -> str:
    """메시지 내용을 기반으로 카테고리를 결정합니다."""
    if not isinstance(message, str):
        return "general"

    lower_message = message.lower()

    if "트레이딩을 시작합니다" in message or "start trading" in lower_message:
        return "bot_start"
    if "트레이딩이 중지되었습니다" in message or "trading stopped" in lower_message:
        return "bot_stop"
    # entry, close, tp, sl 키워드는 더 구체적인 패턴 확인 필요
    # 예시: '진입', 'entry', 'position opened'
    if any(keyword in lower_message for keyword in ["진입", "entry", "position opened"]):
        return "entry"
    # 예시: '청산', 'close', 'position closed'
    if any(keyword in lower_message for keyword in ["청산", "close", "position closed"]):
        return "close"
    # 예시: 'tp', 'take profit'
    if any(keyword in lower_message for keyword in ["익절", "tp", "take profit"]):
        return "tp"
    # 예시: 'sl', 'stop loss'
    if any(keyword in lower_message for keyword in ["손절", "sl", "stop loss"]):
        return "sl"

    return "general"

# 로그 기록 및 발행 함수
async def log_telegram_event(
    user_id: str | None = None,
    okx_uid: str | None = None,  # okx_uid 파라미터 추가
    event_type: str = "send", # 'send', 'edit' 등
    status: str = "unknown", # 'success', 'failed'
    content: str | None = None,
    category: str = "general", # 카테고리
    strategy_type: str = "HyperRSI", # 전략 타입 추가 (기본값 설정)
    message_id: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """
    텔레그램 메시지 관련 이벤트를 Redis에 로깅하고 Pub/Sub으로 발행합니다.
    이중 인덱싱: telegram_id와 okx_uid 모두로 접근 가능

    로그는 Redis Sorted Set에 저장되며, 다음 명령으로 조회할 수 있습니다:
    - telegram_id 기준: ZRANGE telegram:logs:{user_id} 0 -1
    - okx_uid 기준: ZRANGE telegram:logs:by_okx_uid:{okx_uid} 0 -1

    또한 Redis Pub/Sub 채널을 통해 실시간으로 발행됩니다.
    """
    try:
        redis = await get_redis_client()

        # okx_uid가 제공되었지만 user_id가 없으면 조회
        if okx_uid and not user_id:
            user_id_result = await get_telegram_id_from_uid(get_redis_client(), okx_uid, TimescaleUserService)
            user_id = str(user_id_result) if user_id_result else None

        # user_id가 있지만 okx_uid가 없으면 조회
        if user_id and not okx_uid:
            okx_uid = await get_okx_uid_from_telegram_id(user_id)

        # 둘 다 없으면 에러
        if not user_id:
            logger.error(f"Cannot log event: no user_id provided or found for okx_uid={okx_uid}")
            return

        # 로그 엔트리 생성 (okx_uid 포함)
        log_entry = {
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "user_id": user_id,
            "okx_uid": okx_uid,  # okx_uid 추가
            "event_type": event_type,
            "status": status,
            "category": category,
            "strategy_type": strategy_type, # 전략 타입 포함
            "content": content,
        }
        if message_id:
            log_entry["message_id"] = message_id
        if error_message:
            log_entry["error_message"] = error_message

        log_score = time.time() # Sorted Set의 score로 사용될 타임스탬프
        log_data = json.dumps(log_entry)

        # 1. telegram_id 기준 로그 저장 (기존 방식 - 호환성 유지)
        log_set_key = LOG_SET_KEY.format(user_id=user_id)
        await redis.zadd(log_set_key, {log_data: log_score})

        # 2. okx_uid 기준 로그 저장 (새로운 방식)
        if okx_uid:
            okx_log_set_key = f"telegram:logs:by_okx_uid:{okx_uid}"
            await redis.zadd(okx_log_set_key, {log_data: log_score})

        # 3. 통합 인덱스에도 추가 (날짜별 인덱스)
        date_key = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        index_key = f"telegram:logs:index:date:{date_key}"
        log_id = f"{okx_uid or 'unknown'}_{int(log_score * 1000000)}"
        await redis.sadd(index_key, log_id)

        # 4. Redis Pub/Sub 채널에 로그 발행 (두 채널 모두)
        # telegram_id 기준 채널 (기존)
        log_channel = LOG_CHANNEL_KEY.format(user_id=user_id)
        await redis.publish(log_channel, log_data)

        # okx_uid 기준 채널 (새로운)
        if okx_uid:
            okx_log_channel = f"telegram:log_channel:by_okx_uid:{okx_uid}"
            await redis.publish(okx_log_channel, log_data)

        # 5. 통계 업데이트
        if okx_uid:
            stats_key = f"telegram:stats:{okx_uid}"
            await redis.hincrby(stats_key, "total", 1)
            await redis.hincrby(stats_key, status, 1)
            await redis.hincrby(stats_key, f"category:{category}", 1)

        logger.info(f"Logged event - telegram_id: {user_id}, okx_uid: {okx_uid}, event_type: {event_type}, status: {status}, category: {category}, strategy: {strategy_type}")

    except Exception as e:
        logger.error(f"Failed to log telegram event for user {user_id}: {e}")
        traceback.print_exc()

class TelegramFilter(logging.Filter):
    def filter(self, record):
        return not (record.getMessage().startswith('HTTP Request: POST https://api.telegram.org') and 'HTTP/1.1 200 OK' in record.getMessage())

script_path = os.path.abspath(__file__)
script_dir = os.path.dirname(script_path)
os.chdir(script_dir)
# print("Current Working Directory:", os.getcwd())

# 로깅 설정
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# httpx 로거에 필터 추가
httpx_logger = logging.getLogger('httpx')
httpx_logger.addFilter(TelegramFilter())

# 메시지를 레디스 큐에 추가하는 함수
async def enqueue_telegram_message(message_data):
    """
    텔레그램 메시지 데이터를 레디스 큐에 추가합니다
    
    message_data는 다음 형식의 딕셔너리여야 합니다:
    {
        "event_type": "text" | "markup" | "edit",
        "message": 메시지 내용,
        "user_id": 유저 ID,
        "strategy_type": "HyperRSI" (Optional, 기본값 설정됨),
        ... 기타 필요한 파라미터
    }
    
    메시지는 Redis List(telegram:message_queue:{okx_uid})에 저장되며, 다음 명령으로 조회할 수 있습니다:
    - Redis-CLI: LRANGE telegram:message_queue:{okx_uid} 0 -1
    - Python: await redis.lrange(f"telegram:message_queue:{okx_uid}", 0, -1)
    
    처리 상태는 telegram:processing_flag:{okx_uid} 키로 확인할 수 있습니다.
    """
    try:
        redis = await get_redis_client()
        okx_uid = message_data["okx_uid"]
        logger.info(f"[enqueue_telegram_message] 메시지 큐에 추가 시도 - okx_uid: {okx_uid}")
        queue_key = MESSAGE_QUEUE_KEY.format(okx_uid=okx_uid)
        
        # 메시지 내용 기반 카테고리 결정
        content = message_data.get("message", "")
        message_data["category"] = determine_message_category(content)
        
        # 전략 타입 설정 (없으면 기본값 사용)
        if "strategy_type" not in message_data:
            message_data["strategy_type"] = "HyperRSI"
        
        # 타임스탬프 추가
        message_data["timestamp"] = time.time()
        
        # 레디스 큐에 메시지 추가 (JSON 문자열로 변환)
        await redis.rpush(queue_key, json.dumps(message_data))
        
        # 메시지 처리 플래그 확인 및 설정
        processing_flag = MESSAGE_PROCESSING_FLAG.format(okx_uid=okx_uid)
        is_processing = await redis.get(processing_flag)
        
        # 처리 중이 아니면 메시지 처리 시작
        if not is_processing:
            await redis.set(processing_flag, "1", ex=300)  # 5분 타임아웃 설정
            asyncio.create_task(process_telegram_messages(okx_uid))
        
        return True
    except Exception as e:
        logger.error(f"메시지 큐 추가 실패: {str(e)}")
        traceback.print_exc()
        return False

# 큐에서 메시지를 가져와 순차적으로 전송하는 함수
async def process_telegram_messages(okx_uid):
    """레디스 큐에서 메시지를 가져와 순차적으로 텔레그램으로 전송합니다"""
    redis = await get_redis_client()
    queue_key = MESSAGE_QUEUE_KEY.format(okx_uid=okx_uid)
    processing_flag = MESSAGE_PROCESSING_FLAG.format(okx_uid=okx_uid)

    try:
        while True:
            # 큐에서 메시지 가져오기 (블로킹 방식, 1초 타임아웃)
            message_data = await redis.blpop(queue_key, 1)

            # 큐가 비어있으면 처리 종료
            if not message_data:
                await redis.delete(processing_flag)
                break
                
            # 메시지 데이터 파싱
            _, message_json = message_data
            message_obj = json.loads(message_json)
            
            # 메시지 타입에 따라 적절한 함수 호출
            message_type = message_obj.get("event_type", "text")
            category = message_obj.get("category", "general")
  
            if message_type == "text":
                # 일반 텍스트 메시지
                await send_telegram_message_direct(
                    message=message_obj["message"],
                    okx_uid=message_obj["okx_uid"],
                    debug=message_obj.get("debug", False),
                    category=category, # 카테고리 전달
                    error=message_obj.get("error", False)
                )
            elif message_type == "markup":
                # 마크업이 있는 메시지
                await send_telegram_message_with_markup_direct(
                    okx_uid=message_obj["okx_uid"],
                    text=message_obj["message"],
                    reply_markup=message_obj.get("reply_markup"),
                    category=category # 카테고리 전달
                )
            elif message_type == "edit":
                # 메시지 수정
                await edit_telegram_message_text_direct(
                    okx_uid=message_obj["okx_uid"],
                    message_id=message_obj["message_id"],
                    text=message_obj["message"],
                    reply_markup=message_obj.get("reply_markup"),
                    category=category # 카테고리 전달
                )
            
            # 속도 제한을 위한 짧은 대기
            await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"메시지 처리 중 오류 발생: {str(e)}")
        traceback.print_exc()
        await redis.delete(processing_flag)

# 직접 텔레그램으로 메시지를 보내는 함수들 (내부용)

async def send_telegram_message_with_markup_direct(okx_uid, text, reply_markup=None, category="general"):
    """
    인라인 키보드 등 reply_markup을 함께 전송하는 함수 (내부용).
    성공/실패 시 로그를 기록합니다.
    """
    response_msg = None
    status = "failed"
    error_msg = None
    message_id = None
    try:
        telegram_id = await get_telegram_id_from_uid(get_redis_client(), okx_uid, TimescaleUserService)
    except Exception as e:
        traceback.print_exc()
        return
    try:
        async with semaphore:
            max_retries = 3
            retry_delay = 1
            bot = telegram.Bot(TELEGRAM_BOT_TOKEN)

            for attempt in range(max_retries):
                try:
                    response_msg = await bot.send_message(
                        chat_id=telegram_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode='HTML' # HTML 파싱 추가
                    )
                    status = "success"
                    message_id = response_msg.message_id if response_msg else None
                    break # 메시지 전송 성공 시 반복 탈출
                except telegram.error.TelegramError as e:
                    error_msg = str(e)
                    if 'Flood control exceeded' in error_msg:
                        logger.warning(f"Flood control exceeded for chat_id {telegram_id}. Stopping retries.")
                        break # Flood control 발생 시 재시도 중단
                    logger.error(f"[send_with_markup] Failed on attempt {attempt + 1} for chat_id {telegram_id}: {e}. Retrying after {retry_delay} sec...")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"[send_with_markup] Unexpected error on attempt {attempt + 1} for chat_id {telegram_id}: {e}. Retrying after {retry_delay} sec...")
                    traceback.print_exc()
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)

            if status != "success" and not error_msg:
                error_msg = f"Failed to send message after {max_retries} attempts."

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[send_with_markup] Exception occurred for okx_uid {okx_uid}: {e}")
        traceback.print_exc()
    finally:
        # 로그 기록
        await log_telegram_event(
            okx_uid=okx_uid,
            event_type="send_markup",
            status=status,
            content=text,
            category=category, # 로그에 카테고리 기록
            message_id=message_id,
            error_message=error_msg
        )
        return response_msg

semaphore = asyncio.Semaphore(1)
async def send_telegram_message_direct(message, okx_uid, debug=False, category="general", error=False):
    """텔레그램으로 직접 메시지를 전송합니다 (내부용). 성공/실패 시 로그를 기록합니다."""
    og_okx_uid = okx_uid
    telegram_id_to_send = None
    status = "failed"
    error_msg = None
    message_id = None
    final_message = message

    try:
        if error and ERROR_TELEGRAM_ID:
            telegram_id_to_send = ERROR_TELEGRAM_ID
            final_message = f"🚨 [ERROR : {og_okx_uid}] {message}"
        elif debug:
            telegram_id_to_send = 1709556958
            final_message = f"[DEBUG : {og_okx_uid}] {message}"
        else:
            telegram_id_to_send = await get_telegram_id_from_uid(get_redis_client(), okx_uid, TimescaleUserService)
            logger.info(f"OKX UID {okx_uid} -> Telegram ID {telegram_id_to_send}")
        if telegram_id_to_send:
            async with semaphore:
                max_retries = 3
                retry_delay = 1
                token = TELEGRAM_BOT_TOKEN
                bot = telegram.Bot(token)

                for attempt in range(max_retries):
                    try:
                        response = await bot.send_message(
                            chat_id=str(telegram_id_to_send),
                            text=final_message,
                            parse_mode='HTML' # HTML 파싱 추가
                        )
                        status = "success"
                        message_id = response.message_id if response else None
                        break # 성공 시 루프 탈출
                    except telegram.error.TelegramError as e:
                        error_msg = str(e)
                        if 'Flood control exceeded' in error_msg:
                            logger.warning(f"Flood control exceeded for chat_id(telegram_id) {telegram_id_to_send}. Stopping retries.")
                            break
                        logger.error(f"[send_direct] Failed on attempt {attempt + 1} for chat_id(telegram_id) {telegram_id_to_send}: {e}. Retrying after {retry_delay} sec...")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                    except Exception as e:
                        error_msg = str(e)
                        logger.error(f"[send_direct] Unexpected error on attempt {attempt + 1} for chat_id(telegram_id) {telegram_id_to_send}: {e}. Retrying after {retry_delay} sec...")
                        traceback.print_exc()
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)

                if status != "success" and not error_msg:
                    error_msg = f"Failed to send message after {max_retries} attempts."
        else:
             if not error_msg: # telegram_id_to_send가 None이고 특정 에러 메시지가 없는 경우
                 error_msg = f"Invalid okx_uid or failed to convert OKX UID: {og_okx_uid}"
                 logger.error(error_msg)


    except Exception as e:
        error_msg = str(e)
        logger.error(f"[send_direct] Exception occurred for okx_uid {og_okx_uid}: {e}")
        traceback.print_exc()
    finally:
         # 로그 기록 - telegram_id와 okx_uid 둘 다 전달
        await log_telegram_event(
            user_id=telegram_id_to_send,  # telegram_id
            okx_uid=og_okx_uid,  # okx_uid
            event_type="send_direct",
            status=status,
            content=final_message, # 디버그 메시지가 포함될 수 있음
            category=category, # 로그에 카테고리 기록
            message_id=message_id,
            error_message=error_msg
        )

async def edit_telegram_message_text_direct(okx_uid, message_id, text, reply_markup=None, category="general"):
    """
    이미 존재하는 메시지를 수정(edit)하는 함수 (내부용).
    성공/실패 시 로그를 기록합니다.
    """
    response_msg = None
    status = "failed"
    error_msg = None
    edited_message_id = None # 수정 성공 시 message_id가 반환될 수 있음 (문서 확인 필요)
    telegram_id = await get_telegram_id_from_uid(get_redis_client(), okx_uid, TimescaleUserService)
    try:
        async with semaphore:
            max_retries = 3
            retry_delay = 1
            bot = telegram.Bot(TELEGRAM_BOT_TOKEN)

            for attempt in range(max_retries):
                try:
                    # edit_message_text는 수정된 메시지 객체 또는 True를 반환할 수 있음
                    response = await bot.edit_message_text(
                        chat_id=str(telegram_id),
                        message_id=message_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode='HTML' # HTML 파싱 추가
                    )
                    status = "success"
                    # response가 메시지 객체인 경우 message_id 추출 시도
                    if isinstance(response, telegram.Message):
                        edited_message_id = response.message_id
                    else: # True가 반환된 경우, 원본 message_id 사용
                        edited_message_id = message_id
                    break # 성공 시 루프 탈출
                except telegram.error.TelegramError as e:
                    error_msg = str(e)
                    if 'Flood control exceeded' in error_msg:
                         logger.warning(f"Flood control exceeded during edit for okx_uid {okx_uid}, message_id {message_id}. Stopping retries.")
                         break
                    # 메시지가 수정되지 않았다는 에러는 실패로 간주하지 않을 수 있음 (정책 결정 필요)
                    if 'message is not modified' in error_msg.lower():
                         logger.info(f"Message not modified for okx_uid {okx_uid}, message_id {message_id}. Treating as success.")
                         status = "success" # 수정 내용 없을 시 성공으로 처리
                         edited_message_id = message_id
                         error_msg = None # 에러 메시지 초기화
                         break
                    logger.error(f"[edit_message] Failed on attempt {attempt + 1} for okx_uid {okx_uid}, message_id {message_id}: {e}. Retrying after {retry_delay} sec...")
                    if attempt < max_retries - 1:
                         await asyncio.sleep(retry_delay)
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"[edit_message] Unexpected error on attempt {attempt + 1} for okx_uid {okx_uid}, message_id {message_id}: {e}. Retrying after {retry_delay} sec...")
                    traceback.print_exc()
                    if attempt < max_retries - 1:
                         await asyncio.sleep(retry_delay)

            if status != "success" and not error_msg:
                error_msg = f"Failed to edit message after {max_retries} attempts."

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[edit_message] Exception occurred for okx_uid {okx_uid}, message_id {message_id}: {e}")
        traceback.print_exc()
    finally:
        # 로그 기록
        await log_telegram_event(
            okx_uid=okx_uid,
            event_type="edit",
            status=status,
            content=text,
            category=category, # 로그에 카테고리 기록
            message_id=edited_message_id if edited_message_id else message_id, # 성공 시 반환된 ID 사용, 없으면 원본 ID
            error_message=error_msg
        )
        # edit_message_text는 성공 시 True 또는 Message 객체를 반환하므로, 원본 함수 시그니처에 맞게 None 또는 성공 정보를 반환해야 할 수 있음
        # 여기서는 명시적 반환값 변경 없이 로그만 기록
        return edited_message_id is not None and status == "success" # 성공 여부 boolean 반환 (호출 측에서 필요시 사용)


# 사용자 API 함수 - 외부에서 호출할 함수들

async def send_telegram_message_with_reply_markup(okx_uid, text, reply_markup=None):
    """
    인라인 키보드 등 reply_markup을 함께 전송하는 함수.
    큐에 추가하여 순서대로 처리되도록 합니다.
    """
    message_data = {
        "event_type": "markup",
        "okx_uid": okx_uid,
        "message": text,
        "reply_markup": reply_markup
    }
    return await enqueue_telegram_message(message_data)

async def send_telegram_message(message, okx_uid, debug=False, error=False):
    """
    텔레그램 메시지를 큐에 추가합니다 (외부 API용)
    error=True인 경우 ERROR_TELEGRAM_ID로 메시지를 전송합니다.
    """
    logger.info(f"[send_telegram_message] 호출됨 - okx_uid: {okx_uid}, debug: {debug}, error: {error}")

    # 만약 okx_uid가 텔레그램 ID인 경우 (13자리 미만) OKX UID로 변환 시도
    if len(str(okx_uid)) < 13:
        logger.info(f"[send_telegram_message] 텔레그램 ID {okx_uid} 감지, OKX UID로 변환 시도")
        converted_okx_uid = await get_okx_uid_from_telegram_id(str(okx_uid))
        if converted_okx_uid:
            logger.info(f"[send_telegram_message] 변환 성공: {okx_uid} -> {converted_okx_uid}")
            okx_uid = converted_okx_uid
        else:
            logger.warning(f"[send_telegram_message] 텔레그램 ID {okx_uid}를 OKX UID로 변환 실패, 그대로 사용")
    
    message_data = {
        "event_type": "text",
        "okx_uid": okx_uid,
        "message": message,
        "debug": debug,
        "error": error
    }
    return await enqueue_telegram_message(message_data)

async def edit_telegram_message_text(okx_uid, message_id, text, reply_markup=None):
    """
    이미 존재하는 메시지를 수정(edit)하는 함수.
    큐에 추가하여 순서대로 처리되도록 합니다.
    """
    message_data = {
        "event_type": "edit",
        "okx_uid": okx_uid,
        "message_id": message_id,
        "message": text,
        "reply_markup": reply_markup
    }
    return await enqueue_telegram_message(message_data)

# 함수를 테스트하기 위한 비동기 메인 함수
async def main():
    try:
        # 여러 메시지를 빠르게 전송해서 순서 보장 테스트
        await send_telegram_message("테스트 메시지 1", okx_uid=587662504768345929)
        await send_telegram_message("테스트 메시지 2", okx_uid=587662504768345929)
        await send_telegram_message("테스트 메시지 3", okx_uid=587662504768345929)
        
        # 처리 완료를 위해 잠시 대기
        await asyncio.sleep(5)
    except Exception as e:
        traceback.print_exc()
        print(f"오류 발생: {e}")

# 이벤트 루프 실행
if __name__ == "__main__":
    asyncio.run(main())