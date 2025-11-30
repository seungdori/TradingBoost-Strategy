import asyncio
import base64
import hashlib
import hmac
import json
import time
import traceback
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from HYPERRSI.src.api.dependencies import get_user_api_keys
from shared.database.redis_helper import get_redis_client

# Dynamic redis_client access

# Don't initialize at module level - use lazy loading
# redis_client = get_redis_client()  # Removed - causes import-time error

# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")

class TriggerCancelClient:
    def __init__(self, api_key, secret_key, passphrase, base_url="https://www.okx.com"):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.base_url = base_url
        # 서버 시간 캐싱을 위한 변수 추가
        self.server_time_offset = None  # 서버 시간과 로컬 시간의 차이
        self.last_server_time_fetch = 0  # 마지막으로 서버 시간을 가져온 시간
        self.server_time_cache_duration = 300  # 캐시 유효 시간(초)
        self.timeout = 10  # 요청 타임아웃 (초)

        # 연결 풀링과 자동 재시도를 위한 세션 설정
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get_server_timestamp(self):
        """
        서버의 타임스탬프를 가져온 후,
        만약 타임스탬프에 "T"가 포함되어 있지 않으면 (즉, 밀리초 형식이면)
        ISO8601 형식 (예: "2025-02-04T11:59:58.512Z")으로 변환하여 반환합니다.
        
        서버 시간 요청을 최소화하기 위해 오프셋을 캐싱합니다.
        """
        current_time = time.time()
        
        # 캐시된 오프셋이 있고, 캐시 유효 시간 내라면 로컬 시간 기반으로 서버 시간 계산
        if self.server_time_offset is not None and (current_time - self.last_server_time_fetch) < self.server_time_cache_duration:
            # 로컬 시간 + 오프셋으로 서버 시간 추정
            dt = datetime.fromtimestamp(current_time + self.server_time_offset, tz=timezone.utc)
            return dt.isoformat("T", "milliseconds").replace("+00:00", "Z")
        
        # 캐시된 오프셋이 없거나 캐시가 만료되었으면 서버에서 새로 가져옴
        max_retries = 3
        retry_delay = 2  # 초 단위 초기 지연 시간

        # 연결 오류로 재시도해야 할 예외 타입들
        connection_errors = (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        )

        for retry in range(max_retries):
            try:
                response = self.session.get(f'{self.base_url}/api/v5/public/time', timeout=self.timeout)

                # 요청 한도 초과 확인
                if response.status_code == 429 or "Too Many Requests" in response.text:
                    if retry < max_retries - 1:  # 마지막 시도가 아니면 재시도
                        wait_time = retry_delay * (2 ** retry)  # 지수 백오프
                        print(f"서버 시간 조회: API 요청 한도 초과. {wait_time}초 후 재시도 ({retry+1}/{max_retries})...")
                        time.sleep(wait_time)
                        continue

                if response.status_code == 200:
                    ts = response.json()['data'][0]['ts']

                    # ts가 문자열이고 "T"가 있으면 ISO8601 형식으로 간주
                    if isinstance(ts, str) and "T" in ts:
                        server_time_str = ts
                        # ISO8601 문자열에서 timestamp로 변환
                        server_time = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                    else:
                        # 밀리초 형식이면 ISO8601으로 변환
                        if isinstance(ts, str):
                            ts = int(ts)
                        server_time = ts / 1000  # 밀리초를 초로 변환
                        dt = datetime.fromtimestamp(server_time, tz=timezone.utc)
                        server_time_str = dt.isoformat("T", "milliseconds").replace("+00:00", "Z")

                    # 서버 시간과 로컬 시간의 차이(오프셋) 계산 및 저장
                    self.server_time_offset = server_time - current_time
                    self.last_server_time_fetch = current_time
                    #print(f"서버 시간 오프셋 업데이트: {self.server_time_offset:.3f}초")

                    return server_time_str

                raise Exception(f"Failed to get server time: {response.text}")
            except connection_errors as e:
                # 연결 오류는 재시도
                if retry < max_retries - 1:
                    wait_time = retry_delay * (2 ** retry)
                    print(f"서버 시간 조회: 연결 오류 발생. {wait_time}초 후 재시도 ({retry+1}/{max_retries})... 오류: {type(e).__name__}")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"서버 시간 조회: 연결 오류 - 최대 재시도 횟수 초과: {e}")
                    # 캐시된 오프셋이 있으면 로컬 시간 기반으로 서버 시간 계산 시도
                    if self.server_time_offset is not None:
                        print("캐시된 서버 시간 오프셋을 사용합니다.")
                        dt = datetime.fromtimestamp(current_time + self.server_time_offset, tz=timezone.utc)
                        return dt.isoformat("T", "milliseconds").replace("+00:00", "Z")
                    # 캐시도 없으면 로컬 시간 기반으로 대체
                    print("캐시된 오프셋 없음 - 로컬 시간을 서버 시간으로 사용합니다.")
                    dt = datetime.fromtimestamp(current_time, tz=timezone.utc)
                    return dt.isoformat("T", "milliseconds").replace("+00:00", "Z")
            except Exception as e:
                if "Too Many Requests" in str(e) and retry < max_retries - 1:
                    wait_time = retry_delay * (2 ** retry)  # 지수 백오프
                    print(f"서버 시간 조회: API 요청 한도 초과. {wait_time}초 후 재시도 ({retry+1}/{max_retries})...")
                    time.sleep(wait_time)
                else:
                    print(f"Error getting server timestamp: {e}")
                    # 캐시된 오프셋이 있으면 로컬 시간 기반으로 서버 시간 계산 시도
                    if self.server_time_offset is not None:
                        print("캐시된 서버 시간 오프셋을 사용합니다.")
                        dt = datetime.fromtimestamp(current_time + self.server_time_offset, tz=timezone.utc)
                        return dt.isoformat("T", "milliseconds").replace("+00:00", "Z")
                    raise
                    
        print(f"서버 시간 조회: 최대 재시도 횟수({max_retries})를 초과했습니다.")
        # 캐시된 오프셋이 있으면 로컬 시간 기반으로 서버 시간 계산 시도
        if self.server_time_offset is not None:
            print("캐시된 서버 시간 오프셋을 사용합니다.")
            dt = datetime.fromtimestamp(current_time + self.server_time_offset, tz=timezone.utc)
            return dt.isoformat("T", "milliseconds").replace("+00:00", "Z")
        raise Exception("서버 시간 조회 실패: 최대 재시도 횟수 초과")

    def _generate_signature(self, timestamp, method, request_path, body):
        """
        OKX API 인증 서명 생성:
          prehash = timestamp + method + request_path + body
          HMAC SHA256로 암호화 후 Base64 인코딩하여 반환
        """
        message = timestamp + method + request_path + body
        mac = hmac.new(
            self.secret_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()
    
    async def fetch_algo_orders(self, inst_id, ord_type):
        max_retries = 3
        retry_delay = 2  # 초 단위 초기 지연 시간

        # 연결 오류로 재시도해야 할 예외 타입들
        connection_errors = (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        )

        for retry in range(max_retries):
            try:
                method = "GET"
                request_path = f"/api/v5/trade/orders-algo-pending?instId={inst_id}&ordType={ord_type}"
                url = self.base_url + request_path

                # GET 요청이므로 body는 빈 문자열
                body = ""

                # 요청 직전에 서버 타임스탬프(ISO8601 형식)를 가져옴
                timestamp = self.get_server_timestamp()
                signature = self._generate_signature(timestamp, method, request_path, body)

                headers = {
                    "Content-Type": "application/json",
                    "OK-ACCESS-KEY": self.api_key,
                    "OK-ACCESS-SIGN": signature,
                    "OK-ACCESS-TIMESTAMP": timestamp,
                    "OK-ACCESS-PASSPHRASE": self.passphrase
                }

                response = self.session.get(url, headers=headers, timeout=self.timeout)
                response_data = response.json()

                # 요청 한도 초과 확인
                if response_data.get('code') == '50011':  # Too Many Requests
                    if retry < max_retries - 1:  # 마지막 시도가 아니면 재시도
                        wait_time = retry_delay * (2 ** retry)  # 지수 백오프
                        print(f"API 요청 한도 초과. {wait_time}초 후 재시도 ({retry+1}/{max_retries})...")
                        await asyncio.sleep(wait_time)
                        continue

                return response_data

            except connection_errors as e:
                # 연결 오류는 재시도
                if retry < max_retries - 1:
                    wait_time = retry_delay * (2 ** retry)
                    print(f"fetch_algo_orders: 연결 오류 발생. {wait_time}초 후 재시도 ({retry+1}/{max_retries})... 오류: {type(e).__name__}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    print(f"fetch_algo_orders: 연결 오류 - 최대 재시도 횟수 초과: {e}")
                    # errordb 로깅
                    from HYPERRSI.src.utils.error_logger import log_error_to_db
                    log_error_to_db(
                        error=e,
                        error_type="AlgoOrderFetchConnectionError",
                        severity="WARNING",
                        symbol=inst_id,
                        metadata={"ord_type": ord_type, "retry": retry, "component": "TriggerCancelClient.fetch_algo_orders", "error_type": type(e).__name__}
                    )
                    return None

            except Exception as e:
                if "Too Many Requests" in str(e) and retry < max_retries - 1:
                    wait_time = retry_delay * (2 ** retry)  # 지수 백오프
                    print(f"API 요청 한도 초과. {wait_time}초 후 재시도 ({retry+1}/{max_retries})...")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"Error in fetch_algo_orders: {str(e)}")
                    traceback.print_exc()
                    # errordb 로깅
                    from HYPERRSI.src.utils.error_logger import log_error_to_db
                    log_error_to_db(
                        error=e,
                        error_type="AlgoOrderFetchError",
                        severity="ERROR",
                        symbol=inst_id,
                        metadata={"ord_type": ord_type, "retry": retry, "component": "TriggerCancelClient.fetch_algo_orders"}
                    )
                    return None

        print(f"최대 재시도 횟수({max_retries})를 초과했습니다.")
        return None

    async def cancel_all_trigger_orders(self, inst_id, side : str = None, algo_type: str = "trigger", user_id : str = None):
        """
        인스턴스 ID에 해당하는 trigger 주문들을 모두 취소합니다.
        side 파라미터가 주어지면, 해당 side("buy" 혹은 "sell")의 주문만 취소합니다.
        """
        try:
            redis = await get_redis_client()
            
            order_side = side
            if side == "long":
                side = "buy"
                order_side = "sell"
            elif side == "short":
                side = "sell"
                order_side = "buy"
            elif side == "buy":
                side = "buy"
                order_side = "sell"
            elif side == "sell":
                side = "sell"
                order_side = "buy"
            # Fetch active trigger orders
            active_orders = await self.fetch_algo_orders(inst_id=inst_id, ord_type=algo_type)
            if active_orders is not None:
                print(f"inst_id : {inst_id}, side : {side}, order_side : {order_side}, algo_type : {algo_type}")
                print("active_orders : ", active_orders)
            else:
                print(f"Failed to fetch active orders: API 요청 한도 초과 또는 연결 오류")
                return
            
            # active_orders가 None인 경우 처리
            if active_orders is None:
                print("Failed to fetch active orders: API 요청 한도 초과 또는 연결 오류")
                return
                
            if active_orders.get('code') != '0':
                print(f"Failed to fetch active orders: {active_orders.get('msg')}")
                return

            # Extract algoIds from active orders
            algo_orders = active_orders.get('data', [])
            if not algo_orders:
                print("No active trigger orders found.")
                # 주문이 없는 경우에도 성공 응답 반환 (code: 0, 성공)
                return {
                    'code': '0',
                    'msg': 'No active orders to cancel',
                    'data': []
                }
            print(f"[DEBUG] Total algo_orders fetched: {len(algo_orders)}")
            print(f"[DEBUG] order_side filter: {order_side}")

            # 모든 주문 디버그 출력
            for idx, order in enumerate(algo_orders):
                print(f"[DEBUG] Order {idx+1}: algoId={order.get('algoId')}, side={order.get('side')}, posSide={order.get('posSide')}")

            if order_side is not None:
                print(f"[DEBUG] Filtering orders with side={order_side}")
                algo_orders = [
                    order for order in algo_orders
                    if order.get('side', '').lower() == order_side.lower()
                ]
                print(f"[DEBUG] After filtering: {len(algo_orders)} orders remaining")
                if not algo_orders:
                    print(f"No active trigger orders found for side: {order_side}")
                    # 특정 방향의 주문이 없는 경우에도 성공 응답 반환
                    return {
                        'code': '0',
                        'msg': f'No active orders to cancel for side: {order_side}',
                        'data': []
                    }
            # Prepare cancellation requests
            cancel_requests = [
                {"instId": inst_id, "algoId": order['algoId']}
                for order in algo_orders
            ]
            
            for order in algo_orders:
                monitor_key = f"monitor:user:{user_id}:{inst_id}:{order['algoId']}"
                await redis.delete(monitor_key)


            # Send cancellation request with retry logic
            method = "POST"
            request_path = "/api/v5/trade/cancel-algos"
            url = self.base_url + request_path
            body = json.dumps(cancel_requests)

            # 연결 오류로 재시도해야 할 예외 타입들
            connection_errors = (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            )

            max_retries = 3
            retry_delay = 2
            response_data = None

            for retry in range(max_retries):
                try:
                    timestamp = self.get_server_timestamp()
                    signature = self._generate_signature(timestamp, method, request_path, body)

                    headers = {
                        "Content-Type": "application/json",
                        "OK-ACCESS-KEY": self.api_key,
                        "OK-ACCESS-SIGN": signature,
                        "OK-ACCESS-TIMESTAMP": timestamp,
                        "OK-ACCESS-PASSPHRASE": self.passphrase
                    }

                    response = self.session.post(url, headers=headers, data=body, timeout=self.timeout)
                    response_data = response.json()
                    break  # 성공시 루프 종료

                except connection_errors as e:
                    if retry < max_retries - 1:
                        wait_time = retry_delay * (2 ** retry)
                        print(f"cancel_algos: 연결 오류 발생. {wait_time}초 후 재시도 ({retry+1}/{max_retries})... 오류: {type(e).__name__}")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        print(f"cancel_algos: 연결 오류 - 최대 재시도 횟수 초과: {e}")
                        from HYPERRSI.src.utils.error_logger import log_error_to_db
                        log_error_to_db(
                            error=e,
                            error_type="AlgoCancelConnectionError",
                            user_id=user_id,
                            severity="ERROR",
                            symbol=inst_id,
                            metadata={"algo_type": algo_type, "retry": retry, "error_type": type(e).__name__}
                        )
                        return None

            if response_data is None:
                print("cancel_algos: 응답 없음")
                return None

            # 취소 결과 로깅
            print(f"[SL 취소 응답] {inst_id} user:{user_id} - code: {response_data.get('code')}, msg: {response_data.get('msg')}, 취소 대상: {len(cancel_requests)}건")

            # 취소 실패 시 stoploss_error_logs에 기록
            if response_data.get('code') != '0':
                from HYPERRSI.src.database.stoploss_error_db import log_stoploss_error
                await log_stoploss_error(
                    error=Exception(f"알고 주문 취소 실패: {response_data.get('msg')}"),
                    error_type="AlgoOrderCancelError",
                    user_id=user_id,
                    severity="ERROR",
                    module="cancel_trigger_okx",
                    function_name="cancel_all_trigger_orders",
                    symbol=inst_id,
                    side=side,
                    order_side=order_side,
                    algo_type=algo_type,
                    failure_reason=f"OKX API 응답 코드: {response_data.get('code')}, 메시지: {response_data.get('msg')}",
                    metadata={
                        "cancel_requests": cancel_requests,
                        "response_data": response_data,
                        "algo_orders_count": len(algo_orders)
                    }
                )

            return response_data

        except Exception as e:
            print(f"Error in cancel_all_trigger_orders: {str(e)}")
            traceback.print_exc()
            # errordb 로깅
            from HYPERRSI.src.utils.error_logger import log_error_to_db
            log_error_to_db(
                error=e,
                error_type="TriggerOrderCancellationError",
                user_id=user_id,
                severity="CRITICAL",
                symbol=inst_id,
                side=side,
                metadata={"algo_type": algo_type, "component": "TriggerCancelClient.cancel_all_trigger_orders"}
            )
            return None

async def main():
    try:
        api_keys = await get_user_api_keys("1709556958")
        
        client = TriggerCancelClient(
            api_key=api_keys['api_key'],
            secret_key=api_keys['api_secret'],
            passphrase=api_keys['passphrase']
        )
        
        result = await client.cancel_all_trigger_orders(inst_id = "BTC-USDT-SWAP", side = "short", algo_type="trigger", user_id="1709556958")
        print(json.dumps(result, indent=4))

    except Exception as e:
        print(f"Error in main: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())