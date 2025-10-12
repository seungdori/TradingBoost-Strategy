import asyncio
import json
import os
import ssl

import certifi
import redis.asyncio as redis
import websockets

from HYPERRSI.src.config import OKX_API_KEY, OKX_PASSPHRASE, OKX_SECRET_KEY

REDIS_URL = "redis://localhost"
OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/private"
API_KEY = OKX_API_KEY
SECRET_KEY = OKX_SECRET_KEY
PASSPHRASE = OKX_PASSPHRASE




async def authenticate(ws):
    # OKX Websocket 인증
    timestamp = str(int(asyncio.get_event_loop().time()))
    sign_str = timestamp + 'GET' + '/users/self/verify'
    import base64
    import hashlib
    import hmac

    signature = base64.b64encode(hmac.new(SECRET_KEY.encode(), sign_str.encode(), hashlib.sha256).digest()).decode()

    auth_message = {
        "op": "login",
        "args": [{
            "apiKey": API_KEY,
            "passphrase": PASSPHRASE,
            "timestamp": timestamp,
            "sign": signature
        }]
    }
    await ws.send(json.dumps(auth_message))


async def subscribe_trade(ws):
    subscribe_message = {
        "op": "subscribe",
        "args": [{"channel": "orders", "instType": "SWAP"}]
    }
    await ws.send(json.dumps(subscribe_message))


async def handle_message(message, redis_client):
    data = json.loads(message)

    if "data" in data:
        for order_info in data["data"]:
            order_id = order_info["ordId"]
            symbol = order_info["instId"]
            user_id = order_info.get("tag", "default")  # tag에 user_id 저장 가정
            status = order_info["state"]

            monitor_key = f"monitor:{user_id}:{symbol}:{order_id}"
            complete_key = f"complete:{user_id}:{symbol}:{order_id}"

            order_exists = await redis_client.exists(monitor_key)

            if order_exists:
                order_data = await redis_client.hgetall(monitor_key)
                order_type = order_data.get("order_type", "")

                if status == "filled":
                    order_data["status"] = "filled"
                    await redis_client.hmset_dict(complete_key, order_data)
                    await redis_client.delete(monitor_key)
                    print(f"{order_type} 도달 (filled)")

                elif status == "canceled":
                    order_data["status"] = "canceled"
                    await redis_client.hmset_dict(complete_key, order_data)
                    await redis_client.delete(monitor_key)
                    print(f"{order_type} 도달 실패 (canceled)")


async def ws_okx_listener():
    redis_client = redis.from_url(REDIS_URL)
    ssl_context = ssl._create_unverified_context()
    async with websockets.connect(OKX_WS_URL, ssl=ssl_context) as ws:
        await authenticate(ws)
        await subscribe_trade(ws)

        while True:
            message = await ws.recv()
            await handle_message(message, redis_client)


if __name__ == "__main__":
    asyncio.run(ws_okx_listener())
