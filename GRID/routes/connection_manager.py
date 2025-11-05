import logging
import os
import traceback
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel

app = FastAPI()
import asyncio

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


from shared.config import settings

# Use shared Redis pool
from shared.database.redis_patterns import redis_context, RedisTTL
class MessageResponse(BaseModel):
    user_id: int
    messages: List[str]
    status: str


class RedisMessageManager:
    """Redis message manager using context manager pattern for proper connection handling"""

    async def get_and_clear_user_messages(self, user_id: int) -> list[str]:
        """Get and clear user messages using redis_context()"""
        key = f"user:{user_id}:messages"
        async with redis_context() as redis:
            pipe = redis.pipeline()

            # 메시지 가져오기와 TTL 확인을 파이프라인에 추가
            pipe.lrange(key, 0, -1)
            pipe.ttl(key)
            pipe.delete(key)

            # 파이프라인 실행
            results = await pipe.execute()
            messages, ttl = results[0], results[1]

            # 메시지가 있고 TTL이 유효한 경우
            if messages and ttl > 0:
                # 키를 다시 생성하고 TTL 설정
                await redis.rpush(key, *messages)
                await redis.expire(key, ttl)

            # Decode messages if they're in bytes
            decoded_messages: list[str] = [
                message.decode('utf-8') if isinstance(message, bytes) else message
                for message in messages
            ]

            return decoded_messages

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}
        self.redis_key = "connected_users"  # Redis에서 사용할 키


    async def get_user_messages(self, user_id: int) -> list[str]:
        """Get user messages using redis_context()"""
        key = f"user:{user_id}:messages"
        try:
            async with redis_context() as redis:
                messages = await redis.lrange(key, 0, -1)
                # Decode messages if they're in bytes
                decoded_messages: list[str] = [
                    message.decode('utf-8') if isinstance(message, bytes) else message
                    for message in messages
                ]
                logging.info(f" [INFO] Retrieved messages for user {user_id}: {decoded_messages}")
                return decoded_messages or []
        except Exception as e:
            logging.error(f" [ERROR] Failed to get messages for user {user_id}: {str(e)}")
            return []

    async def add_connected_user(self, user_id: int) -> None:
        """Add connected user using redis_context()"""
        try:
            async with redis_context() as redis:
                # Redis에 사용자 추가
                await redis.sadd(self.redis_key, str(user_id))
                logging.info(f"👥 [INFO] Added user {user_id} to connected users")
        except Exception as e:
            logging.error(f" [ERROR] Failed to add user {user_id} to connected users: {str(e)}")

    async def remove_connected_user(self, user_id: int) -> None:
        """Remove connected user using redis_context()"""
        try:
            async with redis_context() as redis:
                # Redis에서 사용자 제거
                await redis.srem(self.redis_key, str(user_id))
                logging.info(f"👋 [INFO] Removed user {user_id} from connected users")
        except Exception as e:
            logging.error(f" [ERROR] Failed to remove user {user_id} from connected users: {str(e)}")

    async def get_connected_users(self) -> List[int]:
        """Get all connected users using redis_context()"""
        try:
            async with redis_context() as redis:
                # Redis에서 모든 연결된 사용자 가져오기
                users = await redis.smembers(self.redis_key)
                return [int(user_id) for user_id in users] if users else []
        except Exception as e:
            logging.error(f" [ERROR] Failed to get connected users: {str(e)}")
            return []

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        try:
            await websocket.accept()
            print('🐻33',user_id)
            if user_id not in self.active_connections:
                self.active_connections[user_id] = []
            self.active_connections[user_id].append(websocket)
            # Redis에 사용자 추가
            await self.add_connected_user(user_id)
            logging.info(f" [INFO] User {user_id} connected")
        except Exception as e:
            logging.error(f" [ERROR] Failed to connect user {user_id}: {str(e)}")
            raise

    async def is_user_connected(self, user_id: int) -> bool:
        """사용자 연결 상태 확인 using redis_context()"""
        try:
            async with redis_context() as redis:
                # 메모리와 Redis 둘 다 확인
                memory_connected = user_id in self.active_connections
                redis_connected = await redis.sismember(self.redis_key, str(user_id))

                # 동기화 체크
                if memory_connected != bool(redis_connected):
                    logging.warning(f" Connection state mismatch for user {user_id}")
                    # 메모리 상태를 우선으로 Redis 상태 동기화
                    if memory_connected:
                        await redis.sadd(self.redis_key, str(user_id))
                    else:
                        await redis.srem(self.redis_key, str(user_id))

                return memory_connected

        except Exception as e:
            logging.error(f" [ERROR] Failed to check connection status: {str(e)}")
            return False

    async def get_connection_status(self, user_id: int) -> dict:
        """사용자 연결 상태 정보 조회 using redis_context()"""
        try:
            async with redis_context() as redis:
                is_connected = await self.is_user_connected(user_id)
                active_connections = len(self.active_connections.get(user_id, []))
                last_seen = await redis.get(f"user:{user_id}:last_seen")

                return {
                    "user_id": user_id,
                    "is_connected": is_connected,
                    "active_connections": active_connections,
                    "last_seen": last_seen
                }
        except Exception as e:
            logging.error(f" [ERROR] Failed to get connection status: {str(e)}")
            return {
                "user_id": user_id,
                "is_connected": False,
                "active_connections": 0,
                "last_seen": None
            }

    async def add_user_message(self, user_id: int, message: str) -> None:
        """Add user message using redis_context()"""
        key = f"user:{user_id}:messages"
        try:
            async with redis_context() as redis:
                # 메시지 저장 전 로깅
                logging.info(f" [INFO] Adding message for user {user_id}: {message}")

                # 파이프라인으로 작업 묶기
                pipe = redis.pipeline()
                await pipe.rpush(key, message)
                await pipe.expire(key, 3600)  # 1시간 유효
                await pipe.publish('messages', message)
                await pipe.execute()

                logging.info(f" [INFO] Message successfully added for user {user_id}")
        except Exception as e:
            logging.error(f" [ERROR] Failed to add message for user {user_id}: {str(e)}")
            raise

    async def send_message_to_user(self, user_id: int, message: str) -> None:
        if user_id in self.active_connections:
            failed_connections = []
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_text(message)
                    logging.info(f" [INFO] Message sent to user {user_id}: {message}")
                except Exception as e:
                    logging.error(f" [ERROR] Failed to send message to user {user_id}: {str(e)}")
                    failed_connections.append(connection)
            
            # 실패한 연결 제거
            if failed_connections:
                self.active_connections[user_id] = [
                    conn for conn in self.active_connections[user_id]
                    if conn not in failed_connections
                ]
        else:
            logging.warning(f" [WARNING] No active connection for user {user_id}")



    async def disconnect(self, websocket: WebSocket, user_id: int) -> None:
        try:
            if user_id in self.active_connections:
                self.active_connections[user_id].remove(websocket)
                # 사용자의 모든 연결이 끊어졌는지 확인
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
                    # Redis에서도 사용자 제거
                    asyncio.create_task(self.remove_connected_user(user_id))
                logging.info(f"👋 [INFO] User {user_id} disconnected")
        except Exception as e:
            logging.error(f" [ERROR] Error during disconnect for user {user_id}: {str(e)}")

    async def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Redis에서 사용자 정보를 조회하는 메서드 using redis_context()

        Args:
            user_id (int): 조회할 사용자 ID

        Returns:
            Optional[Dict[str, Any]]: 사용자 정보 또는 None
        """
        try:
            async with redis_context() as redis:
                # 예시: Redis에서 사용자 정보 조회 로직
                # 실제 구현에서는 Redis에 저장된 사용자 정보를 확인
                user_key = f"okx:user:{user_id}"
                print(f" {user_key}")
                user_info_raw = await redis.hgetall(user_key)
                print('',user_info_raw)

                # Decode bytes to strings if necessary
                if user_info_raw:
                    user_info: dict[str, Any] = {
                        k.decode('utf-8') if isinstance(k, bytes) else k:
                        v.decode('utf-8') if isinstance(v, bytes) else v
                        for k, v in user_info_raw.items()
                    }
                    return user_info
                return None
        except Exception:
            traceback.print_exc()
            return None

manager = ConnectionManager()

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int) -> None:
    print('Recivced 🍎',user_id)
    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.add_user_message(user_id, data)
            await manager.send_message_to_user(user_id, f"Message received: {data}")
    except Exception as e:
        logging.error(f" [ERROR] WebSocket error: {str(e)}")
    finally:
        await manager.disconnect(websocket, user_id)

@app.post("/add/{user_id}")
async def add_message(user_id: int, message: str) -> dict[str, str]:
    await manager.add_user_message(user_id, message)
    return {"status": "Message added successfully"}

@app.get("/get/{user_id}")
async def get_messages(user_id: int) -> dict[str, list[str]]:
    messages = await manager.get_user_messages(user_id)
    return {"messages": messages}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)