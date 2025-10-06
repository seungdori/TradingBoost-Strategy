    #src/data_collector/websocket.py
import sys
import os

# src 폴더를 Python 모듈 경로에 추가
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import websockets
import json
import asyncio
import redis
from datetime import datetime
import ssl
import ccxt.pro as ccxt
import logging
import time
from HYPERRSI.src.core.config import settings
import pytz
from HYPERRSI.src.bot.telegram_message import send_telegram_message
import requests
SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
def fetch_usdt_swaps():
    url = "https://www.okx.com/api/v5/public/instruments?instType=SWAP"
    data = requests.get(url, timeout=10).json().get("data", [])
    return [d["instId"] for d in data if d["settleCcy"] == "USDT"]
def save_candle(key, candle_json):
    with redis.pipeline() as p:
        p.rpush(key, candle_json)
        p.ltrim(key, -10000, -1)
        p.execute()
def convert_symbol_format(symbol: str, to_okx_ws: bool = True) -> str:
    """심볼 형식을 웹소켓 양식으로 변환하는 헬퍼 함수
    
    Args:
        symbol: 변환할 심볼 문자열
        to_okx: True면 OKX 형식으로, False면 표준 형식으로 변환
    
    Examples:
        >>> convert_symbol_format("BTC-USDT-SWAP", to_okx=True)
        "BTC/USDT:USDT"
        >>> convert_symbol_format("BTC/USDT:USDT", to_okx=False)
        "BTC-USDT-SWAP"
    """
    if to_okx_ws:
        # BTC-USDT-SWAP -> BTC/USDT:USDT
        base, quote, _ = symbol.split("-")
        return f"{base}/{quote}:{quote}"
    else:
        # BTC/USDT:USDT -> BTC-USDT-SWAP
        base = symbol.split("/")[0]
        quote = symbol.split("/")[1].split(":")[0]
        return f"{base}-{quote}-SWAP"

class OKXWebSocket:
    def __init__(self):
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/business" #<-- public이 아니라, business로 해야됨. 공식문서 기준. 
        if settings.REDIS_PASSWORD:
            self.redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0, decode_responses=True, password=settings.REDIS_PASSWORD)
        else:
            self.redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0, decode_responses=True)
        self.ws = None
        self.connected = False
        self.timeframes = {
            "mark-price-candle1m": "1m",
            "mark-price-candle3m": "3m",
            "mark-price-candle5m": "5m",
            "mark-price-candle15m": "15m",
            "mark-price-candle30m": "30m",
            "mark-price-candle1H": "1h",
            "mark-price-candle4h": "4h"
        }
        self.message_counts = {
            symbol: {channel: 0 for channel in self.timeframes.keys()} 
            for symbol in SYMBOLS
        }
    async def connect(self):
        try:
            ssl_context = ssl.SSLContext()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            self.ws = await websockets.connect(self.ws_url, ssl=ssl_context)
            self.connected = True
            print("Connected to OKX WebSocket")
            
            # 구독 요청 (1분봉 예시)
            subscribe_message = {
                "op": "subscribe",
                "args": [
                    {"channel": "candle1m", "instId": "BTC-USDT-SWAP"},
                    {"channel": "candle1m", "instId": "ETH-USDT-SWAP"},
                    {"channel": "candle1m", "instId": "SOL-USDT-SWAP"}
                ]
            }
            await self.ws.send(json.dumps(subscribe_message))
            
        except Exception as e:
            print(f"Connection error: {e}")
            self.connected = False
            
            
    async def handle_message(self, message):
        print(message)
        data = json.loads(message)
        if "data" not in data:
            return

        candle_data = data["data"][0]
        channel = data["arg"]["channel"]  # ex) 'candle5m'
        symbol  = data["arg"]["instId"]   # ex) 'BTC-USDT-SWAP'
        # 현재 시간과 마지막 저장 시간 확인
        current_time = time.time()
        save_key = f"{symbol}:{channel}"
        last_save_time = self.last_save.get(save_key, 0)
        current_time_kr = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
        
        timestamp_ms = int(candle_data[0])
        candle = {
            "timestamp": timestamp_ms // 1000,
            "open": float(candle_data[1]),
            "high": float(candle_data[2]),
            "low": float(candle_data[3]),
            "close": float(candle_data[4]),
            "volume": float(candle_data[5]),
            "current_time_kr": current_time_kr
        }

        # channel => "1m","3m","5m", etc. 로 추출
        # 'candle1m' => '1m'
        tf_str = channel.replace("candle", "")  

        # Redis 키를 만들 때도 tf_str을 포함시킴
        latest_key = f"latest:{symbol}:{tf_str}" 
        self.redis_client.set(latest_key, json.dumps(candle))
        print(f"Updated {symbol} {tf_str} candle at {datetime.fromtimestamp(timestamp_ms/1000)}")
            
    async def heartbeat(self):
        """정기적으로 ping 을 보내어 연결 유지."""
        while self.connected:
            try:
                await self.ws.send("ping")
                await asyncio.sleep(20)  # 20초 간격
            except:
                self.connected = False
                break
                
    async def receive_messages(self):
        """메시지 수신 루프."""
        while self.connected:
            try:
                message = await self.ws.recv()
                if message == "pong":
                    # OKX 서버에서 pong이 오면 생략
                    continue
                await self.handle_message(message)
            except Exception as e:
                print(f"Error receiving message: {e}")
                self.connected = False
                break
                
    async def run(self):
        """메인 실행 루프"""
        try:
            while self.should_run:
                if not self.connected:
                    try:
                        await self.connect()
                        if self.connected:
                            await asyncio.gather(
                                self.receive_messages(),
                                self.heartbeat(),
                                self.log_status()
                            )
                    except Exception as e:
                        logging.error(f"Run error: {e}")
                await asyncio.sleep(5)
        except KeyboardInterrupt:
            logging.info("Received shutdown signal")
        finally:
            self.should_run = False
            await self.cleanup()


