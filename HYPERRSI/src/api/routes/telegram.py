from fastapi import APIRouter, HTTPException, Query, Path, WebSocket, WebSocketDisconnect
from typing import Optional, List
from pydantic import BaseModel, Field
from shared.logging import get_logger

from shared.helpers.user_id_converter import get_telegram_id_from_uid
from HYPERRSI.src.services.timescale_service import TimescaleUserService
import datetime
import asyncio
import telegram
import os
import json

logger = get_logger(__name__)

# Dynamic redis_client access
def _get_redis_client():
    """Get redis_client dynamically to avoid import-time errors"""
    from HYPERRSI.src.core import database as db_module
    return db_module.redis_client

redis_client = _get_redis_client()

# ✅ FastAPI 라우터 설정
router = APIRouter(prefix="/telegram", tags=["Telegram Message"])

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# 응답 모델
class TelegramResponse(BaseModel):
    """텔레그램 메시지 전송 응답 모델"""
    status: str = Field(..., example="success", description="요청 처리 상태")
    message: str = Field(..., example="메시지가 성공적으로 전송되었습니다.", description="응답 메시지")

# 에러 응답 모델
class ErrorResponse(BaseModel):
    """에러 응답 모델"""
    detail: str = Field(..., example="메시지 전송 실패", description="에러 상세 내용")

class LogEntry(BaseModel):
    """로그 항목 모델"""
    timestamp: str
    user_id: str
    symbol: Optional[str] = None
    event_type: str
    status: str
    category: str
    strategy_type: str
    content: str
    message_id: Optional[int] = None
    error_message: Optional[str] = None

    class Config:
        populate_by_name = True
        aliases = {
            "event_type": "type"
        }

class TelegramLogResponse(BaseModel):
    """텔레그램 로그 조회 응답 모델"""
    logs: List[LogEntry]
    total: int

# Redis 키 상수
LOG_SET_KEY = "telegram:logs:{user_id}"
LOG_SET_KEY_BY_OKX = "telegram:logs:by_okx_uid:{okx_uid}"
LOG_CHANNEL_KEY = "telegram:log_channel:{user_id}"

# 동시성 제어를 위한 세마포어
semaphore = asyncio.Semaphore(3)

@router.post(
    "/messages/{user_id}",
    response_model=TelegramResponse,
    responses={
        200: {
            "description": "메시지 전송 성공",
            "model": TelegramResponse
        },
        400: {
            "description": "잘못된 요청",
            "model": ErrorResponse
        },
        429: {
            "description": "메시지 전송 제한 초과",
            "model": ErrorResponse
        },
        500: {
            "description": "서버 내부 오류",
            "model": ErrorResponse
        }
    },
    summary="텔레그램 메시지 전송",
    description="""
    지정된 사용자에게 텔레그램 메시지를 전송합니다.
    
    - 최대 3회 재시도
    - Flood control 감지 및 처리
    
    **주의사항:**
    - 사용자 ID는 유효한 텔레그램 chat_id여야 합니다
    - 메시지는 비어있지 않아야 합니다
    """
)
async def send_message(
    user_id: str = Path(
        ..., 
        description="메시지를 받을 사용자의 텔레그램 ID",
        example=123456789
    ),
    message: str = Query(
        ..., 
        description="전송할 메시지 내용",
        min_length=1,
        max_length=4096,
        example="거래가 체결되었습니다."
    )
):
    try:
        user_id = await get_telegram_id_from_uid(user_id, TimescaleUserService)
        if not message.strip():
            raise HTTPException(
                status_code=400,
                detail="메시지 내용이 비어있습니다."
            )

        async with semaphore:
            max_retries = 3
            retry_delay = 1
            success = False
            
            bot = telegram.Bot(TELEGRAM_BOT_TOKEN)

            for attempt in range(max_retries):
                try:
                    await bot.send_message(
                        chat_id=str(user_id),
                        text=message,
                        parse_mode='HTML'  # HTML 포맷팅 지원
                    )
                    success = True
                    break

                except telegram.error.Unauthorized:
                    raise HTTPException(
                        status_code=400,
                        detail="봇이 해당 사용자에게 메시지를 보낼 권한이 없습니다."
                    )

                except telegram.error.BadRequest as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"잘못된 요청: {str(e)}"
                    )

                except telegram.error.RetryAfter as e:
                    raise HTTPException(
                        status_code=429,
                        detail=f"메시지 전송 제한 초과. {e.retry_after}초 후 다시 시도하세요."
                    )

                except telegram.error.TelegramError as e:
                    logger.error(f"Telegram error on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        
                except Exception as e:
                    logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)

            if not success:
                raise HTTPException(
                    status_code=500,
                    detail="최대 재시도 횟수를 초과했습니다."
                )

            return TelegramResponse(
                status="success",
                message="메시지가 성공적으로 전송되었습니다."
            )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Error sending telegram message: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"메시지 전송 중 오류가 발생했습니다: {str(e)}"
        )

