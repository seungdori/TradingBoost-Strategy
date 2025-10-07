import asyncio
import json
import random
import traceback
import websockets
import hmac
import base64
import hashlib
import time
import redis.asyncio as aioredis
from redis.asyncio import Redis
import os
from shared.config import settings

REDIS_PASSWORD = settings.REDIS_PASSWORD


if REDIS_PASSWORD:
    pool: aioredis.ConnectionPool = aioredis.ConnectionPool.from_url(
        'redis://localhost', 
        max_connections=30,
    encoding='utf-8', 
    decode_responses=True,
        password=REDIS_PASSWORD
    )
    redis_client = aioredis.Redis(connection_pool=pool)
else:
    pool = aioredis.ConnectionPool.from_url(
        'redis://localhost', 
        max_connections=30,
        encoding='utf-8', 
        decode_responses=True
    )
    redis_client = aioredis.Redis(connection_pool=pool)

async def get_redis_connection():
    return redis_client

async def get_and_cache_all_positions(uri: str, API_KEY: str, SECRET_KEY: str, PASSPHRASE: str, redis: Redis, cache_key: str) -> list | None:
    async with websockets.connect(uri) as websocket:
        # Perform authentication
        timestamp = str(int(time.time()))
        message = timestamp + 'GET' + '/users/self/verify'
        signature = base64.b64encode(hmac.new(SECRET_KEY.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()).decode('utf-8')
        
        login_data = {
            "op": "login",
            "args": [{
                "apiKey": API_KEY,
                "passphrase": PASSPHRASE,
                "timestamp": timestamp,
                "sign": signature
            }]
        }
        await websocket.send(json.dumps(login_data))
        print("Sent login data to WebSocket")
        
        login_response = await websocket.recv()
        login_response_str = login_response.decode() if isinstance(login_response, bytes) else login_response
        print(f"Login response: {login_response_str}")
        
        # Subscribe to position channel
        subscribe_data = {
            "op": "subscribe",
            "args": [{
                "channel": "positions",
                "instType": "SWAP"
            }]
        }
        await websocket.send(json.dumps(subscribe_data))
        print("Sent subscription request")
        
        subscription_response = await websocket.recv()
        subscription_response_str = subscription_response.decode() if isinstance(subscription_response, bytes) else subscription_response
        print(f"Subscription response: {subscription_response_str}")
        
        try:
            while True:
                position_data = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                position_data_str = position_data.decode() if isinstance(position_data, bytes) else position_data
                print(f"Received data: {position_data_str}")
                
                data = json.loads(position_data)
                if 'data' in data:
                    positions_data: list = data['data']
                    # Cache all position data
                    await redis.set(cache_key, json.dumps(positions_data), ex=300)  # Cache for 5 minutes
                    #print(f"Cached all position data: {positions_data}")
                    return positions_data
        except asyncio.TimeoutError:
            print("Timeout occurred while waiting for position data")
        except Exception as e:
            print(f"Error in WebSocket connection: {e}")
        
        return None




async def handle_okx(exchange, symbol, user_id, redis, cache_key):
    uri = "wss://ws.okx.com:8443/ws/v5/private"
    
    # Get user data from Redis
    user_key = f'okx:user:{user_id}'
    user_data = await redis.hgetall(user_key)
    API_KEY = user_data.get('api_key')
    SECRET_KEY = user_data.get('api_secret')
    PASSPHRASE = user_data.get('password')

    # Check if we have cached position data
    cached_data = await redis.get(cache_key)
    if not cached_data:
        # If no cached data, fetch and cache all positions
        await get_and_cache_all_positions(uri, API_KEY, SECRET_KEY, PASSPHRASE, redis, cache_key)
    
    # Get position for the specific symbol
    quantity = await get_position_for_symbol(redis, cache_key, symbol)
    return quantity

async def get_position_for_symbol(redis: Redis, cache_key: str, symbol: str) -> float:
    cached_data = await redis.get(cache_key)
    if cached_data:
        positions_data = json.loads(cached_data)
        for position in positions_data:
            if position['instId'] == symbol:
                quantity = float(position['pos'])
                print(f"{symbol}의 position : {quantity} Quantity type : {type(quantity)}")
                return quantity
    return 0.0


def process_okx_position_data(positions_data, symbol):
    #print(f"Processing position data: {positions_data}")  # Debug print
    #print(f"Type of positions_data: {type(positions_data)}")  # Debug print

    if isinstance(positions_data, str):
        try:
            positions_data = json.loads(positions_data)
        except json.JSONDecodeError:
            print("Failed to parse positions_data as JSON")
            return 0.0

    if not isinstance(positions_data, list):
        print(f"Unexpected data type for positions_data: {type(positions_data)}")
        return 0.0

    for position in positions_data:
        if not isinstance(position, dict):
            print(f"Unexpected item in positions_data: {position}")
            continue
        if 'instId' in position and position['instId'] == symbol:
            try:
                quantity = float(position['pos'])
                print(f"{symbol}의 position : {quantity} Quantity type : {type(quantity)}")
                return quantity
            except (KeyError, ValueError) as e:
                print(f"Error processing position data: {e}")
    
    print(f"No position found for symbol: {symbol}")  # Debug print
    return 0.0


# Test example
async def main():
    import GRID.instance as instance
    # Mock Redis client
    redis = await get_redis_connection()
    
    # Mock exchange object
    exchange = await instance.get_okx_instance(1709556958)
    
    # Set up test data in Redis
    user_id = '1709556958'
    user_key = f'okx:user:{user_id}'
    user_data = await redis.hgetall(user_key)
    cache_key = f'okx:positions:{user_id}'

    # Run the handle_okx function
    result = await handle_okx(exchange, 'ETHFI-USDT-SWAP', user_id, redis, cache_key)
    print(f"Final result: {result}")
    
    # Close Redis connection
    await redis.aclose()





if __name__ == "__main__":
    asyncio.run(main())