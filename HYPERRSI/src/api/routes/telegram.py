import asyncio
import datetime
import json
import os
from typing import Any, Dict, List, Optional

import telegram
from fastapi import APIRouter, HTTPException, Path, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from HYPERRSI.src.services.timescale_service import TimescaleUserService
from shared.database.redis_helper import get_redis_client
from shared.helpers.user_id_resolver import get_telegram_id_from_okx_uid
from shared.logging import get_logger

# Try to import telegram errors, fallback to generic Exception if not available
try:
    from telegram.error import BadRequest, RetryAfter, TelegramError, Unauthorized
except ImportError:
    # Fallback for older versions
    TelegramError = Exception  # type: ignore
    Unauthorized = Exception  # type: ignore
    BadRequest = Exception  # type: ignore
    RetryAfter = Exception  # type: ignore

logger = get_logger(__name__)

#  FastAPI 라우터 설정
router = APIRouter(prefix="/telegram", tags=["Telegram Message"])

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# 응답 모델
class TelegramResponse(BaseModel):
    """텔레그램 메시지 전송 응답 모델"""
    status: str = Field(description="요청 처리 상태")
    message: str = Field(description="응답 메시지")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "success",
                "message": "메시지가 성공적으로 전송되었습니다."
            }
        }
    }

# 에러 응답 모델
class ErrorResponse(BaseModel):
    """에러 응답 모델"""
    detail: str = Field(description="에러 상세 내용")

    model_config = {
        "json_schema_extra": {
            "example": {
                "detail": "메시지 전송 실패"
            }
        }
    }

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
    summary="텔레그램 메시지 전송",
    description="""
# 텔레그램 메시지 전송

지정된 사용자에게 텔레그램 메시지를 전송합니다. 재시도 로직과 rate limit 처리를 포함합니다.

## 동작 방식

1. **사용자 확인**: OKX UID 또는 Telegram ID로 사용자 확인
2. **메시지 검증**: 비어있지 않은 메시지인지 확인 (1-4096자)
3. **봇 토큰 확인**: TELEGRAM_BOT_TOKEN 환경변수 검증
4. **동시성 제어**: 세마포어로 최대 3개 동시 요청 제한
5. **재시도 로직**: 최대 3회 재시도 (각 1초 간격)
6. **전송 시도**: Telegram Bot API 호출 (HTML 파싱 모드)
7. **에러 처리**: Unauthorized, BadRequest, RetryAfter, TelegramError 구분 처리
8. **응답 반환**: 성공/실패 상태 반환

## 재시도 전략

- **최대 재시도**: 3회
- **재시도 간격**: 1초 (exponential backoff 미적용)
- **재시도 대상**: TelegramError, Exception (Unauthorized/BadRequest 제외)
- **동시성 제한**: Semaphore(3)으로 과부하 방지

## 메시지 형식

- **파싱 모드**: HTML (bold, italic, code 등 지원)
- **길이 제한**: 1-4096자 (Telegram API 제한)
- **지원 태그**: `<b>`, `<i>`, `<code>`, `<pre>`, `<a>` 등

## 사용 시나리오

-  **거래 알림**: 진입/청산 신호 전송
-  **통계 리포트**: 일일/주간 수익 보고서
-  **에러 알림**: API 키 만료, 잔액 부족 등
-  **목표 달성**: TP/SL 도달 알림
-  **봇 상태**: 시작/중지 알림

## 예시 요청

```bash
curl -X POST "http://localhost:8000/telegram/messages/1709556958?message=거래가%20체결되었습니다." \\
     -H "Content-Type: application/json"
```
""",
    responses={
        200: {
            "description": " 메시지 전송 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "trade_entry_success": {
                            "summary": "거래 진입 알림 성공",
                            "value": {
                                "status": "success",
                                "message": "메시지가 성공적으로 전송되었습니다."
                            }
                        },
                        "profit_report_success": {
                            "summary": "수익 보고서 전송 성공",
                            "value": {
                                "status": "success",
                                "message": "메시지가 성공적으로 전송되었습니다."
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청 - 메시지 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "empty_message": {
                            "summary": "빈 메시지",
                            "value": {
                                "detail": "메시지 내용이 비어있습니다."
                            }
                        },
                        "unauthorized_bot": {
                            "summary": "봇 권한 없음",
                            "value": {
                                "detail": "봇이 해당 사용자에게 메시지를 보낼 권한이 없습니다."
                            }
                        },
                        "invalid_chat_id": {
                            "summary": "잘못된 채팅 ID",
                            "value": {
                                "detail": "잘못된 요청: Chat not found"
                            }
                        },
                        "message_too_long": {
                            "summary": "메시지 길이 초과",
                            "value": {
                                "detail": "잘못된 요청: Message is too long"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자 텔레그램 ID를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자 미등록",
                            "value": {
                                "detail": "사용자의 텔레그램 ID를 찾을 수 없습니다."
                            }
                        }
                    }
                }
            }
        },
        429: {
            "description": "⏱️ 메시지 전송 제한 초과 (Rate Limit)",
            "content": {
                "application/json": {
                    "examples": {
                        "rate_limit_hit": {
                            "summary": "Telegram API rate limit",
                            "value": {
                                "detail": "메시지 전송 제한 초과. 30초 후 다시 시도하세요."
                            }
                        },
                        "flood_wait": {
                            "summary": "Flood control 발동",
                            "value": {
                                "detail": "메시지 전송 제한 초과. 60초 후 다시 시도하세요."
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류 - 설정 또는 재시도 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_token": {
                            "summary": "봇 토큰 미설정",
                            "value": {
                                "detail": "텔레그램 봇 토큰이 설정되지 않았습니다."
                            }
                        },
                        "max_retries_exceeded": {
                            "summary": "최대 재시도 초과",
                            "value": {
                                "detail": "최대 재시도 횟수를 초과했습니다."
                            }
                        },
                        "network_error": {
                            "summary": "네트워크 오류",
                            "value": {
                                "detail": "메시지 전송 중 오류가 발생했습니다: Connection timeout"
                            }
                        }
                    }
                }
            }
        }
    }
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
) -> Dict[str, Any]:
    try:
        telegram_id = await get_telegram_id_from_okx_uid(user_id, TimescaleUserService)
        if not telegram_id:
            raise HTTPException(
                status_code=404,
                detail="사용자의 텔레그램 ID를 찾을 수 없습니다."
            )
        if not message.strip():
            raise HTTPException(
                status_code=400,
                detail="메시지 내용이 비어있습니다."
            )

        if not TELEGRAM_BOT_TOKEN:
            raise HTTPException(
                status_code=500,
                detail="텔레그램 봇 토큰이 설정되지 않았습니다."
            )

        async with semaphore:
            max_retries = 3
            retry_delay = 1
            success = False

            bot = telegram.Bot(TELEGRAM_BOT_TOKEN)

            for attempt in range(max_retries):
                try:
                    await bot.send_message(
                        chat_id=str(telegram_id),
                        text=message,
                        parse_mode='HTML'  # HTML 포맷팅 지원
                    )
                    success = True
                    break

                except Unauthorized:
                    raise HTTPException(
                        status_code=400,
                        detail="봇이 해당 사용자에게 메시지를 보낼 권한이 없습니다."
                    )

                except BadRequest as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"잘못된 요청: {str(e)}"
                    )

                except TelegramError as e:
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
    summary="텔레그램 메시지 로그 조회 (통합)",
    description="""
# 텔레그램 메시지 로그 조회 (통합)

사용자의 텔레그램 메시지 전송 및 수정 로그를 시간 역순으로 조회합니다. Telegram ID와 OKX UID 모두 지원합니다.

## 동작 방식

1. **ID 형식 판별**:
   - 18자리 이상 → OKX UID로 간주
   - 18자리 미만 → Telegram ID로 간주
2. **Telegram ID 해석**: OKX UID인 경우 Telegram ID 조회
3. **Redis 조회**: Sorted Set에서 시간 역순으로 로그 조회
4. **필드 검증**: 필수 필드 (timestamp, user_id, status, category, strategy_type, content) 확인
5. **에러 필터링**: "에러", "error", "DEBUG" 키워드 포함 로그 제외
6. **카테고리 필터링**: 요청 시 category/strategy_type으로 필터
7. **응답 반환**: 로그 목록 + 전체 개수 반환

## Redis 키 구조

- **Telegram ID 기준**: `telegram:logs:{telegram_id}`
- **OKX UID 기준**: `telegram:logs:by_okx_uid:{okx_uid}`
- **데이터 타입**: Sorted Set (score=timestamp)
- **값 형식**: JSON 문자열 (LogEntry)

## 로그 항목 필드

- **timestamp** (string): ISO 8601 형식 타임스탬프
- **user_id** (string): 텔레그램 ID
- **symbol** (string, optional): 거래 심볼 (예: BTC-USDT-SWAP)
- **event_type** (string): 이벤트 유형 (entry, exit, start, stop 등)
- **status** (string): 메시지 상태 (sent, edited, failed)
- **category** (string): 로그 카테고리 (start, stop, entry, exit, tp, sl 등)
- **strategy_type** (string): 전략 유형 (HyperRSI, GRID 등)
- **content** (string): 메시지 본문
- **message_id** (integer, optional): 텔레그램 메시지 ID
- **error_message** (string, optional): 에러 메시지 (실패 시)

## 필터링 옵션

- **category**: 로그 카테고리 (start, stop, entry, exit, tp, sl, error)
- **strategy_type**: 전략 타입 (HyperRSI, GRID)
- **limit**: 조회 개수 제한 (1-1000, 기본 100)
- **offset**: 조회 시작 오프셋 (페이지네이션)

## 사용 시나리오

-  **거래 이력**: 진입/청산 메시지 로그 확인
-  **에러 추적**: 실패한 메시지 원인 분석
-  **통계 분석**: 카테고리별 메시지 빈도 확인
-  **성과 검증**: TP/SL 도달 이벤트 추적
-  **알림 이력**: 봇 상태 변경 로그 확인

## 예시 요청

```bash
# 최근 100개 로그 조회
curl "http://localhost:8000/telegram/logs/1709556958?limit=100&offset=0"

# 진입 시그널만 조회
curl "http://localhost:8000/telegram/logs/1709556958?category=entry&limit=50"

# HyperRSI 전략만 조회
curl "http://localhost:8000/telegram/logs/646396755365762614?strategy_type=HyperRSI"

# 두 번째 페이지 조회 (offset=100)
curl "http://localhost:8000/telegram/logs/1709556958?limit=100&offset=100"
```
""",
    responses={
        200: {
            "description": " 로그 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "entry_exit_logs": {
                            "summary": "진입/청산 로그",
                            "value": {
                                "logs": [
                                    {
                                        "timestamp": "2025-01-15T10:30:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "BTC-USDT-SWAP",
                                        "event_type": "entry",
                                        "status": "sent",
                                        "category": "entry",
                                        "strategy_type": "HyperRSI",
                                        "content": " 롱 진입 신호 발생\n심볼: BTC-USDT-SWAP\n가격: $92,000",
                                        "message_id": 123456,
                                        "error_message": None
                                    },
                                    {
                                        "timestamp": "2025-01-15T10:35:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "BTC-USDT-SWAP",
                                        "event_type": "exit",
                                        "status": "sent",
                                        "category": "tp",
                                        "strategy_type": "HyperRSI",
                                        "content": " TP1 도달\n심볼: BTC-USDT-SWAP\n수익: +2.5%",
                                        "message_id": 123457,
                                        "error_message": None
                                    }
                                ],
                                "total": 250
                            }
                        },
                        "bot_status_logs": {
                            "summary": "봇 상태 로그",
                            "value": {
                                "logs": [
                                    {
                                        "timestamp": "2025-01-15T09:00:00Z",
                                        "user_id": "1709556958",
                                        "symbol": None,
                                        "event_type": "start",
                                        "status": "sent",
                                        "category": "start",
                                        "strategy_type": "HyperRSI",
                                        "content": " HyperRSI 봇 시작\n레버리지: 10x\n방향: 롱숏",
                                        "message_id": 123450,
                                        "error_message": None
                                    }
                                ],
                                "total": 50
                            }
                        },
                        "empty_logs": {
                            "summary": "로그 없음",
                            "value": {
                                "logs": [],
                                "total": 0
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자 로그 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자 미등록",
                            "value": {
                                "detail": "사용자의 텔레그램 ID를 찾을 수 없습니다."
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 조회 실패",
                            "value": {
                                "detail": "로그 조회 중 오류가 발생했습니다."
                            }
                        },
                        "json_decode_error": {
                            "summary": "로그 파싱 실패",
                            "value": {
                                "detail": "로그 조회 중 오류가 발생했습니다."
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_telegram_logs(
    user_id: str = Path(..., description="로그를 조회할 사용자의 텔레그램 ID 또는 OKX UID"),
    limit: int = Query(100, description="조회할 로그 개수 제한", ge=1, le=1000),
    offset: int = Query(0, description="조회 시작 오프셋", ge=0),
    category: Optional[str] = Query(None, description="필터링할 로그 카테고리 (e.g., start, stop, entry)"),
    strategy_type: Optional[str] = Query(None, description="필터링할 전략 타입 (e.g., HyperRSI)")
) -> Dict[str, Any]:
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
        final_user_id = user_id_str
    else:
        # Telegram ID로 조회 (18자리 미만인 경우)
        telegram_id = await get_telegram_id_from_okx_uid(user_id_str, TimescaleUserService)
        if not telegram_id:
            raise HTTPException(
                status_code=404,
                detail="사용자의 텔레그램 ID를 찾을 수 없습니다."
            )
        log_set_key = LOG_SET_KEY.format(user_id=telegram_id)
        print(f"telegram id: {telegram_id}")
        final_user_id = telegram_id
    
    print(f"log_set_key: {log_set_key}")
    try:
        # Sorted Set에서 점수(타임스탬프) 기준 역순으로 로그 데이터 조회
        # ZREVRANGE 사용 (start=offset, end=offset + limit - 1)
        log_data = await get_redis_client().zrevrange(
            log_set_key,
            start=offset,
            end=offset + limit - 1
        )

        # 전체 로그 개수 조회
        total_logs = await get_redis_client().zcard(log_set_key)

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
async def websocket_log_endpoint(websocket: WebSocket, user_id: str) -> None:
    """WebSocket을 통해 실시간 텔레그램 로그를 스트리밍합니다."""
    await websocket.accept()
    telegram_id = await get_telegram_id_from_okx_uid(user_id, TimescaleUserService)
    if not telegram_id:
        await websocket.close(code=1008, reason="사용자의 텔레그램 ID를 찾을 수 없습니다.")
        return
    log_channel = LOG_CHANNEL_KEY.format(user_id=telegram_id)
    pubsub = get_redis_client().pubsub()
    

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
    summary="텔레그램 메시지 로그 조회 (OKX UID 전용)",
    description="""
# 텔레그램 메시지 로그 조회 (OKX UID 전용)

OKX UID를 직접 사용하여 텔레그램 메시지 로그를 조회합니다. Telegram ID 조회 과정을 생략하여 더 빠른 응답 속도를 제공합니다.

## 동작 방식

1. **Redis 키 생성**: `telegram:logs:by_okx_uid:{okx_uid}` 형식
2. **Sorted Set 조회**: 시간 역순(ZREVRANGE)으로 로그 데이터 조회
3. **전체 개수 조회**: ZCARD로 총 로그 개수 확인
4. **JSON 파싱**: 각 로그 항목을 LogEntry 모델로 변환
5. **필드 검증**: 필수 필드 존재 여부 확인
6. **에러 필터링**: "에러", "error", "DEBUG" 키워드 제외
7. **카테고리 필터링**: 요청된 category/strategy_type 적용
8. **응답 반환**: 필터링된 로그 목록 + 전체 개수

## Redis 키 구조

- **키 형식**: `telegram:logs:by_okx_uid:{okx_uid}`
- **데이터 타입**: Sorted Set (score = Unix timestamp)
- **값 형식**: JSON 문자열 (LogEntry 직렬화)
- **정렬 순서**: 타임스탬프 역순 (최신이 먼저)

## 로그 데이터 구조

```json
{
  "timestamp": "2025-01-15T10:30:00Z",
  "user_id": "1709556958",
  "symbol": "BTC-USDT-SWAP",
  "event_type": "entry",
  "status": "sent",
  "category": "entry",
  "strategy_type": "HyperRSI",
  "content": "진입 시그널 메시지",
  "message_id": 123456,
  "error_message": null
}
```

## 필터링 옵션

### Category 필터
- **start**: 봇 시작 로그
- **stop**: 봇 중지 로그
- **entry**: 진입 시그널 로그
- **exit**: 청산 시그널 로그
- **tp**: Take Profit 로그
- **sl**: Stop Loss 로그
- **error**: 에러 로그

### Strategy Type 필터
- **HyperRSI**: RSI + 트렌드 전략
- **GRID**: 그리드 전략
- **Custom**: 커스텀 전략

## 페이지네이션

- **limit**: 1-1000 범위 (기본 100)
- **offset**: 0부터 시작 (페이지 크기 단위로 증가)
- **예시**: 두 번째 페이지 = `limit=100&offset=100`

## 사용 시나리오

-  **실시간 모니터링**: 최근 100개 로그로 거래 현황 파악
-  **성과 분석**: TP/SL 로그로 수익률 분석
-  **문제 진단**: error 카테고리로 실패 원인 추적
-  **이력 조회**: offset 조정으로 과거 로그 탐색
-  **전략 비교**: strategy_type으로 전략별 성과 분리

## 예시 요청

```bash
# 최근 100개 로그 (기본)
curl "http://localhost:8000/telegram/logs/by_okx_uid/646396755365762614?limit=100"

# 진입 시그널만 조회
curl "http://localhost:8000/telegram/logs/by_okx_uid/646396755365762614?category=entry"

# HyperRSI 전략만 50개
curl "http://localhost:8000/telegram/logs/by_okx_uid/646396755365762614?strategy_type=HyperRSI&limit=50"

# 두 번째 페이지 (101-200번째 로그)
curl "http://localhost:8000/telegram/logs/by_okx_uid/646396755365762614?limit=100&offset=100"

# TP/SL 로그만 조회
curl "http://localhost:8000/telegram/logs/by_okx_uid/646396755365762614?category=tp"
```
""",
    responses={
        200: {
            "description": " 로그 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "full_logs": {
                            "summary": "전체 로그 조회",
                            "value": {
                                "logs": [
                                    {
                                        "timestamp": "2025-01-15T10:30:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "BTC-USDT-SWAP",
                                        "event_type": "entry",
                                        "status": "sent",
                                        "category": "entry",
                                        "strategy_type": "HyperRSI",
                                        "content": " 롱 진입 신호\n심볼: BTC-USDT-SWAP\n가격: $92,000\nRSI: 35",
                                        "message_id": 123456,
                                        "error_message": None
                                    },
                                    {
                                        "timestamp": "2025-01-15T10:25:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "ETH-USDT-SWAP",
                                        "event_type": "exit",
                                        "status": "sent",
                                        "category": "tp",
                                        "strategy_type": "HyperRSI",
                                        "content": " TP1 도달\n심볼: ETH-USDT-SWAP\n수익: +2.5%",
                                        "message_id": 123455,
                                        "error_message": None
                                    }
                                ],
                                "total": 350
                            }
                        },
                        "category_filtered": {
                            "summary": "카테고리 필터 (entry만)",
                            "value": {
                                "logs": [
                                    {
                                        "timestamp": "2025-01-15T10:30:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "BTC-USDT-SWAP",
                                        "event_type": "entry",
                                        "status": "sent",
                                        "category": "entry",
                                        "strategy_type": "HyperRSI",
                                        "content": " 롱 진입 신호",
                                        "message_id": 123456,
                                        "error_message": None
                                    }
                                ],
                                "total": 350
                            }
                        },
                        "empty_result": {
                            "summary": "로그 없음",
                            "value": {
                                "logs": [],
                                "total": 0
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_connection_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "detail": "로그 조회 중 오류가 발생했습니다."
                            }
                        },
                        "json_parse_error": {
                            "summary": "JSON 파싱 오류",
                            "value": {
                                "detail": "로그 조회 중 오류가 발생했습니다."
                            }
                        },
                        "field_validation_error": {
                            "summary": "필수 필드 누락",
                            "value": {
                                "detail": "로그 조회 중 오류가 발생했습니다."
                            }
                        }
                    }
                }
            }
        }
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
        log_data = await get_redis_client().zrevrange(
            log_set_key,
            start=offset,
            end=offset + limit - 1
        )

        # 전체 로그 개수 조회
        total_logs = await get_redis_client().zcard(log_set_key)

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
    pubsub = get_redis_client().pubsub()
    
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
    description="""
# 텔레그램 메시지 통계 조회

OKX UID 기준으로 텔레그램 메시지 전송 통계를 조회합니다. 전체 메시지 수, 성공/실패 건수, 성공률, 카테고리별 분포를 제공합니다.

## 동작 방식

1. **Redis 키 생성**: `telegram:stats:{okx_uid}` 형식
2. **Hash 데이터 조회**: HGETALL로 모든 통계 필드 가져오기
3. **기본값 처리**: 통계가 없는 경우 0으로 초기화
4. **카테고리 파싱**: `category:*` 접두사 필드를 카테고리별 통계로 변환
5. **성공률 계산**: (success / total) * 100 (소수점 2자리)
6. **응답 반환**: 종합 통계 + 카테고리별 세부 통계

## Redis Hash 구조

```
telegram:stats:{okx_uid}
  - total: "350"                    # 총 메시지 수
  - success: "340"                  # 성공 건수
  - failed: "10"                    # 실패 건수
  - category:entry: "150"           # 진입 시그널 수
  - category:exit: "145"            # 청산 시그널 수
  - category:tp: "80"               # TP 도달 수
  - category:sl: "15"               # SL 도달 수
  - category:start: "5"             # 시작 알림 수
  - category:stop: "3"              # 중지 알림 수
  - category:error: "10"            # 에러 알림 수
```

## 반환 데이터 구조

- **okx_uid** (string): 조회한 OKX UID
- **total_messages** (integer): 총 메시지 전송 횟수
- **success_count** (integer): 성공한 메시지 수
- **failed_count** (integer): 실패한 메시지 수
- **success_rate** (float): 성공률 (%, 소수점 2자리)
- **by_category** (object): 카테고리별 메시지 수
  - **entry**: 진입 시그널 수
  - **exit**: 청산 시그널 수
  - **tp**: Take Profit 알림 수
  - **sl**: Stop Loss 알림 수
  - **start**: 봇 시작 알림 수
  - **stop**: 봇 중지 알림 수
  - **error**: 에러 알림 수

## 통계 업데이트 시점

통계는 다음 시점에 자동으로 업데이트됩니다:

- **메시지 전송 성공**: total +1, success +1, category:X +1
- **메시지 전송 실패**: total +1, failed +1, category:error +1
- **메시지 수정 성공**: success +1 (total 증가 없음)
- **메시지 수정 실패**: failed +1 (total 증가 없음)

## 사용 시나리오

-  **성과 대시보드**: 전체 메시지 통계 한눈에 확인
-  **성공률 모니터링**: 메시지 전송 안정성 추적
-  **카테고리 분석**: 어떤 알림이 가장 많은지 확인
-  **실패율 추적**: failed_count로 문제 조기 감지
-  **전략 효율성**: 진입/청산 빈도로 전략 활동성 측정

## 예시 요청

```bash
# 기본 통계 조회
curl "http://localhost:8000/telegram/stats/646396755365762614"

# 동일한 OKX UID, 같은 결과
curl "http://localhost:8000/telegram/stats/646396755365762614"
```
""",
    responses={
        200: {
            "description": " 통계 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "active_trader": {
                            "summary": "활발한 거래자",
                            "value": {
                                "okx_uid": "646396755365762614",
                                "total_messages": 350,
                                "success_count": 340,
                                "failed_count": 10,
                                "success_rate": 97.14,
                                "by_category": {
                                    "entry": 150,
                                    "exit": 145,
                                    "tp": 80,
                                    "sl": 15,
                                    "start": 5,
                                    "stop": 3,
                                    "error": 10
                                }
                            }
                        },
                        "new_user": {
                            "summary": "신규 사용자 (통계 없음)",
                            "value": {
                                "okx_uid": "646396755365762614",
                                "total_messages": 0,
                                "success_count": 0,
                                "failed_count": 0,
                                "success_rate": 0,
                                "by_category": {}
                            }
                        },
                        "high_error_rate": {
                            "summary": "높은 실패율",
                            "value": {
                                "okx_uid": "646396755365762614",
                                "total_messages": 100,
                                "success_count": 80,
                                "failed_count": 20,
                                "success_rate": 80.0,
                                "by_category": {
                                    "entry": 40,
                                    "exit": 35,
                                    "tp": 20,
                                    "sl": 5,
                                    "error": 20
                                }
                            }
                        },
                        "category_only": {
                            "summary": "카테고리별 분포",
                            "value": {
                                "okx_uid": "646396755365762614",
                                "total_messages": 200,
                                "success_count": 195,
                                "failed_count": 5,
                                "success_rate": 97.5,
                                "by_category": {
                                    "entry": 90,
                                    "exit": 85,
                                    "tp": 50,
                                    "sl": 10,
                                    "start": 3,
                                    "stop": 2
                                }
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 내부 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "detail": "통계 조회 중 오류가 발생했습니다."
                            }
                        },
                        "parsing_error": {
                            "summary": "통계 데이터 파싱 실패",
                            "value": {
                                "detail": "통계 조회 중 오류가 발생했습니다."
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_telegram_stats(okx_uid: str = Path(..., description="통계를 조회할 사용자의 OKX UID")):
    """지정된 OKX UID의 텔레그램 메시지 통계를 조회합니다."""
    
    stats_key = f"telegram:stats:{okx_uid}"
    
    try:
        # 모든 통계 가져오기
        stats = await get_redis_client().hgetall(stats_key)
        
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