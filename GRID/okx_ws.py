import websockets
import json
import asyncio
import hmac
import base64
import time
import hashlib
import redis.asyncio as redis
from typing import Optional, Dict, List, Set
from datetime import datetime

from redis_connection_manager import RedisConnectionManager
import aiohttp
redis_manager = RedisConnectionManager()
import os
import logging

class OKXWebsocket:
    def __init__(self, api_key: str, secret_key: str, passphrase: str, user_id: int, exchange_name: str):
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/private"
        self.rest_url = "https://www.okx.com"
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.user_id = user_id
        self.exchange_name = exchange_name
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.open_orders: Dict[str, List[Dict]] = {}
        self.running_symbols: Set[str] = set()
        self.redis: Optional[redis.Redis] = None
        self.logged_in = asyncio.Event()
        
    async def connect(self):
        self.websocket = await websockets.connect(self.ws_url)
        self.redis = await redis_manager.get_connection_async()
        await self.login()
        await self.wait_for_login()

    async def login(self):
        timestamp = str(int(time.time()))
        message = timestamp + 'GET' + '/users/self/verify'
        signature = base64.b64encode(hmac.new(self.secret_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()).decode('utf-8')
        
        login_data = {
            "op": "login",
            "args": [{
                "apiKey": self.api_key,
                "passphrase": self.passphrase,
                "timestamp": timestamp,
                "sign": signature
            }]
        }
        await self.websocket.send(json.dumps(login_data))

    async def wait_for_login(self):
        while True:
            response = await self.websocket.recv()
            data = json.loads(response)
            if data.get('event') == 'login' and data.get('code') == '0':
                self.logged_in.set()
                logging.info("Successfully logged in to OKX WebSocket")
                break
            elif data.get('event') == 'error':
                logging.error(f"Login error: {data}")
                raise Exception(f"Failed to log in: {data.get('msg')}")



    async def subscribe_orders(self, symbols: List[str]):
        await self.logged_in.wait()
        subscribe_data = {
            "op": "subscribe",
            "args": [
                {
                    "channel": "orders",
                    "instType": "SWAP",
                    "instId": symbol
                } for symbol in symbols
            ]
        }
        await self.websocket.send(json.dumps(subscribe_data))
        logging.info(f"Subscribed to orders for symbols: {symbols}")

    async def unsubscribe_orders(self, symbols: List[str]):
        await self.logged_in.wait()
        unsubscribe_data = {
            "op": "unsubscribe",
            "args": [
                {
                    "channel": "orders",
                    "instType": "SWAP",
                    "instId": symbol
                } for symbol in symbols
            ]
        }
        await self.websocket.send(json.dumps(unsubscribe_data))
        logging.info(f"Unsubscribed from orders for symbols: {symbols}")


    async def process_order(self, order):
        
        order_id = order['ordId']
        symbol = order['instId']
        status = order['state']
        cancel_source = order.get('cancelSource')
        print(f"symbol: {symbol}, order_id : {order_id},  status: {status}")
        if not all([order_id, symbol, status]):
              logging.warning(f"Incomplete order data received: {order}")
              return
        current_minutes = datetime.now().minute
        current_seconds = datetime.now().second
        if current_seconds == 0:
            logging.info(f"Processing order: ID: {order_id}, Symbol: {symbol}, Status: {status}")
  
        if status == 'live':
            if symbol not in self.open_orders:
                self.open_orders[symbol] = []
            self.open_orders[symbol].append(order)
            logging.info(f"New open order for {symbol}: Order ID: {order_id}")
        elif status == 'partially_filled':
            # 부분 체결된 주문도 여전히 오픈 상태로 간주
            if symbol not in self.open_orders:
                self.open_orders[symbol] = []
            # 기존 주문 업데이트 또는 새로 추가
            updated = False
            for i, existing_order in enumerate(self.open_orders[symbol]):
                if existing_order['ordId'] == order_id:
                    self.open_orders[symbol][i] = order
                    updated = True
                    break
            if not updated:
                self.open_orders[symbol].append(order)
            logging.info(f"Updated partially filled order for {symbol}: Order ID: {order_id}")
        elif status in ['filled', 'canceled']:
            if symbol in self.open_orders:
                self.open_orders[symbol] = [o for o in self.open_orders[symbol] if o['ordId'] != order_id]
                if status == 'filled':
                    logging.info(f"Order {order_id} for {symbol} has been filled.")
                else:
                    cancel_reason = "User cancelled" if cancel_source == '1' else f"Cancelled by source {cancel_source}"
                    logging.info(f"Order {order_id} for {symbol} has been canceled. Reason: {cancel_reason}")
        
        logging.info(f"Current open orders for {symbol}: {len(self.open_orders.get(symbol, []))}")


    async def update_running_symbols(self):
        user_key = f'{self.exchange_name}:user:{self.user_id}'
        is_running = await self.redis.hget(user_key, 'is_running')
        
        running_symbols_json = await self.redis.hget(user_key, 'running_symbols')
        print(running_symbols_json)
        if not is_running or is_running.decode('utf-8') != '1':
            logging.info("The User is not running. Skipping symbol update.")
            return
        if running_symbols_json:
            new_running_symbols = set(json.loads(running_symbols_json.decode('utf-8')))
        else:
            new_running_symbols = set()
        
        symbols_to_subscribe = new_running_symbols - self.running_symbols
        symbols_to_unsubscribe = self.running_symbols - new_running_symbols
        
        if symbols_to_subscribe:
            await self.subscribe_orders(list(symbols_to_subscribe))
        if symbols_to_unsubscribe:
            await self.unsubscribe_orders(list(symbols_to_unsubscribe))
        
        self.running_symbols = new_running_symbols
        logging.info(f"Updated running symbols: {self.running_symbols}")


    async def periodic_symbol_update(self):
        while True:
            await self.update_running_symbols()
            await asyncio.sleep(23)  # Wait for 60 seconds before next update

    async def handle_message(self):
        while True:
            try:
                message = await self.websocket.recv()
                data = json.loads(message)
                #print(data)
                if 'event' in data and data['event'] == 'subscribe':
                    logging.info(f"Successfully subscribed to {data['arg']['channel']} for {data['arg']['instId']}")
                elif 'data' in data:
                    for order in data['data']:
                        await self.process_order(order)
            except websockets.exceptions.ConnectionClosed:
                logging.warning("WebSocket connection closed. Attempting to reconnect...")
                await self.connect()
                await self.subscribe_orders(list(self.running_symbols))
            except Exception as e:
                logging.error(f"Error in handle_message: {e}")
                await asyncio.sleep(5)

    async def process_position(self, position):
        symbol = position['instId'].replace('-SWAP', '')
        pos_side = position['posSide']
        pos_size = float(position['pos'])
        avg_price = float(position['avgPx'])
        unrealized_pnl = float(position['upl'])
        
        self.positions[symbol] = {
            'side': pos_side,
            'size': pos_size,
            'avg_price': avg_price,
            'unrealized_pnl': unrealized_pnl
        }
        
        print(f"Updated position for {symbol}: Side: {pos_side}, Size: {pos_size}, Avg Price: {avg_price}, Unrealized PNL: {unrealized_pnl}")

    async def get_positions(self):
        return self.positions

    async def fetch_initial_positions(self):
        endpoint = "/api/v5/account/positions"
        method = "GET"
        timestamp = str(int(time.time()))
        
        message = timestamp + method + endpoint
        signature = base64.b64encode(hmac.new(self.secret_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()).decode('utf-8')
        
        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.rest_url}{endpoint}", headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    for position in data['data']:
                        await self.process_position(position)
                else:
                    print(f"Failed to fetch initial positions. Status code: {response.status}")





class ExchangeInstanceManager:
    def __init__(self):
        self.redis = None

    async def initialize(self):
        self.redis = await redis_manager.get_connection_async()

    async def get_exchange_instance(self, exchange_name: str, user_id: int):
        if not self.redis:
            await self.initialize()

        user_key = f'{exchange_name}:user:{user_id}'
        user_data = await self.redis.hgetall(user_key)


        if user_data and b'api_key' in user_data:
            return OKXWebsocket(
                api_key=user_data[b'api_key'].decode(),
                secret_key=user_data[b'api_secret'].decode(),
                passphrase=user_data[b'password'].decode(),
                user_id=user_id,
                exchange_name=exchange_name
            )
        else:
            logging.error(f"No API keys found for user {user_id}")
            return None

#================================================================================================

    async def run_with_retry(self, max_retries: int = 5, retry_delay: int = 30):
        retries = 0
        while retries < max_retries:
            try:
                await self.connect()
                logging.info("Connected to OKX WebSocket")
                
                await self.update_running_symbols()
                logging.info("Initial running symbols updated")
                
                symbol_update_task = asyncio.create_task(self.periodic_symbol_update())
                
                await self.handle_message()
            except Exception as e:
                logging.error(f"Error in OKX WebSocket: {e}")
                retries += 1
                if retries < max_retries:
                    logging.info(f"Retrying in {retry_delay} seconds... (Attempt {retries}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                else:
                    logging.error("Max retries reached. Stopping OKX WebSocket.")
                    break
            finally:
                if 'symbol_update_task' in locals():
                    symbol_update_task.cancel()
                    try:
                        await symbol_update_task
                    except asyncio.CancelledError:
                        pass

async def run_okx_websocket(user_id: int):
    exchange_name = 'okx'
    instance_manager = ExchangeInstanceManager()
    okx_ws = await instance_manager.get_exchange_instance(exchange_name, user_id)
    
    if okx_ws:
        await okx_ws.run_with_retry()
    else:
        logging.error("Failed to initialize OKX WebSocket")
        
#================================================================================================


async def main(user_id: int, exchange_name: str):
    try:
        instance_manager = ExchangeInstanceManager()
        okx_ws = await instance_manager.get_exchange_instance(exchange_name, user_id)
        print(okx_ws)
        if okx_ws:
            await okx_ws.connect()
            print("Connected to OKX WebSocket")
            # Initial update of running symbols
            await okx_ws.update_running_symbols()
            print("Initial running symbols updated")
            # Start periodic symbol updates
            asyncio.create_task(okx_ws.periodic_symbol_update())
            # Start message handling
            await okx_ws.handle_message()
        else:
            logging.error("Failed to initialize OKX WebSocket")
    except Exception as e:
        logging.error(f"Error in main: {e}")

if __name__ == "__main__":
    asyncio.run(main(user_id=1234, exchange_name='okx'))