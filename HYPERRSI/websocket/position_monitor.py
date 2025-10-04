import asyncio
import json
import logging
import websockets
import ssl
import time
import hmac
import os
import base64
import hashlib

from HYPERRSI.src.core.database import redis_client
from HYPERRSI.src.core.logger import get_logger

logger = get_logger(__name__)

OKX_PUBLIC_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
OKX_PRIVATE_WS_URL = "wss://ws.okx.com:8443/ws/v5/private"

class OKXWebsocketClient:
    def __init__(
        self,
        user_id: str,
        api_key: str,
        api_secret: str,
        passphrase: str,
        options: dict = None
    ):
        self.user_id = user_id
        
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.options = options or {}

        if not all([self.api_key, self.api_secret, self.passphrase]):
            logger.warning("[OKX] API credentials not found. Private channels will be disabled.")
            self.private_enabled = False
        else:
            self.private_enabled = True

        self.logger = logging.getLogger("OKX_WS_Manager")
        self.public_ws = None
        self.private_ws = None
        self.running = True

    async def connect(self):
        """Public/Private WebSocket 모두 연결"""
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # 1) 공개 채널 연결
        self.public_ws = await websockets.connect(OKX_PUBLIC_WS_URL, ssl=ssl_context)
        logger.info("[OKX] Connected to Public WebSocket")

        # 공개 채널: Ticker 구독
        subscribe_public = {
            "op": "subscribe",
            "args": [
                {
                    "channel": "tickers",
                    "instId": "BTC-USDT-SWAP"  # 이 부분이 실제 트레이딩 심볼과 일치해야 함
                }
            ]
        }
        await self.public_ws.send(json.dumps(subscribe_public))
        logger.info("[OKX] Subscribed to public channel (tickers)")

        # 2) 개인 채널 연결 (API 키 있는 경우)
        if self.private_enabled:
            try:
                self.private_ws = await websockets.connect(
                    OKX_PRIVATE_WS_URL,
                    ssl=ssl_context,  # SSL 컨텍스트 추가
                    ping_interval=20,
                    ping_timeout=10
                )
                logger.info("[OKX] Private WebSocket connected")
                
                # 로그인 시도
                await self.login()
                response = await self.private_ws.recv()
                logger.info(f"[OKX] Login response: {response}")
                
            except Exception as e:
                logger.error(f"[OKX] Connection error: {str(e)}")
                self.private_ws = None

    async def login(self):
        """OKX WebSocket 로그인"""
        timestamp = str(int(time.time()))
        message = timestamp + 'GET' + '/users/self/verify'
        
        # HMAC-SHA256 서명 생성
        mac = hmac.new(
            bytes(self.api_secret, encoding='utf-8'),
            bytes(message, encoding='utf-8'),
            digestmod='sha256'
        )
        d = mac.digest()
        signature = base64.b64encode(d).decode()

        login_message = {
            "op": "login",
            "args": [{
                "apiKey": self.api_key,
                "passphrase": self.passphrase,
                "timestamp": timestamp,
                "sign": signature
            }]
        }

        # 로그인 요청 전송
        await self.private_ws.send(json.dumps(login_message))
        logger.info("[OKX] Sent login request")

        # 로그인 응답 대기
        response = await self.private_ws.recv()
        response_data = json.loads(response)
        
        if response_data.get('event') == 'login' and response_data.get('code') == '0':
            logger.info("[OKX] Login successful")
            return True
        else:
            logger.error(f"[OKX] Login failed: {response_data}")
            return False

    async def handle_public_messages(self):
        """공개 채널(tickers)에서 들어오는 메시지를 Redis에 저장"""
        while self.running:
            try:
                message = await self.public_ws.recv()
                data = json.loads(message)
                #logger.debug(f"[OKX] Public Message: {data}")

                if "event" in data:
                    # 구독 성공/실패 등의 이벤트
                    logger.info(f"[OKX] Public event: {data}")
                elif "data" in data:
                    channel = data.get("arg", {}).get("channel")
                    inst_id = data.get("arg", {}).get("instId", "unknown")
                    if channel == "tickers":
                        redis_key = f"ws:okx:tickers:{inst_id}"
                        # data["data"]는 리스트 형태
                        await redis_client.set(redis_key, json.dumps(data["data"]))
                        #logger.debug(f"[OKX] Updated ticker data in Redis: {redis_key}")
            except websockets.exceptions.ConnectionClosed:
                logger.warning("[OKX] Public WebSocket connection closed.")
                break
            except Exception as e:
                logger.error(f"[OKX] Error in public message loop: {e}")
                await asyncio.sleep(1)

    async def handle_private_messages(self, user_id: str):
        """
        개인 채널(positions, orders) 메시지를 Redis에 저장.
        posSide가 net/long/short인지에 따라 key를 달리 저장할 수 있음.
        """
        if not self.private_enabled or not self.private_ws:
            logger.warning("[OKX] Private websocket is disabled or not connected.")
            return

        while self.running:
            try:
                message = await self.private_ws.recv()
                data = json.loads(message)
                logger.debug(f"[OKX] Private Message: {data}")

                if "event" in data:
                    logger.info(f"[OKX] Private event: {data}")
                elif "data" in data:
                    channel = data.get("arg", {}).get("channel")
                    inst_id = data.get("arg", {}).get("instId", "unknown")
                    payload = data["data"]  # 실제 포지션/오더 정보 리스트

                    if channel == "positions":
                        # OKX Position 모드(net/long/short 등) 유의
                        # payload가 여러 포지션일 수도 있음
                        for pos in payload:
                            # 예: posSide가 "net"인 경우 -> side="net"
                            side = pos.get("posSide", "unknown").lower()

                            # 예시) ws:user:1709556958:BTC-USDT-SWAP:long
                            redis_key = f"ws:user:{user_id}:{inst_id}:{side}"
                            await redis_client.set(redis_key, json.dumps(pos))
                            logger.debug(f"[OKX] Updated position => {redis_key}")

                    elif channel == "orders":
                        # 주문 정보도 여러 개가 들어올 수 있음 => 통째로 저장
                        redis_key = f"ws:user:{user_id}:{inst_id}:open_orders"
                        await redis_client.set(redis_key, json.dumps(payload))
                        logger.debug(f"[OKX] Updated orders => {redis_key}")

            except websockets.exceptions.ConnectionClosed:
                logger.warning("[OKX] Private WebSocket connection closed.")
                break
            except Exception as e:
                logger.error(f"[OKX] Error in private message loop: {e}")
                await asyncio.sleep(1)

    async def run(self, user_id: str):
        """Public/Private WebSocket 연결 후, 메시지 처리 루프 실행"""
        await self.connect()
        public_task = asyncio.create_task(self.handle_public_messages())
        private_task = None

        if self.private_enabled:
            private_task = asyncio.create_task(self.handle_private_messages(user_id))

        if private_task:
            await asyncio.gather(public_task, private_task)
        else:
            await public_task

    def stop(self):
        """루프 종료"""
        self.running = False
        
        
