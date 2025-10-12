"""OKX WebSocket 통합 클라이언트

실시간 시장 데이터 및 계정 정보 수신을 위한 WebSocket 클라이언트
"""
import asyncio
import base64
import hashlib
import hmac
import json
import time
from typing import Any, Callable, Dict, Optional

import websockets
from websockets.legacy.client import WebSocketClientProtocol

from shared.exchange.okx.constants import WSS_PRIVATE_URL, WSS_PUBLIC_URL
from shared.logging import get_logger

logger = get_logger(__name__)


class OKXWebsocket:
    """
    OKX WebSocket 클라이언트

    공개 채널(시장 데이터) 및 비공개 채널(계정 정보) 구독 지원
    """

    def __init__(self, api_key: str, api_secret: str, passphrase: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.connections: Dict[str, asyncio.Task[None]] = {}
        self.callbacks: Dict[str, Callable[[Any], Any]] = {}

    async def connect(
        self,
        channel: str,
        symbol: str,
        callback: Callable[[Any], Any],
        private: bool = False
    ) -> None:
        """
        WebSocket 채널 연결 및 구독

        Args:
            channel: 채널 이름 (예: "trades", "positions", "orders")
            symbol: 거래 쌍 심볼
            callback: 메시지 수신 시 호출할 콜백 함수
            private: 비공개 채널 여부
        """
        url = WSS_PRIVATE_URL if private else WSS_PUBLIC_URL

        async def handler():
            while True:
                try:
                    async with websockets.connect(url) as ws:
                        # 비공개 채널의 경우 인증 수행
                        if private:
                            await self._authenticate(ws)

                        # 구독 메시지 전송
                        subscribe_message = {
                            "op": "subscribe",
                            "args": [{
                                "channel": channel,
                                "instId": symbol
                            }]
                        }
                        await ws.send(json.dumps(subscribe_message))
                        logger.info(f"Subscribed to {channel}:{symbol}")

                        # 메시지 수신 루프
                        while True:
                            message = await ws.recv()
                            data = json.loads(message)
                            await callback(data)

                except Exception as e:
                    logger.error(f"WebSocket error: {str(e)}")
                    await asyncio.sleep(5)  # 재연결 전 대기
                    continue

        task = asyncio.create_task(handler())
        self.connections[f"{channel}:{symbol}"] = task

    async def _authenticate(self, ws: WebSocketClientProtocol) -> None:
        """
        비공개 채널 인증

        Args:
            ws: WebSocket 연결 객체
        """
        timestamp = str(int(time.time()))
        message = timestamp + 'GET' + '/users/self/verify'
        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')

        login_data = {
            "op": "login",
            "args": [{
                "apiKey": self.api_key,
                "passphrase": self.passphrase,
                "timestamp": timestamp,
                "sign": signature
            }]
        }

        await ws.send(json.dumps(login_data))
        login_response_raw = await ws.recv()
        login_response = login_response_raw.decode() if isinstance(login_response_raw, bytes) else login_response_raw
        logger.info(f"Login response: {login_response}")

    async def disconnect(self, channel: str, symbol: str) -> None:
        """
        WebSocket 연결 해제

        Args:
            channel: 채널 이름
            symbol: 거래 쌍 심볼
        """
        key = f"{channel}:{symbol}"
        if key in self.connections:
            self.connections[key].cancel()
            del self.connections[key]
            logger.info(f"Disconnected from {key}")

    async def disconnect_all(self) -> None:
        """모든 WebSocket 연결 해제"""
        for task in self.connections.values():
            task.cancel()
        self.connections.clear()
        logger.info("All WebSocket connections closed")


async def get_position_via_websocket(
    api_key: str,
    secret_key: str,
    passphrase: str,
    symbol: str,
    cache_key: str,
    redis_client: Any
) -> float:
    """
    WebSocket을 통한 포지션 조회 (GRID 호환성)

    Args:
        api_key: API 키
        secret_key: API 시크릿
        passphrase: API 패스프레이즈
        symbol: 심볼
        cache_key: Redis 캐시 키
        redis_client: Redis 클라이언트

    Returns:
        float: 포지션 수량
    """
    uri = WSS_PRIVATE_URL

    async with websockets.connect(uri) as websocket:
        # 인증 수행
        timestamp = str(int(time.time()))
        message = timestamp + 'GET' + '/users/self/verify'
        signature = base64.b64encode(
            hmac.new(
                secret_key.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')

        login_data = {
            "op": "login",
            "args": [{
                "apiKey": api_key,
                "passphrase": passphrase,
                "timestamp": timestamp,
                "sign": signature
            }]
        }
        await websocket.send(json.dumps(login_data))
        login_response_raw = await websocket.recv()
        login_response = login_response_raw.decode() if isinstance(login_response_raw, bytes) else login_response_raw
        logger.info(f"Login response: {login_response}")

        # 포지션 채널 구독
        subscribe_data = {
            "op": "subscribe",
            "args": [{
                "channel": "positions",
                "instType": "SWAP"
            }]
        }
        await websocket.send(json.dumps(subscribe_data))
        subscription_response_raw = await websocket.recv()
        subscription_response = subscription_response_raw.decode() if isinstance(subscription_response_raw, bytes) else subscription_response_raw
        logger.info(f"Subscription response: {subscription_response}")

        # 포지션 데이터 수신
        try:
            while True:
                position_data = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                data = json.loads(position_data)

                if 'data' in data:
                    positions_data = data['data']
                    # Redis 캐싱
                    await redis_client.set(cache_key, json.dumps(positions_data), ex=300)

                    # 특정 심볼의 포지션 수량 추출
                    for position in positions_data:
                        if position.get('instId') == symbol:
                            quantity = float(position.get('pos', '0'))
                            return quantity

                    return 0.0

        except asyncio.TimeoutError:
            logger.warning("Timeout occurred while waiting for position data")
            return 0.0
        except Exception as e:
            logger.error(f"Error in WebSocket connection: {e}")
            return 0.0
