from fastapi import APIRouter, Query, HTTPException, WebSocket, WebSocketDisconnect
from GRID.dtos import user
from GRID.version import __version__
from GRID.routes.connection_manager import ConnectionManager, RedisMessageManager
import os
import redis.asyncio as aioredis
import json
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union, cast
from datetime import datetime, timedelta

router = APIRouter(prefix="/logs", tags=["logs"])
manager = ConnectionManager()

import logging
from shared.config import settings

REDIS_PASSWORD = settings.REDIS_PASSWORD

if REDIS_PASSWORD:
    pool: aioredis.ConnectionPool = aioredis.ConnectionPool.from_url(
        settings.REDIS_URL,
        max_connections=30,
        encoding='utf-8',
        decode_responses=True,
        password=REDIS_PASSWORD
    )
    redis_client: aioredis.Redis = cast(aioredis.Redis, aioredis.Redis(connection_pool=pool))
else:
    pool = aioredis.ConnectionPool.from_url(
        settings.REDIS_URL,
        max_connections=30,
        encoding='utf-8',
        decode_responses=True
    )
    redis_client = cast(aioredis.Redis, aioredis.Redis(connection_pool=pool))
class ConnectedUsersResponse(BaseModel):
    connected_users: List[int]
    count: int  # List[int]가 아닌 int로 수정

class LogMessage(BaseModel):
    message: str = Field(..., description="Message to be logged")
    timestamp: Optional[datetime] = Field(default_factory=datetime.utcnow)
    
class LogResponse(BaseModel):
    message: str
    status: str
    user_id: str | int 
    timestamp: datetime = Field(default_factory=datetime.utcnow)


TRADING_SERVER_URL = os.getenv('TRADING_SERVER_URL', 'localhost:8000')

async def get_redis_connection() -> aioredis.Redis:
    if REDIS_PASSWORD:
        return await aioredis.from_url(settings.REDIS_URL, encoding='utf-8', decode_responses=True, password=REDIS_PASSWORD)
    else:
        return await aioredis.from_url(settings.REDIS_URL, encoding='utf-8', decode_responses=True)

def convert_date_to_timestamp(date_str: str | None) -> float | None:
    """Convert date string to Unix timestamp"""
    if date_str is None:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').timestamp()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")


@router.get("/trading_volumes")
async def get_trading_volumes(
    user_id: str,
    symbol: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    exchange_name: str = 'okx'
) -> dict[str, Any]:
    print(f"Received user_id: {user_id}, type: {type(user_id)}")
    int(user_id)
    # 날짜 형식 검증 추가
    try:
        if start_date:
            datetime.strptime(start_date, '%Y-%m-%d')
        if end_date:
            datetime.strptime(end_date, '%Y-%m-%d')
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    redis = await get_redis_connection()
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    start_ts = convert_date_to_timestamp(start_date)
    end_ts = convert_date_to_timestamp(end_date)

    # Ensure timestamps are valid floats
    if start_ts is None or end_ts is None:
        raise HTTPException(status_code=400, detail="Invalid date range")

    if symbol is None:
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = json.loads(await redis.hget(user_key, 'data') or '{}')
        symbols = set(user_data.get('running_symbols', []))
        results: dict[str, Any] = {}
        for sym in symbols:
            user_symbol_key = f'{exchange_name}:user:{user_id}:volume:{sym}'
            volumes = await redis.zrangebyscore(user_symbol_key, start_ts, end_ts, withscores=True)
            results[sym] = {k: v for k, v in volumes}
        return {"user_id": user_id, "volumes": results}
    else:
        user_symbol_key = f'{exchange_name}:user:{user_id}:volume:{symbol}'
        volumes = await redis.zrangebyscore(user_symbol_key, start_ts, end_ts, withscores=True)
        return {"user_id": user_id, "symbol": symbol, "volumes": {k: v for k, v in volumes}}

