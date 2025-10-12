"""WebSocket 클라이언트 및 유틸리티"""

import asyncio
import random
import time
from datetime import datetime, timedelta, timezone

import websockets


async def log_exception(e):
    """
    예외 정보를 로깅합니다.

    Args:
        e: 예외 객체
    """
    print(f"An error occurred: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print(f"HTTP Status: {e.response.status}")
        try:
            print(f"Response Content: {await e.response.text()}")
        except Exception as resp_e:
            print(f"Failed to read response content: {resp_e}")


async def send_heartbeat(websocket, interval=30):
    """
    WebSocket 연결 유지를 위한 heartbeat를 전송합니다.

    Args:
        websocket: WebSocket 연결
        interval: heartbeat 전송 간격 (초)
    """
    while True:
        try:
            await websocket.ping()
            await asyncio.sleep(interval)
        except websockets.ConnectionClosed:
            break


async def ws_client(exchange_name, symbol, symbol_queue, user_id, max_retries=6):
    """
    거래소 WebSocket 클라이언트입니다.

    Args:
        exchange_name: 거래소 이름
        symbol: 심볼
        symbol_queue: 가격 데이터를 전달할 큐
        user_id: 사용자 ID
        max_retries: 최대 재시도 횟수

    Note:
        이 함수는 grid_original에서 가져온 것으로, 복잡한 로직이 포함되어 있습니다.
        향후 더 세분화할 수 있습니다.
    """
    from core.redis import get_redis_connection
    from trading.instance_manager import get_exchange_instance

    redis = await get_redis_connection()
    exchange = None
    try:
        exchange = await get_exchange_instance(exchange_name, user_id)
        retries = 0
        user_key = f'{exchange_name}:user:{user_id}'

        # 심볼 형식 변환
        if exchange_name == 'okx':
            parts = symbol.replace('-SWAP', '').split('-')
            symbol = f"{parts[0]}/{parts[1]}:{parts[1]}"
        elif exchange_name == 'okx_spot':
            parts = symbol.split('-')
            symbol = f"{parts[0]}/{parts[1]}"

        last_check_time = 0.0
        check_interval = 7  # 7초마다 is_running 상태 확인
        print(f"Connecting to {exchange} websocket for {symbol}.")
        reconnected = False

        while True:
            current_time = time.time()

            # is_running 상태 확인
            if current_time - last_check_time > check_interval:
                is_running_value = await redis.hget(user_key, 'is_running')
                if isinstance(is_running_value, bytes):
                    is_running_str = is_running_value.decode('utf-8')
                else:
                    is_running_str = is_running_value
                is_running = bool(int(is_running_str or '0'))
                last_check_time = current_time

            if is_running and (retries < max_retries):
                try:
                    ticker = await exchange.watch_ticker(symbol)
                    if reconnected:
                        print(f"Successfully reconnected to {exchange} websocket for {symbol} after {retries} retries.")
                        reconnected = False

                    retries = 0  # 성공 시 재시도 카운트 리셋
                    last_price = ticker['last']
                    server_time = ticker.get('timestamp', None)

                    # UTC → KST 변환
                    utc_time = datetime.fromtimestamp(server_time / 1000, timezone.utc)
                    kst_time = utc_time + timedelta(hours=9)

                    await symbol_queue.put((last_price, kst_time))
                    await asyncio.sleep(random.random() + 0.4)

                except Exception as e:
                    print(f"Error in ws_client for {symbol} on {exchange_name}: {str(e)}")
                    retries += 1
                    print(f"Attempting to reconnect... ({retries}/{max_retries})")
                    reconnected = True
                    await asyncio.sleep(min(2 * retries, 5))
            else:
                if retries >= max_retries:
                    print(f"Max retries reached for {symbol}. Stopping...")
                    break
                else:
                    print(f"Stopping websocket client for {symbol}... cause of is_running is {is_running}")
                    break

    except Exception as e:
        print(f"Unexpected error in ws_client for {symbol}: {str(e)}")
