import json
import asyncio
from typing import Callable, Dict, Optional
import websockets
from .constants import WSS_PUBLIC_URL, WSS_PRIVATE_URL
from shared.logging import get_logger

logger = get_logger(__name__)

class OKXWebsocket:
    def __init__(self, api_key: str, api_secret: str, passphrase: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.connections = {}
        self.callbacks = {}
        
    async def connect(self, channel: str, symbol: str, 
                     callback: Callable, private: bool = False):
        url = WSS_PRIVATE_URL if private else WSS_PUBLIC_URL
        
        async def handler():
            while True:
                try:
                    async with websockets.connect(url) as ws:
                        # 구독 메시지 전송
                        subscribe_message = {
                            "op": "subscribe",
                            "args": [{
                                "channel": channel,
                                "instId": symbol
                            }]
                        }
                        await ws.send(json.dumps(subscribe_message))
                        
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
        
    async def disconnect(self, channel: str, symbol: str):
        key = f"{channel}:{symbol}"
        if key in self.connections:
            self.connections[key].cancel()
            del self.connections[key] 