@router.get("/total_trading_volume")
async def get_total_trading_volume(
    user_id: str = Query(..., description="User ID"),
    symbol: str = Query(..., description="Trading symbol"),
    start_date: str | None = None,
    end_date: str | None = None,
    exchange_name: str = 'okx'
) -> dict[str, Any]:
    int(user_id)
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    start_ts = convert_date_to_timestamp(start_date)
    end_ts = convert_date_to_timestamp(end_date)

    # Ensure timestamps are valid floats
    if start_ts is None or end_ts is None:
        raise HTTPException(status_code=400, detail="Invalid date range")

    redis = await get_redis_connection()
    user_symbol_key = f'{exchange_name}:user:{user_id}:volume:{symbol}'
    volumes = await redis.zrangebyscore(user_symbol_key, start_ts, end_ts, withscores=True)
    total_volume = sum(float(volume) for _, volume in volumes)

    return {
        "user_id": user_id,
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "total_volume": total_volume
    }


@router.get("/trading_pnl")
async def get_trading_pnl(
    user_id: str,
    symbol: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    exchange_name: str = 'okx'
) -> dict[str, Any]:
    int(user_id)
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    start_ts = convert_date_to_timestamp(start_date)
    end_ts = convert_date_to_timestamp(end_date)

    # Ensure timestamps are valid floats
    if start_ts is None or end_ts is None:
        raise HTTPException(status_code=400, detail="Invalid date range")

    redis = await get_redis_connection()

    if symbol is None:
        user_key = f'{exchange_name}:user:{user_id}'
        user_data = json.loads(await redis.hget(user_key, 'data') or '{}')
        symbols = set(user_data.get('running_symbols', []))
        results: dict[str, Any] = {}

        for sym in symbols:
            user_symbol_key = f'{exchange_name}:user:{user_id}:pnl:{sym}'
            pnl_data = await redis.zrangebyscore(user_symbol_key, start_ts, end_ts, withscores=True)
            results[sym] = {k: v for k, v in pnl_data}

        return {"user_id": user_id, "pnl": results}
    else:
        user_symbol_key = f'{exchange_name}:user:{user_id}:pnl:{symbol}'
        pnl_data = await redis.zrangebyscore(user_symbol_key, start_ts, end_ts, withscores=True)
        return {"user_id": user_id, "symbol": symbol, "pnl": {k: v for k, v in pnl_data}}
    
    
@router.get("/total_trading_pnl")
async def get_total_trading_pnl(
    user_id: str,
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    exchange_name: str = 'okx'
) -> dict[str, Any]:
    int(user_id)
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    start_ts = convert_date_to_timestamp(start_date)
    end_ts = convert_date_to_timestamp(end_date)

    # Ensure timestamps are valid floats
    if start_ts is None or end_ts is None:
        raise HTTPException(status_code=400, detail="Invalid date range")

    redis = await get_redis_connection()
    user_symbol_key = f'{exchange_name}:user:{user_id}:pnl:{symbol}'
    pnl_data = await redis.zrangebyscore(user_symbol_key, start_ts, end_ts, withscores=True)
    total_pnl = sum(float(pnl) for _, pnl in pnl_data)

    return {
        "user_id": user_id,
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "total_pnl": total_pnl
    }

# 웹소켓 연결 엔드포인트
@router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str) -> None:
    print('⚡️⚡️😈 : ', user_id)
    user_id_int = int(user_id)
    await manager.connect(websocket, user_id_int)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.add_user_message(user_id_int, data)
            await manager.send_message_to_user(user_id_int, f"{data}")
    except WebSocketDisconnect:
        await manager.disconnect(websocket, user_id_int)
    except Exception as e:
        logging.error(f"🚨 [ERROR] WebSocket error for user {user_id}: {str(e)}")
        await manager.disconnect(websocket, user_id_int)

# FastAPI 라우터에서 메시지 전송을 위한 엔드포인트 예시
@router.post("/send/{user_id}")
async def send_message_to_user(user_id: int, message: str) -> dict[str, str]:
    await manager.send_message_to_user(user_id, message)
    return {"status": "success"}

# 브로드캐스트 메시지 전송을 위한 엔드포인트 예시
@router.post("/broadcast")
async def broadcast_message(message: str) -> dict[str, str]:
    # Note: broadcast method needs to be implemented in ConnectionManager
    # For now, we'll send to all connected users
    connected_users = await manager.get_connected_users()
    for user_id in connected_users:
        try:
            await manager.send_message_to_user(user_id, message)
        except Exception as e:
            logging.error(f"Failed to broadcast to user {user_id}: {e}")
    return {"status": "success"}