async def main():
    try:
        key = f"user:1709556958:api:keys"
        key_type = await redis_client.type(key)
        logger.info(f"Redis key type: {key_type}")
        
        # Redis type 명령어는 문자열로 반환되므로 정확한 비교 필요
        if key_type == b'hash' or key_type == 'hash':
            api_keys = await redis_client.hgetall(key)
            if not api_keys:
                logger.error("API 키를 찾을 수 없습니다")
                return
                
            logger.info(f"Found API keys (hash): {api_keys}")
            
            # 문자열 키로 접근하도록 수정
            client = OKXWebsocketClient(
                user_id="1709556958",
                api_key=api_keys.get('api_key', ''),  # 바이트열 키(b'api_key') 대신 문자열 키 사용
                api_secret=api_keys.get('api_secret', ''),
                passphrase=api_keys.get('passphrase', '')
            )
        else:
            # 문자열 타입인 경우
            api_keys = await redis_client.get(key)
            if not api_keys:
                logger.error("API 키를 찾을 수 없습니다")
                return
                
            logger.info(f"Found API keys (string): {api_keys}")  # 디버깅용
            
            api_keys_json = json.loads(api_keys)
            client = OKXWebsocketClient(
                user_id="1709556958",
                api_key=api_keys_json.get("api_key"),
                api_secret=api_keys_json.get("api_secret"),
                passphrase=api_keys_json.get("passphrase")
            )
            
        await client.run("1709556958")
        
    except Exception as e:
        logger.error(f"에러 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())  # 상세한 에러 트레이스 출력

if __name__ == "__main__":
    asyncio.run(main())
