import asyncio
import logging
import telegram
from telegram.ext.filters import TEXT
import os
import traceback
import json
import time
import redis.asyncio as redis
from HYPERRSI.src.core.database import redis_client
import requests
import aiohttp


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ORDER_BACKEND = os.getenv("ORDER_BACKEND")

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

# 메시지 큐 이름 형식
MESSAGE_QUEUE_KEY = "telegram:message_queue:{okx_uid}"
MESSAGE_PROCESSING_LOCK = "telegram:processing_lock:{okx_uid}"
MESSAGE_PROCESSING_FLAG = "telegram:processing_flag:{okx_uid}"

async def get_telegram_id(identifier: str) -> int:
    """
    식별자가 okx_uid인지 telegram_id인지 확인하고 적절한 telegram_id를 반환합니다.
    
    Args:
        identifier: 확인할 식별자 (okx_uid 또는 telegram_id)
        
    Returns:
        int: 텔레그램 ID
    """
    if not identifier:
        return None
        
    # 11글자 이하면 telegram_id로 간주
    if len(str(identifier)) <= 11:
        print("TELEGRAM ID 반환")
        return int(identifier)
    
    # 12글자 이상이면 okx_uid로 간주하고 텔레그램 ID 조회
    try:
        api_url = f"/api/user/okx/{identifier}/telegram"
        full_url = f"{ORDER_BACKEND}{api_url}"
        logger.info(f"OKX UID {identifier}에 대한 텔레그램 ID 조회 시도: {full_url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(full_url) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"API 응답 데이터: {data}")
                    
                    # primary_telegram_id 먼저 확인
                    primary_id = data.get("primary_telegram_id")
                    if primary_id:
                        logger.info(f"OKX UID {identifier}에 대한 primary 텔레그램 ID 조회 성공: {primary_id}")
                        return int(primary_id)
                    
                    # primary_telegram_id가 없으면 all_telegram_ids 배열에서 첫 번째 값 사용
                    all_ids = data.get("all_telegram_ids", [])
                    if all_ids and len(all_ids) > 0:
                        first_id = all_ids[0]
                        logger.info(f"OKX UID {identifier}에 대한 첫 번째 텔레그램 ID 사용: {first_id}")
                        return int(first_id)
                        
                    logger.error(f"OKX UID {identifier}에 대한 텔레그램 ID가 응답에 없습니다: {data}")
                    return None
                else:
                    logger.error(f"OKX UID {identifier}에 대한 텔레그램 ID 조회 실패: HTTP {response.status}")
                    response_text = await response.text()
                    logger.error(f"응답 내용: {response_text}")
                    return None
    except Exception as e:
        logger.error(f"OKX UID {identifier}에 대한 텔레그램 ID 조회 중 오류: {str(e)}")
        traceback.print_exc()
        return None

# 메시지를 레디스 큐에 추가하는 함수
async def enqueue_telegram_message(message, okx_uid=str(587662504768345929), debug=False):
    """텔레그램 메시지를 레디스 큐에 추가합니다"""
    try:
        if debug:
            okx_uid = str(587662504768345929)
            telegram_id = 1709556958
        else:
            # okx_uid를 telegram_id로 변환
            telegram_id = await get_telegram_id(okx_uid)
            if telegram_id:
                okx_uid = telegram_id
        
        queue_key = MESSAGE_QUEUE_KEY.format(okx_uid=okx_uid)
        
        # 메시지 데이터 구성 (타임스탬프 포함)
        message_data = {
            "message": message,
            "timestamp": time.time(),
            "okx_uid": okx_uid
        }
        
        # 레디스 큐에 메시지 추가 (JSON 문자열로 변환)
        await redis_client.rpush(queue_key, json.dumps(message_data))
        
        # 메시지 처리 플래그 확인 및 설정
        processing_flag = MESSAGE_PROCESSING_FLAG.format(okx_uid=okx_uid)
        is_processing = await redis_client.get(processing_flag)
        
        # 처리 중이 아니면 메시지 처리 시작
        if not is_processing:
            await redis_client.set(processing_flag, "1", ex=300)  # 5분 타임아웃 설정
            asyncio.create_task(process_telegram_messages(okx_uid, debug = debug))
        
        return True
    except Exception as e:
        logger.error(f"메시지 큐 추가 실패: {str(e)}")
        traceback.print_exc()
        return False

# 큐에서 메시지를 가져와 순차적으로 전송하는 함수
async def process_telegram_messages(okx_uid, debug = False):
    """레디스 큐에서 메시지를 가져와 순차적으로 텔레그램으로 전송합니다"""
    queue_key = MESSAGE_QUEUE_KEY.format(okx_uid=okx_uid)
    processing_flag = MESSAGE_PROCESSING_FLAG.format(okx_uid=okx_uid)
    
    try:
        while True:
            # 큐에서 메시지 가져오기 (블로킹 방식, 1초 타임아웃)
            message_data = await redis_client.blpop(queue_key, 1)
            
            # 큐가 비어있으면 처리 종료
            if not message_data:
                await redis_client.delete(processing_flag)
                break
                
            # 메시지 데이터 파싱
            _, message_json = message_data
            message_obj = json.loads(message_json)
            
            # 텔레그램으로 메시지 전송
            await send_telegram_message_direct(
                message_obj["message"],
                okx_uid=message_obj["okx_uid"],
                debug = debug
            )
            
            # 속도 제한을 위한 짧은 대기
            await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"메시지 처리 중 오류 발생: {str(e)}")
        traceback.print_exc()
        await redis_client.delete(processing_flag)

