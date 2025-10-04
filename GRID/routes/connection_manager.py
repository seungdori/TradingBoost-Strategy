from fastapi import FastAPI, WebSocket, HTTPException
from typing import List, Dict, Optional, Any
import logging
import redis.asyncio as aioredis
import os
import traceback
from pydantic import BaseModel
app = FastAPI()
import asyncio

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


from shared.config import settings

REDIS_PASSWORD = settings.REDIS_PASSWORD


pool = aioredis.ConnectionPool.from_url(
    settings.REDIS_URL, 
    max_connections=30,
    encoding='utf-8', 
    decode_responses=True,
    password=REDIS_PASSWORD
)
redis_client = aioredis.Redis(connection_pool=pool)
class MessageResponse(BaseModel):
    user_id: int
    messages: List[str]
    status: str


class RedisMessageManager:
    def __init__(self):
        if REDIS_PASSWORD:
            self.redis = aioredis.from_url(settings.REDIS_URL, 
                                        max_connections=30,
                                        encoding='utf-8', 
                                        decode_responses=True,
                                        password=REDIS_PASSWORD
                                        )
        else:
            self.redis = aioredis.from_url(settings.REDIS_URL, 
                                        max_connections=30,
                                        encoding='utf-8', 
                                        decode_responses=True,
                                        )

    async def get_and_clear_user_messages(self, user_id: int):
        key = f"user:{user_id}:messages"
        pipe = self.redis.pipeline()
        
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
            await self.redis.rpush(key, *messages)
            await self.redis.expire(key, ttl)
        
        # Decode messages if they're in bytes
        decoded_messages = [
            message.decode('utf-8') if isinstance(message, bytes) else message
            for message in messages
        ]

        return decoded_messages

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}
        self.redis_key = "connected_users"  # Redis에서 사용할 키


    async def get_user_messages(self, user_id: int):
        key = f"user:{user_id}:messages"
        try:
            # redis_client가 decode_responses=True로 설정되어 있으므로
            # 추가 디코딩이 필요 없음
            messages = await redis_client.lrange(key, 0, -1)
            logging.info(f"🔍 [INFO] Retrieved messages for user {user_id}: {messages}")
            return messages or []
        except Exception as e:
            logging.error(f"🚨 [ERROR] Failed to get messages for user {user_id}: {str(e)}")
            return []

    async def add_connected_user(self, user_id: str):
        try:
            # Redis에 사용자 추가
            await redis_client.sadd(self.redis_key, str(user_id))
            logging.info(f"👥 [INFO] Added user {user_id} to connected users")
        except Exception as e:
            logging.error(f"🚨 [ERROR] Failed to add user {user_id} to connected users: {str(e)}")

    async def remove_connected_user(self, user_id: str):
        try:
            # Redis에서 사용자 제거
            await redis_client.srem(self.redis_key, str(user_id))
            logging.info(f"👋 [INFO] Removed user {user_id} from connected users")
        except Exception as e:
            logging.error(f"🚨 [ERROR] Failed to remove user {user_id} from connected users: {str(e)}")

    async def get_connected_users(self) -> List[int]:
        try:
            # Redis에서 모든 연결된 사용자 가져오기
            users = await redis_client.smembers(self.redis_key)
            return [int(user_id) for user_id in users] if users else []
        except Exception as e:
            logging.error(f"🚨 [ERROR] Failed to get connected users: {str(e)}")
            return []

    async def connect(self, websocket: WebSocket, user_id: str):
        try:
            await websocket.accept()
            print('🐻33',user_id)
            if user_id not in self.active_connections:
                self.active_connections[user_id] = []
            self.active_connections[user_id].append(websocket)
            # Redis에 사용자 추가
            await self.add_connected_user(user_id)
            logging.info(f"🚀 [INFO] User {user_id} connected")
        except Exception as e:
            logging.error(f"🚨 [ERROR] Failed to connect user {user_id}: {str(e)}")
            raise

    async def is_user_connected(self, user_id: int) -> bool:
        """사용자 연결 상태 확인"""
        try:
            # 메모리와 Redis 둘 다 확인
            memory_connected = user_id in self.active_connections
            redis_connected = await redis_client.sismember(self.redis_key, str(user_id))
            
            # 동기화 체크
            if memory_connected != bool(redis_connected):
                logging.warning(f"⚠️ Connection state mismatch for user {user_id}")
                # 메모리 상태를 우선으로 Redis 상태 동기화
                if memory_connected:
                    await redis_client.sadd(self.redis_key, str(user_id))
                else:
                    await redis_client.srem(self.redis_key, str(user_id))
            
            return memory_connected
            
        except Exception as e:
            logging.error(f"🚨 [ERROR] Failed to check connection status: {str(e)}")
            return False

    async def get_connection_status(self, user_id: int) -> dict:
        """사용자 연결 상태 정보 조회"""
        try:
            is_connected = await self.is_user_connected(user_id)
            active_connections = len(self.active_connections.get(user_id, []))
            last_seen = await redis_client.get(f"user:{user_id}:last_seen")
            
            return {
                "user_id": user_id,
                "is_connected": is_connected,
                "active_connections": active_connections,
                "last_seen": last_seen
            }
        except Exception as e:
            logging.error(f"🚨 [ERROR] Failed to get connection status: {str(e)}")
            return {
                "user_id": user_id,
                "is_connected": False,
                "active_connections": 0,
                "last_seen": None
            }

    async def add_user_message(self, user_id: int, message: str):
        key = f"user:{user_id}:messages"
        try:
            # 메시지 저장 전 로깅
            logging.info(f"📝 [INFO] Adding message for user {user_id}: {message}")
            
            # 파이프라인으로 작업 묶기
            pipe = redis_client.pipeline()
            await pipe.rpush(key, message)
            await pipe.expire(key, 3600)  # 1시간 유효
            await pipe.publish('messages', message)
            await pipe.execute()
            
            logging.info(f"✅ [INFO] Message successfully added for user {user_id}")
        except Exception as e:
            logging.error(f"🚨 [ERROR] Failed to add message for user {user_id}: {str(e)}")
            raise

    async def send_message_to_user(self, user_id: int, message: str):
        if user_id in self.active_connections:
            failed_connections = []
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_text(message)
                    logging.info(f"🚀 [INFO] Message sent to user {user_id}: {message}")
                except Exception as e:
                    logging.error(f"🚨 [ERROR] Failed to send message to user {user_id}: {str(e)}")
                    failed_connections.append(connection)
            
            # 실패한 연결 제거
            if failed_connections:
                self.active_connections[user_id] = [
                    conn for conn in self.active_connections[user_id]
                    if conn not in failed_connections
                ]
        else:
            logging.warning(f"⚠️ [WARNING] No active connection for user {user_id}")



    async def disconnect(self, websocket: WebSocket, user_id: int):
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
            logging.error(f"🚨 [ERROR] Error during disconnect for user {user_id}: {str(e)}")

    async def get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Redis에서 사용자 정보를 조회하는 메서드
        
        Args:
            user_id (int): 조회할 사용자 ID
            
        Returns:
            Optional[Dict[str, Any]]: 사용자 정보 또는 None
        """
        try:
            
            # 예시: Redis에서 사용자 정보 조회 로직
            # 실제 구현에서는 Redis에 저장된 사용자 정보를 확인
            user_key = f"okx:user:{user_id}"
            print(f"🍏🔹😇👆 {user_key}")
            user_info = await redis_client.hgetall(user_key)
            print('🍏🔹😇👆',user_info)
            return user_info if user_info else None
        except Exception:
            traceback.print_exc()
            return None

manager = ConnectionManager()

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    print('Recivced 🍎',user_id)
    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.add_user_message(user_id, data)
            await manager.send_message_to_user(user_id, f"Message received: {data}")
    except Exception as e:
        logging.error(f"🚨🚨🚨 [ERROR] WebSocket error: {str(e)}")
    finally:
        manager.disconnect(websocket, user_id)

@app.post("/add/{user_id}")
async def add_message(user_id: int, message: str):
    await manager.add_user_message(user_id, message)
    return {"status": "Message added successfully"}

@app.get("/get/{user_id}")
async def get_messages(user_id: int):
    messages = await manager.get_user_messages(user_id)
    return {"messages": messages}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)