async def check_user_exists(user_id: int | str) -> bool:
    """
    사용자 존재 여부를 확인하는 함수

    Args:
        user_id (int | str): 확인할 사용자 ID

    Returns:
        bool: 사용자 존재 여부
    """
    # 예시: Redis에서 사용자 정보 확인
    user_id_int = int(user_id) if isinstance(user_id, str) else user_id
    user_exists = await manager.get_user_info(user_id_int) is not None
    print(f"User {user_id} exists: {user_exists}")
    return user_exists


class MessageResponse(BaseModel):
    user_id: int | str
    messages: List[str]
    status: str = "success"

@router.get("/ws/docs", tags=["logs"])
async def get_websocket_docs(user_id: int) -> dict[str, Any]:
    f"""
    WebSocket 연결 정보:

    웹소켓 URL: ws://{TRADING_SERVER_URL}/logs/ws/{user_id}

    사용 방법:
    1. user_id를 지정하여 웹소켓에 연결
    2. 텍스트 메시지 송수신 가능
    """
    return {
        "websocket_url": f"{TRADING_SERVER_URL}/logs/ws/{user_id}",
        "description": "Websocket Endpoint",
        "parameters": {
            "user_id": "User ID"
        }
    }

# FastAPI 라우터 수정
@router.get("/ws/users", response_model=ConnectedUsersResponse)
async def get_connected_users() -> ConnectedUsersResponse:
    """
    현재 연결된 모든 사용자 목록을 조회합니다.
    Returns:
        ConnectedUsersResponse: 연결된 사용자 ID 목록과 총 수
    """
    try:
        connected_users = await manager.get_connected_users()
        return ConnectedUsersResponse(
            connected_users=connected_users,
            count=len(connected_users)
        )
    except Exception as e:
        logging.error(f"🚨 [ERROR] Failed to get connected users: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve connected users"
        )
        
@router.post("/ws/{user_id}", response_model=LogResponse)
async def add_log_endpoint(
    user_id: Union[str, int], 
    log_message: str = Query(
        ..., 
        description="Message to be logged",
        min_length=1,
        max_length=1000
    )
) -> LogResponse:
    """
    사용자 메시지를 추가하고 웹소켓으로 브로드캐스트하는 엔드포인트
    
    Args:\n
        user_id (int): 사용자 ID\n
        log_message (str): 저장할 메시지\n
    
    Returns:\n
        LogResponse: 메시지 저장 결과를 포함한 응답\n
    
    Raises:\n
        HTTPException:\n
            - 404: 사용자가 존재하지 않는 경우\n
            - 422: 메시지 형식이 잘못된 경우\n
            - 500: Redis 작업 실패 시\n
    """
    try:
        # Convert user_id to int
        user_id_int = int(user_id) if isinstance(user_id, str) else user_id

        # 로깅 시작
        logging.info(f"📝 [LOG] Adding message for user {user_id}: {log_message}")

        # 사용자 존재 여부 확인
        user_exists = await check_user_exists(user_id)
        if not user_exists:
            logging.warning(f"⚠️ [WARNING] User {user_id} not found")
            raise HTTPException(
                status_code=404,
                detail=f"User {user_id} not found"
            )

        # 메시지 형식 검증
        if not log_message.strip():
            raise HTTPException(
                status_code=422,
                detail="Message cannot be empty"
            )

        # 타임스탬프 추가
        timestamp = datetime.utcnow()
        formatted_message = f"User {user_id}: {log_message}"

        # Redis에 메시지 저장
        try:
            await manager.add_user_message(user_id_int, formatted_message)
            logging.info(f"✅ [SUCCESS] Message saved for user {user_id}")
        except Exception as redis_error:
            logging.error(f"🚨 [ERROR] Redis operation failed: {str(redis_error)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save message: {str(redis_error)}"
            )

        # 웹소켓으로 메시지 전송
        try:
            await manager.send_message_to_user(user_id_int, formatted_message)
            logging.info(f"📢 [BROADCAST] Message sent to user {user_id}")
        except Exception as ws_error:
            logging.warning(f"⚠️ [WARNING] Failed to broadcast message: {str(ws_error)}")
            # 웹소켓 전송 실패는 경고로 처리하고 계속 진행

        # 응답 생성
        response = LogResponse(
            message="Log message processed successfully",
            status="success",
            user_id=user_id,
            timestamp=timestamp
        )
        
        logging.info(f"✨ [COMPLETE] Message processing completed for user {user_id}")
        return response

    except HTTPException as he:
        # HTTP 예외는 그대로 전달
        raise he
    except Exception as e:
        # 예상치 못한 오류
        error_msg = f"Unexpected error processing log message: {str(e)}"
        logging.error(f"🚨 [ERROR] {error_msg}")
        raise HTTPException(
            status_code=500,
            detail=error_msg
        )