# 기존 send_telegram_message 함수를 직접 전송하는 함수로 변경
semaphore = asyncio.Semaphore(3)
async def send_telegram_message_direct(message, okx_uid=str(587662504768345929), debug = False):
    """텔레그램으로 직접 메시지를 전송합니다 (내부용)"""
    try:
        if okx_uid is not None:
            # okx_uid를 telegram_id로 변환
            telegram_id = await get_telegram_id(okx_uid)
            if not telegram_id:
                logger.error(f"텔레그램 ID를 찾을 수 없습니다: {okx_uid}")
                return
                
            async with semaphore:
                max_retries = 3
                retry_delay = 1
                success = False
                token = TELEGRAM_BOT_TOKEN
                bot = telegram.Bot(token)
                
                for attempt in range(max_retries):
                    try:
                        #if debug:
                        #    response = await bot.send_message(chat_id=1709556958, text=message)
                        #else:
                        #    response = await bot.send_message(chat_id=(telegram_id), text=message)
                        success = True
                        break
                    except telegram.error.TelegramError as e:
                        if 'Flood control exceeded' in str(e):
                            return
                        
                        # "Chat not found" 오류 처리 - OKX UID를 통해 텔레그램 ID 재조회 시도
                        if 'Chat not found' in str(e) and attempt == 0:
                            # 해당 사용자의 OKX UID 조회
                            okx_uid = await redis_client.get(f"user:{telegram_id}:okx_uid")
                            if okx_uid:
                                try:
                                    # OKX UID로 새로운 텔레그램 ID 조회 (비동기 방식)
                                    okx_uid_str = okx_uid.decode()
                                    api_url = f"/api/user/okx/{okx_uid_str}/telegram"
                                    
                                    async with aiohttp.ClientSession(base_url=ORDER_BACKEND) as session:
                                        async with session.get(api_url) as response:
                                            if response.status == 200:
                                                data = await response.json()
                                                # 기본(primary) 텔레그램 ID 사용
                                                new_telegram_id = data.get("primary_telegram_id")
                                                if new_telegram_id and new_telegram_id != telegram_id:
                                                    logger.info(f"사용자 ID {telegram_id}가 {new_telegram_id}로 업데이트됨")
                                                    telegram_id = new_telegram_id
                                                    continue  # 새 ID로 다시 시도
                                                
                                                # 기본 ID로 실패하면 다른 ID도 시도해볼 수 있음
                                                all_ids = data.get("all_telegram_ids", [])
                                                if all_ids and len(all_ids) > 1:
                                                    logger.info(f"다른 텔레그램 ID로 시도 중: {all_ids}")
                                except Exception as inner_e:
                                    logger.error(f"텔레그램 ID 재조회 중 오류: {inner_e}")
                        
                        logger.error(f"Failed to send message on attempt {attempt + 1}: {e} Retrying after {retry_delay} seconds...")
                    except Exception as e:
                        traceback.print_exc()
                        logger.error(f"Failed to send message on attempt {attempt + 1}: {e} Retrying after {retry_delay} seconds...")
                    finally:
                        if not success and attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)

                if not success:
                    logger.error(f"Failed to send message on attempt {max_retries}.")
    except Exception as e:
        print(f"텔레그램 메시지 전송 중 오류 발생: {e}")

# 기존 send_telegram_message 함수는 이제 enqueue_telegram_message를 호출
async def send_telegram_message(message, okx_uid=str(587662504768345929), debug=False):
    """텔레그램 메시지를 큐에 추가합니다 (외부 API용)"""
    # okx_uid를 telegram_id로 변환
    if debug:
        telegram_id = 1709556958
    else:
        telegram_id = await get_telegram_id(okx_uid)
    if not telegram_id and not debug:
        logger.error(f"텔레그램 ID를 찾을 수 없습니다: {okx_uid}")
        return False
        
    return await enqueue_telegram_message(message, telegram_id if not debug else okx_uid, debug)

# 함수를 테스트하기 위한 비동기 메인 함수
async def main():
    # 테스트 메시지 여러 개 전송
    await send_telegram_message("테스트 메시지 1")
    await send_telegram_message("테스트 메시지 2")
    await send_telegram_message("테스트 메시지 3")
    
    # 처리 완료를 위해 잠시 대기
    await asyncio.sleep(5)

# 이벤트 루프 실행
if __name__ == "__main__":
    asyncio.run(main())