@router.get(
    "/logs/{user_id}",
    response_model=TelegramLogResponse,
    summary="텔레그램 메시지 로그 조회",
    description="사용자별 텔레그램 메시지 전송/수정 로그를 조회합니다.",
    responses={
        200: {"description": "로그 조회 성공"},
        404: {"description": "사용자 로그 없음"},
        500: {"description": "서버 내부 오류"}
    }
)
async def get_telegram_logs(
    user_id: str = Path(..., description="로그를 조회할 사용자의 텔레그램 ID 또는 OKX UID"),
    limit: int = Query(100, description="조회할 로그 개수 제한", ge=1, le=1000),
    offset: int = Query(0, description="조회 시작 오프셋", ge=0),
    category: Optional[str] = Query(None, description="필터링할 로그 카테고리 (e.g., start, stop, entry)"),
    strategy_type: Optional[str] = Query(None, description="필터링할 전략 타입 (e.g., HyperRSI)")
):
    """지정된 사용자의 텔레그램 메시지 로그를 시간 역순으로 조회합니다."""
    
    print(f"OG user_id: {user_id}")
    
    # user_id를 문자열로 변환 (int일 수도 있으므로)
    user_id_str = str(user_id)
    
    # OKX UID 형식인지 Telegram ID 형식인지 구분
    # OKX UID는 일반적으로 18자리 이상
    if len(user_id_str) >= 18:
        # OKX UID로 조회
        log_set_key = LOG_SET_KEY_BY_OKX.format(okx_uid=user_id_str)
        print(f"OKX UID로 조회: {user_id_str}")
    else:
        # Telegram ID로 조회 (18자리 미만인 경우)
        telegram_id = await get_telegram_id_from_uid(user_id_str, TimescaleUserService)
        log_set_key = LOG_SET_KEY.format(user_id=telegram_id)
        print(f"telegram id: {telegram_id}")
        user_id = telegram_id
    
    print(f"log_set_key: {log_set_key}")
    try:
        # Sorted Set에서 점수(타임스탬프) 기준 역순으로 로그 데이터 조회
        # ZREVRANGE 사용 (start=offset, end=offset + limit - 1)
        log_data = await redis_client.zrevrange(
            log_set_key,
            start=offset,
            end=offset + limit - 1
        )

        # 전체 로그 개수 조회
        total_logs = await redis_client.zcard(log_set_key)

        if not log_data:
            return TelegramLogResponse(logs=[], total=0)

        #print(f"log_data: {log_data}")  
        # JSON 문자열을 LogEntry 모델 객체로 변환
        logs = []
        for item in log_data:
            try:
                log_entry_dict = json.loads(item)
                
                # 필수 필드 검증
                required_fields = ["timestamp", "user_id", "status", "category", "strategy_type", "content"]
                missing_fields = [field for field in required_fields if field not in log_entry_dict]
                
                # 데이터 타입 조정 - user_id는 문자열로 유지 (LogEntry 모델에 맞춤)
                if "user_id" in log_entry_dict and not isinstance(log_entry_dict["user_id"], str):
                    log_entry_dict["user_id"] = str(log_entry_dict["user_id"])
                
                # type 필드가 있고 event_type 필드가 없는 경우 매핑
                if "type" in log_entry_dict and "event_type" not in log_entry_dict:
                    log_entry_dict["event_type"] = log_entry_dict.pop("type")
                elif "type" not in log_entry_dict and "event_type" not in log_entry_dict:
                    missing_fields.append("event_type/type")
                
                if missing_fields:
                    logger.warning(f"Log entry missing required fields: {', '.join(missing_fields)}. Skipping this entry.")
                    continue
                
                # '에러', 'error', 'DEBUG' 단어가 포함된 로그는 제외
                content = log_entry_dict.get("content", "")
                if (isinstance(content, str) and 
                    not any(keyword.lower() in content.lower() for keyword in ["에러", "error", "debug"])):
                    logs.append(LogEntry(**log_entry_dict))
                #else:
                #    logger.debug(f"로그 필터링: '에러/error/DEBUG' 키워드 포함된 로그 제외됨")
                    
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode log entry for user {user_id}: {item}")
            except Exception as e:
                logger.error(f"Error processing log entry for user {user_id}: {e}, data: {item}")

        # 카테고리 필터링 (요청된 경우)
        if category:
            logs = [log for log in logs if log.category == category]

        # 전략 타입 필터링 (요청된 경우)
        if strategy_type:
            logs = [log for log in logs if log.strategy_type == strategy_type]

        # 필터링 후 전체 개수는 필터링 전 total_logs를 유지할지, 필터링된 개수를 반환할지 결정 필요
        # 여기서는 필터링 전 전체 개수를 total로 반환
        return TelegramLogResponse(logs=logs, total=total_logs)
    
    except Exception as e:
        logger.error(f"Error retrieving logs for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="로그 조회 중 오류가 발생했습니다.")

@router.websocket("/ws/logs/{user_id}")
async def websocket_log_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket을 통해 실시간 텔레그램 로그를 스트리밍합니다."""
    await websocket.accept()
    user_id = await get_telegram_id_from_uid(user_id, TimescaleUserService)
    log_channel = LOG_CHANNEL_KEY.format(user_id=user_id)
    pubsub = redis_client.pubsub()
    

    try:
        await pubsub.subscribe(log_channel)
        logger.info(f"WebSocket client connected for user {user_id} logs.")

        # 연결 시 최근 로그 몇 개 전송 (선택 사항)
        # recent_logs_resp = await get_telegram_logs(user_id=user_id, limit=10, offset=0)
        # await websocket.send_json({"event_type": "history", "data": recent_logs_resp.dict()})

        while True:
            # Redis Pub/Sub 메시지 수신 대기 (타임아웃 설정)
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=60) # 60초 타임아웃
            if message and message.get("event_type") == "message":
                log_data = message["data"]
                try:
                    log_entry = json.loads(log_data)
                    
                    # 필수 필드 검증
                    required_fields = ["timestamp", "user_id", "status", "category", "strategy_type", "content"]
                    missing_fields = [field for field in required_fields if field not in log_entry]
                    
                    # 데이터 타입 조정 - user_id는 문자열로 유지 (LogEntry 모델에 맞춤)
                    if "user_id" in log_entry and not isinstance(log_entry["user_id"], str):
                        log_entry["user_id"] = str(log_entry["user_id"])
                    
                    # type 필드가 있고 event_type 필드가 없는 경우 매핑
                    if "type" in log_entry and "event_type" not in log_entry:
                        log_entry["event_type"] = log_entry.pop("type")
                    elif "type" not in log_entry and "event_type" not in log_entry:
                        missing_fields.append("event_type/type")
                    
                    if missing_fields:
                        logger.warning(f"WebSocket log entry missing required fields: {', '.join(missing_fields)}. Skipping this entry.")
                        continue
                    
                    # '에러', 'error', 'DEBUG' 단어가 포함된 로그는 제외
                    content = log_entry.get("content", "")
                    if (isinstance(content, str) and 
                        not any(keyword.lower() in content.lower() for keyword in ["에러", "error", "debug"])):
                        # WebSocket 클라이언트에게 로그 전송
                        await websocket.send_json({"event_type": "log", "data": log_entry})
                    else:
                        logger.debug(f"WebSocket에서 '에러/error/DEBUG' 키워드 포함된 로그 필터링됨")
                        
                except json.JSONDecodeError:
                    logger.warning(f"Failed to decode message from pubsub channel {log_channel}: {log_data}")
                except WebSocketDisconnect: # send_json 도중 연결 끊김 처리
                     logger.info(f"WebSocket client disconnected during send for user {user_id} logs.")
                     break # 루프 종료
                except Exception as e:
                     logger.error(f"Error sending log via WebSocket for user {user_id}: {e}")
                     # 연결 유지하며 에러 로깅
            else:
                # 타임아웃 발생 시 PING 메시지 전송하여 연결 활성 확인 (선택 사항)
                 try:
                     await websocket.send_json({"event_type": "ping"})
                 except WebSocketDisconnect:
                     break # 클라이언트 연결 끊김
                 except Exception:
                     # send_json 중 다른 에러 발생 가능성 처리
                     logger.warning(f"Failed to send ping to WebSocket client for user {user_id}")
                     # 여기서도 연결 끊김 발생 가능성 있음
                     try:
                         # 연결 상태 재확인 시도 (예: 간단한 메시지 전송)
                         await websocket.send_text("") # 비어있는 텍스트 전송으로 상태 확인
                     except WebSocketDisconnect:
                         logger.info(f"WebSocket client disconnected after failed ping for user {user_id} logs.")
                         break
                     except Exception as ping_check_e:
                          logger.warning(f"Error checking WebSocket connection after failed ping for user {user_id}: {ping_check_e}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected for user {user_id} logs.")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        try:
            await websocket.close(code=1011) # Internal Server Error
        except RuntimeError:
            pass # 이미 닫혔을 경우 무시
    finally:
        # Pub/Sub 구독 해지
        if pubsub:
            await pubsub.unsubscribe(log_channel)
            await pubsub.close()
        logger.info(f"Cleaned up WebSocket resources for user {user_id}.")

@router.get(
    "/logs/by_okx_uid/{okx_uid}",
    response_model=TelegramLogResponse,
    summary="텔레그램 메시지 로그 조회 (OKX UID 기준)",
    description="OKX UID 기준으로 텔레그램 메시지 전송/수정 로그를 조회합니다.",
    responses={
        200: {"description": "로그 조회 성공"},
        404: {"description": "사용자 로그 없음"},
        500: {"description": "서버 내부 오류"}
    }
)
async def get_telegram_logs_by_okx_uid(
    okx_uid: str = Path(..., description="로그를 조회할 사용자의 OKX UID"),
    limit: int = Query(100, description="조회할 로그 개수 제한", ge=1, le=1000),
    offset: int = Query(0, description="조회 시작 오프셋", ge=0),
    category: Optional[str] = Query(None, description="필터링할 로그 카테고리 (e.g., start, stop, entry)"),
    strategy_type: Optional[str] = Query(None, description="필터링할 전략 타입 (e.g., HyperRSI)")
):
    """지정된 OKX UID의 텔레그램 메시지 로그를 시간 역순으로 조회합니다."""
    
    log_set_key = f"telegram:logs:by_okx_uid:{okx_uid}"
    
    try:
        # Sorted Set에서 점수(타임스탬프) 기준 역순으로 로그 데이터 조회
        log_data = await redis_client.zrevrange(
            log_set_key,
            start=offset,
            end=offset + limit - 1
        )

        # 전체 로그 개수 조회
        total_logs = await redis_client.zcard(log_set_key)

        if not log_data:
            return TelegramLogResponse(logs=[], total=0)

        # JSON 문자열을 LogEntry 모델 객체로 변환
        logs = []
        for item in log_data:
            try:
                log_entry_dict = json.loads(item)
                
                # 필수 필드 검증
                required_fields = ["timestamp", "user_id", "status", "category", "strategy_type", "content"]
                missing_fields = [field for field in required_fields if field not in log_entry_dict]
                
                # 데이터 타입 조정
                if "user_id" in log_entry_dict and not isinstance(log_entry_dict["user_id"], str):
                    log_entry_dict["user_id"] = str(log_entry_dict["user_id"])
                
                # type 필드가 있고 event_type 필드가 없는 경우 매핑
                if "type" in log_entry_dict and "event_type" not in log_entry_dict:
                    log_entry_dict["event_type"] = log_entry_dict.pop("type")
                elif "type" not in log_entry_dict and "event_type" not in log_entry_dict:
                    missing_fields.append("event_type/type")
                
                if missing_fields:
                    logger.warning(f"Log entry missing required fields: {', '.join(missing_fields)}. Skipping this entry.")
                    continue
                
                # '에러', 'error', 'DEBUG' 단어가 포함된 로그는 제외
                content = log_entry_dict.get("content", "")
                if (isinstance(content, str) and 
                    not any(keyword.lower() in content.lower() for keyword in ["에러", "error", "debug"])):
                    logs.append(LogEntry(**log_entry_dict))
                    
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode log entry for okx_uid {okx_uid}: {item}")
            except Exception as e:
                logger.error(f"Error processing log entry for okx_uid {okx_uid}: {e}, data: {item}")

        # 카테고리 필터링 (요청된 경우)
        if category:
            logs = [log for log in logs if log.category == category]

        # 전략 타입 필터링 (요청된 경우)
        if strategy_type:
            logs = [log for log in logs if log.strategy_type == strategy_type]

        return TelegramLogResponse(logs=logs, total=total_logs)
    
    except Exception as e:
        logger.error(f"Error retrieving logs for okx_uid {okx_uid}: {str(e)}")
        raise HTTPException(status_code=500, detail="로그 조회 중 오류가 발생했습니다.")

@router.websocket("/ws/logs/by_okx_uid/{okx_uid}")
async def websocket_log_endpoint_by_okx_uid(websocket: WebSocket, okx_uid: str):
    """WebSocket을 통해 실시간 텔레그램 로그를 스트리밍합니다 (OKX UID 기준)."""
    await websocket.accept()
    
    log_channel = f"telegram:log_channel:by_okx_uid:{okx_uid}"
    pubsub = redis_client.pubsub()
    
    try:
        await pubsub.subscribe(log_channel)
        logger.info(f"WebSocket client connected for okx_uid {okx_uid} logs.")

        while True:
            # Redis Pub/Sub 메시지 수신 대기 (타임아웃 설정)
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=60)
            if message and message.get("event_type") == "message":
                log_data = message["data"]
                try:
                    log_entry = json.loads(log_data)
                    
                    # 필수 필드 검증
                    required_fields = ["timestamp", "user_id", "status", "category", "strategy_type", "content"]
                    missing_fields = [field for field in required_fields if field not in log_entry]
                    
                    # 데이터 타입 조정
                    if "user_id" in log_entry and not isinstance(log_entry["user_id"], str):
                        log_entry["user_id"] = str(log_entry["user_id"])
                    
                    # type 필드 매핑
                    if "type" in log_entry and "event_type" not in log_entry:
                        log_entry["event_type"] = log_entry.pop("type")
                    elif "type" not in log_entry and "event_type" not in log_entry:
                        missing_fields.append("event_type/type")
                    
                    if missing_fields:
                        logger.warning(f"WebSocket log entry missing required fields: {', '.join(missing_fields)}. Skipping this entry.")
                        continue
                    
                    # 에러 메시지 필터링
                    content = log_entry.get("content", "")
                    if (isinstance(content, str) and 
                        not any(keyword.lower() in content.lower() for keyword in ["에러", "error", "debug"])):
                        # WebSocket 클라이언트에게 로그 전송
                        await websocket.send_json({"event_type": "log", "data": log_entry})
                        
                except json.JSONDecodeError:
                    logger.warning(f"Failed to decode message from pubsub channel {log_channel}: {log_data}")
                except WebSocketDisconnect:
                     logger.info(f"WebSocket client disconnected during send for okx_uid {okx_uid} logs.")
                     break
                except Exception as e:
                     logger.error(f"Error sending log via WebSocket for okx_uid {okx_uid}: {e}")
            else:
                # 타임아웃 발생 시 PING 메시지 전송
                try:
                    await websocket.send_json({"event_type": "ping"})
                except WebSocketDisconnect:
                    break
                except Exception:
                    logger.warning(f"Failed to send ping to WebSocket client for okx_uid {okx_uid}")
                    try:
                        await websocket.send_text("")
                    except WebSocketDisconnect:
                        logger.info(f"WebSocket client disconnected after failed ping for okx_uid {okx_uid} logs.")
                        break
                    except Exception as ping_check_e:
                        logger.warning(f"Error checking WebSocket connection after failed ping for okx_uid {okx_uid}: {ping_check_e}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected for okx_uid {okx_uid} logs.")
    except Exception as e:
        logger.error(f"WebSocket error for okx_uid {okx_uid}: {e}")
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass
    finally:
        # Pub/Sub 구독 해지
        if pubsub:
            await pubsub.unsubscribe(log_channel)
            await pubsub.close()
        logger.info(f"Cleaned up WebSocket resources for okx_uid {okx_uid}.")

@router.get(
    "/stats/{okx_uid}",
    summary="텔레그램 메시지 통계 조회",
    description="OKX UID 기준으로 텔레그램 메시지 통계를 조회합니다.",
    responses={
        200: {"description": "통계 조회 성공"},
        500: {"description": "서버 내부 오류"}
    }
)
async def get_telegram_stats(okx_uid: str = Path(..., description="통계를 조회할 사용자의 OKX UID")):
    """지정된 OKX UID의 텔레그램 메시지 통계를 조회합니다."""
    
    stats_key = f"telegram:stats:{okx_uid}"
    
    try:
        # 모든 통계 가져오기
        stats = await redis_client.hgetall(stats_key)
        
        # 기본값 설정
        total = int(stats.get("total", 0))
        success = int(stats.get("success", 0))
        failed = int(stats.get("failed", 0))
        
        # 카테고리별 통계
        categories = {}
        for key, value in stats.items():
            if key.startswith("category:"):
                category_name = key.replace("category:", "")
                categories[category_name] = int(value)
        
        return {
            "okx_uid": okx_uid,
            "total_messages": total,
            "success_count": success,
            "failed_count": failed,
            "success_rate": round(success / total * 100, 2) if total > 0 else 0,
            "by_category": categories
        }
    
    except Exception as e:
        logger.error(f"Error retrieving stats for okx_uid {okx_uid}: {str(e)}")
        raise HTTPException(status_code=500, detail="통계 조회 중 오류가 발생했습니다.")