# 메시지 삭제 엔드포인트 추가
@router.delete("/ws/{user_id}/messages")
async def delete_user_messages(user_id: Union[str, int]) -> dict[str, str]:
    """
    사용자의 모든 메시지를 삭제하는 엔드포인트

    Args:
        user_id (int): 메시지를 삭제할 사용자 ID
    """
    try:
        key = f"user:{user_id}:messages"
        if redis_client:
            await redis_client.delete(key)
        return {"status": "success", "message": f"All messages deleted for user {user_id}"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete messages: {str(e)}"
        )


@router.get("/ws/users/{user_id}/status")
async def get_user_connection_status(user_id: int | str) -> dict[str, Any]:
    """
    특정 사용자의 연결 상태를 확인합니다.
    """
    try:
        user_id_int = int(user_id) if isinstance(user_id, str) else user_id
        status = await manager.get_connection_status(user_id_int)
        logging.info(f"📊 Connection status for user {user_id}: {status}")
        return status
    except Exception as e:
        logging.error(f"🚨 [ERROR] Failed to get user status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get status for user {user_id}"
        )

@router.get("/ws/{user_id}", response_model=MessageResponse)
async def get_user_messages(user_id: int) -> MessageResponse:
    """
    사용자의 메시지를 조회하고 삭제하는 엔드포인트
    
    Args:
        user_id (int): 사용자 ID
    
    Returns:
        MessageResponse: 사용자 메시지 정보를 포함한 응답
        
    Raises:
        HTTPException: 
            - 404: 사용자가 존재하지 않는 경우\n
            - 500: Redis 작업 실패 시
    """
    try:
        # 사용자 존재 여부 확인
        user_exists = await check_user_exists(user_id)
        if not user_exists:
            raise HTTPException(
                status_code=404,
                detail=f"{user_id}의 OKX UID 사용자가 존재하지 않습니다."
            )

        manager = RedisMessageManager()
        messages = await manager.get_and_clear_user_messages(user_id)
        print("[GET USER MESSAGES]", messages)
        
        if not messages:  # 메시지가 없는 경우
            return MessageResponse(
                user_id=user_id,
                messages=[],
                status="success"
            )
        
        return MessageResponse(
            user_id=user_id,
            messages=messages,
            status="success"
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve messages: {str(e)}"
        )


# 메시지 조회 엔드포인트 추가
@router.get("/ws/{user_id}/messages")
async def get_user_messages_endpoint(
    user_id: int,
    limit: int = Query(default=50, ge=1, le=100)
) -> dict[str, Any]:
    """
    사용자의 최근 메시지를 조회하는 엔드포인트

    Args:
        user_id (int): 메시지를 조회할 사용자 ID
        limit (int): 조회할 최대 메시지 수 (기본값: 50)
    """
    try:
        messages = await manager.get_user_messages(user_id)
        return {
            "user_id": user_id,
            "messages": messages[-limit:],
            "total_count": len(messages)
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve messages: {str(e)}"
        )

@router.post("/ws/users/{user_id}/sync")
async def force_sync_connection_state(user_id: int) -> dict[str, str]:
    """연결 상태를 강제로 동기화합니다."""
    await manager.is_user_connected(user_id)
    return {"message": "Connection state synchronized"}