class OKXMultiTimeframeWebSocket(OKXWebSocket):
    def __init__(self):
        super().__init__()
        self.last_save = {}  # 마지막 저장 시간 추적
        self.should_run = True 
        self.save_interval = 5  # 5초마다 저장
        self.timeframes = {
            "candle1m": "1m",
            "candle3m": "3m",
            "candle5m": "5m",
            "candle15m": "15m",
            "candle30m": "30m",
            "candle1H": "1h",
            "candle4H": "4h"
        }
        self.message_counts = {
            symbol: {channel: 0 for channel in self.timeframes.keys()} 
            for symbol in SYMBOLS
        }

    async def connect(self):
        try:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            self.ws = await websockets.connect(self.ws_url, ssl=ssl_context)
            self.connected = True
            logging.info("Connected to OKX WebSocket")
            
            # 모든 심볼과 타임프레임에 대한 구독
            subscribe_args = []
            for symbol in SYMBOLS:
                for channel in self.timeframes.keys():
                    subscribe_args.append({
                        "channel": channel,
                        "instId": symbol
                    })
            
            subscribe_message = {
                "op": "subscribe",
                "args": subscribe_args
            }
            logging.info(f"Subscribing to {len(subscribe_args)} channels")
            await self.ws.send(json.dumps(subscribe_message))
            
        except Exception as e:
            logging.error(f"Connection error: {e}")
            self.connected = False
            
    async def log_status(self):
        """5분마다 구독 상태를 로깅"""
        while self.connected:
            try:
                await asyncio.sleep(300)  # 5분(300초) 대기
                now = datetime.now()
                logging.info("=== Subscription Status Report ===")
                for symbol in SYMBOLS:
                    for channel in self.timeframes.keys():
                        count = self.message_counts[symbol][channel]
                        logging.info(f"{symbol} {channel}: {count} messages received in last 5 minutes")
                        self.message_counts[symbol][channel] = 0  # 카운터 리셋
                logging.info("================================")
            except Exception as e:
                logging.error(f"Error in status logging: {e}")

    async def handle_message(self, message):
        try:
            data = json.loads(message)
            if "data" not in data:
                logging.debug(f"Invalid message: {data}")
                return

            channel = data["arg"]["channel"]
            symbol = data["arg"]["instId"]
            
            # 메시지 카운트 증가
            self.message_counts[symbol][channel] += 1

            # 현재 시간과 마지막 저장 시간 확인
            current_time = time.time()
            save_key = f"{symbol}"  # 심볼 단위로 저장 간격 체크
            last_save_time = self.last_save.get(save_key, 0)
            
            # save_interval 초가 지났을 때만 저장
            if current_time - last_save_time >= self.save_interval:
                candle_data = data["data"][0]
                timestamp_ms = int(candle_data[0])
                current_time_kr = datetime.now(pytz.timezone("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
                bar_end = candle_data[7]
                candle = {
                    "timestamp": timestamp_ms // 1000,
                    "open": float(candle_data[1]),
                    "high": float(candle_data[2]),
                    "low": float(candle_data[3]),
                    "close": float(candle_data[4]),
                    "volume": float(candle_data[5]),
                    "current_time_kr": current_time_kr,
                    "bar_end":    str(bar_end)
                }

                # Redis 파이프라인으로 한 심볼의 모든 타임프레임 데이터를 한번에 저장
                with self.redis_client.pipeline() as pipe:
                    for channel_name, tf_str in self.timeframes.items():
                        latest_key = f"latest:{symbol}:{tf_str}"
                        pipe.set(latest_key, json.dumps(candle))
                    pipe.execute()
                
                self.last_save[save_key] = current_time
                logging.debug(f"Updated {symbol} candles at {datetime.fromtimestamp(timestamp_ms/1000)}")

        except Exception as e:
            logging.error(f"Error handling message: {e}")

    async def run(self):
        while True:
            if not self.connected:
                try:
                    await self.connect()
                    if self.connected:
                        await asyncio.gather(
                            self.receive_messages(),
                            self.heartbeat(),
                            self.log_status()
                        )
                except Exception as e:
                    logging.error(f"Run error: {e}")
            
            await asyncio.sleep(5)

    async def cleanup(self):
        """웹소켓 연결 정리"""
        try:
            if self.ws:
                # 구독 해제 메시지 전송
                unsubscribe_message = {
                    "op": "unsubscribe",
                    "args": [
                        {"channel": channel, "instId": symbol}
                        for symbol in SYMBOLS
                        for channel in self.timeframes.keys()
                    ]
                }
                await self.ws.send(json.dumps(unsubscribe_message))
                await self.ws.close()
                logging.info("WebSocket connection closed cleanly")
        except Exception as e:
            logging.error(f"Error during cleanup: {e}")
        finally:
            self.connected = False
            self.ws = None
            
    async def handle_disconnect(self):
        """예기치 않은 연결 종료 처리"""
        logging.warning("WebSocket disconnected unexpectedly")
        self.connected = False
        await self.cleanup()
        
        # Redis에 연결 상태 업데이트
        try:
            self.redis_client.set("websocket_status", "disconnected")
        except Exception as e:
            logging.error(f"Error updating Redis status: {e}")

    async def receive_messages(self):
        """메시지 수신 루프"""
        while self.connected:
            try:
                message = await self.ws.recv()
                if message == "pong":
                    continue
                
                if message is None:  # 연결이 깨끗이 종료된 경우
                    logging.info("Connection closed by server")
                    break
                    
                await self.handle_message(message)
            except websockets.exceptions.ConnectionClosed:
                logging.warning("Connection closed unexpectedly")
                await self.handle_disconnect()
                break
            except Exception as e:
                logging.error(f"Error receiving message: {e}")
                await self.handle_disconnect()
                break

async def main():
    try:
        try:
            ws_client = OKXMultiTimeframeWebSocket()
            await ws_client.run()
        except Exception as e:
            send_telegram_message(f"WebSocket 오류: {e}", debug=True)
    finally:
        send_telegram_message("WebSocket 종료", debug=True)

if __name__ == "__main__":
    asyncio.run(main())