from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from HYPERRSI.src.core.logger import (
    get_order_logs_by_date_range,
    get_order_logs_by_user_id,
    get_user_order_logs_from_file,
)
from shared.database.redis_helper import get_redis_client

trading_log_router = APIRouter()

class TradingLogResponse(BaseModel):
    user_id: str
    execution_count: int
    execution_times: List[str]
    
class CleanupResponse(BaseModel):
    user_id: str
    symbol: str
    deleted_keys: list[str]
    success: bool

class OrderLogEntry(BaseModel):
    timestamp: str
    user_id: str
    symbol: str
    action_type: str
    position_side: str
    price: Optional[float] = None
    quantity: Optional[float] = None
    level: Optional[int] = None
    message: Optional[str] = None
    extra: Optional[dict] = None

class OrderLogsResponse(BaseModel):
    user_id: str
    total_count: int
    logs: List[OrderLogEntry]



@trading_log_router.get(
    "/trading-logs/{user_id}",
    response_model=TradingLogResponse,
    summary="트레이딩 사이클 실행 이력 조회",
    description="""
# 트레이딩 사이클 실행 이력 조회

사용자의 트레이딩 사이클 실행 횟수와 실행 시간을 조회합니다. 거래 주기 모니터링과 봇 활동성 추적에 사용됩니다.

## 동작 방식

1. **Redis 키 조회**:
   - `user:{user_id}:trading_execution_count` - 총 실행 횟수
   - `user:{user_id}:trading_execution_times` - 실행 시간 목록 (List)
2. **실행 횟수 파싱**: String → Integer 변환 (없으면 0)
3. **실행 시간 목록 조회**: LRANGE로 전체 리스트 가져오기 (0, -1)
4. **바이트 디코딩**: Redis bytes → UTF-8 문자열 변환
5. **응답 반환**: 실행 통계 + 시간 목록

## Redis 키 구조

- **실행 횟수 키**: `user:{user_id}:trading_execution_count`
  - 타입: String
  - 값: "150" (숫자 문자열)
  - 업데이트: 각 트레이딩 사이클 실행 시 +1

- **실행 시간 키**: `user:{user_id}:trading_execution_times`
  - 타입: List
  - 값: ["2025-01-15T10:30:00Z", "2025-01-15T10:35:00Z", ...]
  - 업데이트: 각 사이클 실행 시 LPUSH (최신이 앞에)

## 반환 데이터 구조

- **user_id** (string): 사용자 식별자
- **execution_count** (integer): 총 트레이딩 사이클 실행 횟수
- **execution_times** (array[string]): 실행 시간 목록 (ISO 8601 형식)

## 트레이딩 사이클이란?

- **정의**: 봇이 주기적으로 실행하는 거래 로직 (신호 확인, 주문 실행, 포지션 관리)
- **주기**: 설정에 따라 다름 (예: 5분마다, 1분마다)
- **실행 조건**: 봇이 running 상태일 때만 카운트
- **중요성**: 실행 빈도로 봇 정상 작동 여부 확인 가능

## 사용 시나리오

- 📊 **활동성 모니터링**: 봇이 정상적으로 실행되고 있는지 확인
- ⏰ **실행 주기 확인**: 마지막 실행 시간으로 멈춤 여부 감지
- 🔍 **문제 진단**: 실행 횟수가 너무 적으면 설정 오류 의심
- 📈 **통계 분석**: 시간대별 실행 빈도 분석
- 🎯 **성과 측정**: 실행 횟수 대비 거래 횟수 비율 계산

## 예시 요청

```bash
# 기본 조회
curl "http://localhost:8000/trading-logs/1709556958"

# OKX UID로 조회
curl "http://localhost:8000/trading-logs/646396755365762614"
```
""",
    responses={
        200: {
            "description": "✅ 실행 이력 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "active_bot": {
                            "summary": "활발한 봇",
                            "value": {
                                "user_id": "1709556958",
                                "execution_count": 150,
                                "execution_times": [
                                    "2025-01-15T10:35:00Z",
                                    "2025-01-15T10:30:00Z",
                                    "2025-01-15T10:25:00Z",
                                    "2025-01-15T10:20:00Z",
                                    "2025-01-15T10:15:00Z"
                                ]
                            }
                        },
                        "new_bot": {
                            "summary": "신규 봇 (실행 이력 없음)",
                            "value": {
                                "user_id": "1709556958",
                                "execution_count": 0,
                                "execution_times": []
                            }
                        },
                        "recently_started": {
                            "summary": "최근 시작한 봇",
                            "value": {
                                "user_id": "1709556958",
                                "execution_count": 5,
                                "execution_times": [
                                    "2025-01-15T10:04:00Z",
                                    "2025-01-15T10:03:00Z",
                                    "2025-01-15T10:02:00Z",
                                    "2025-01-15T10:01:00Z",
                                    "2025-01-15T10:00:00Z"
                                ]
                            }
                        }
                    }
                }
            }
        }
    }
)
async def fetch_trading_logs(user_id: str) -> TradingLogResponse:
    """
    ### 트레이딩 로그 조회
    - **user_id**: 유저 식별자
    - Redis에서 다음 키를 조회합니다.
      - `user:{user_id}:trading_execution_count`
      - `user:{user_id}:trading_execution_times`
    - 반환값:
      - **execution_count**: 실행 횟수 (int)
      - **execution_times**: 실행 시간 목록 (List[str])
    """
    # Redis 키 설정
    count_key = f"user:{user_id}:trading_execution_count"
    times_key = f"user:{user_id}:trading_execution_times"
    
    # 실행 횟수 조회
    execution_count = await get_redis_client().get(count_key)
    if execution_count is None:
        execution_count = 0
    else:
        execution_count = int(execution_count)
    
    # 실행 시간 목록 조회 (List 타입)
    execution_times_bytes = await get_redis_client().lrange(times_key, 0, -1)
    # Redis에서 가져온 값은 bytes이므로, 디코딩을 해줘야 문자열로 변환됨
    execution_times = [x.decode("utf-8") for x in execution_times_bytes]
    
    return TradingLogResponse(
        user_id=user_id,
        execution_count=execution_count,
        execution_times=execution_times
    )
    
    



@trading_log_router.delete(
    "/cleanup/{user_id}/{symbol}",
    response_model=CleanupResponse,
    summary="트레이딩 데이터 정리 (포지션 초기화)",
    description="""
# 트레이딩 데이터 정리 (포지션 초기화)

특정 사용자의 특정 심볼에 대한 트레이딩 관련 Redis 데이터를 완전히 삭제합니다. 포지션 리셋, 데이터 불일치 해결, 긴급 상황 대응에 사용됩니다.

## 동작 방식

1. **삭제 대상 키 목록 생성**: 9개 키 패턴 정의
2. **존재 확인**: EXISTS로 각 키 존재 여부 확인
3. **삭제 실행**: DELETE 명령으로 키 제거
4. **삭제 기록**: 실제 삭제된 키 목록 수집
5. **응답 반환**: 삭제된 키 목록 + 성공 여부

## 삭제되는 Redis 키 목록

### 포지션 데이터
- `user:{user_id}:position:{symbol}:long` - 롱 포지션 정보
- `user:{user_id}:position:{symbol}:short` - 숏 포지션 정보

### TP (Take Profit) 데이터
- `user:{user_id}:position:{symbol}:long:tp_data` - 롱 TP 설정
- `user:{user_id}:position:{symbol}:short:tp_data` - 숏 TP 설정

### 상태 정보
- `user:{user_id}:position:{symbol}:position_state` - 포지션 상태 플래그
- `user:{user_id}:{symbol}:dual_side_position` - 양방향 포지션 플래그

### DCA (Dollar Cost Averaging) 데이터
- `user:{user_id}:position:{symbol}:long:dca_levels` - 롱 DCA 레벨
- `user:{user_id}:position:{symbol}:short:dca_levels` - 숏 DCA 레벨

### 피라미딩 카운터
- `user:{user_id}:position:{symbol}:pyramiding_count` - 피라미딩 횟수

## 주의사항

⚠️ **이 작업은 되돌릴 수 없습니다!**

- 삭제된 데이터는 복구 불가능
- 현재 열린 포지션이 있어도 Redis에서는 삭제됨
- 실제 거래소 포지션은 유지되지만, 봇 추적 데이터는 손실
- 실행 전 현재 포지션 상태 확인 권장

## 사용 시나리오

- 🔄 **데이터 리셋**: 포지션 추적 데이터 초기화
- 🛠️ **불일치 해결**: Redis와 실제 포지션 간 불일치 수정
- 🚨 **긴급 상황**: 버그로 인한 잘못된 데이터 제거
- 🧪 **테스트 환경**: 테스트 후 데이터 정리
- 📊 **전략 변경**: 새로운 전략 시작 전 초기화

## 예시 요청

```bash
# BTC 포지션 데이터 정리
curl -X DELETE "http://localhost:8000/cleanup/1709556958/BTC-USDT-SWAP"

# ETH 포지션 데이터 정리
curl -X DELETE "http://localhost:8000/cleanup/1709556958/ETH-USDT-SWAP"

# 모든 심볼 정리 (반복 호출 필요)
for symbol in BTC-USDT-SWAP ETH-USDT-SWAP SOL-USDT-SWAP; do
  curl -X DELETE "http://localhost:8000/cleanup/1709556958/$symbol"
done
```
""",
    responses={
        200: {
            "description": "✅ 데이터 정리 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "full_cleanup": {
                            "summary": "전체 데이터 존재 (9개 키 삭제)",
                            "value": {
                                "user_id": "1709556958",
                                "symbol": "BTC-USDT-SWAP",
                                "deleted_keys": [
                                    "user:1709556958:position:BTC-USDT-SWAP:long",
                                    "user:1709556958:position:BTC-USDT-SWAP:short",
                                    "user:1709556958:position:BTC-USDT-SWAP:long:tp_data",
                                    "user:1709556958:position:BTC-USDT-SWAP:short:tp_data",
                                    "user:1709556958:position:BTC-USDT-SWAP:position_state",
                                    "user:1709556958:BTC-USDT-SWAP:dual_side_position",
                                    "user:1709556958:position:BTC-USDT-SWAP:long:dca_levels",
                                    "user:1709556958:position:BTC-USDT-SWAP:short:dca_levels",
                                    "user:1709556958:position:BTC-USDT-SWAP:pyramiding_count"
                                ],
                                "success": True
                            }
                        },
                        "partial_cleanup": {
                            "summary": "일부 데이터만 존재 (3개 키 삭제)",
                            "value": {
                                "user_id": "1709556958",
                                "symbol": "ETH-USDT-SWAP",
                                "deleted_keys": [
                                    "user:1709556958:position:ETH-USDT-SWAP:long",
                                    "user:1709556958:position:ETH-USDT-SWAP:long:tp_data",
                                    "user:1709556958:position:ETH-USDT-SWAP:position_state"
                                ],
                                "success": True
                            }
                        },
                        "no_data": {
                            "summary": "정리할 데이터 없음 (0개 키 삭제)",
                            "value": {
                                "user_id": "1709556958",
                                "symbol": "SOL-USDT-SWAP",
                                "deleted_keys": [],
                                "success": True
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 내부 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "detail": "Failed to cleanup trading data: Redis connection error"
                            }
                        },
                        "delete_error": {
                            "summary": "키 삭제 실패",
                            "value": {
                                "detail": "Failed to cleanup trading data: Delete operation failed"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def cleanup_trading_data(user_id: str, symbol: str) -> CleanupResponse:
    """
    ### 트레이딩 데이터 정리
    - **user_id**: 유저 식별자
    - **symbol**: 거래 심볼
    
    다음 Redis 키들을 제거합니다:
    - tp_data
    - tp_state
    - dual_side_position
    - dca_levels
    - pyramiding_count
    """
    try:
        # 삭제할 키 패턴 정의
        keys_to_delete = [
            f"user:{user_id}:position:{symbol}:long",
            f"user:{user_id}:position:{symbol}:short",
            f"user:{user_id}:position:{symbol}:long:tp_data",
            f"user:{user_id}:position:{symbol}:short:tp_data",
            f"user:{user_id}:position:{symbol}:position_state",
            f"user:{user_id}:{symbol}:dual_side_position",
            f"user:{user_id}:position:{symbol}:long:dca_levels",
            f"user:{user_id}:position:{symbol}:short:dca_levels",
            f"user:{user_id}:position:{symbol}:pyramiding_count"
        ]
        
        # 키 삭제 실행
        deleted_keys = []
        for key in keys_to_delete:
            if await get_redis_client().exists(key):
                await get_redis_client().delete(key)
                deleted_keys.append(key)
        
        return CleanupResponse(
            user_id=user_id,
            symbol=symbol,
            deleted_keys=deleted_keys,
            success=True
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cleanup trading data: {str(e)}"
        )

@trading_log_router.get(
    "/order-logs/user/{user_id}",
    response_model=OrderLogsResponse,
    summary="사용자별 거래 주문 로그 조회",
    description="""
# 사용자별 거래 주문 로그 조회

특정 사용자의 모든 거래 주문 로그를 조회합니다. 진입, 청산, TP, SL, DCA 등 모든 주문 이벤트를 포함합니다.

## 동작 방식

1. **로그 파일 조회**: 사용자별 로그 파일에서 로그 읽기
2. **페이지네이션 적용**: offset부터 limit개 로그 가져오기
3. **필드 추출**: 기본 필드 (timestamp, user_id, symbol, action_type, position_side, price, quantity, level, message) 추출
4. **Extra 필드 처리**: 기본 필드 외 모든 필드를 extra 객체에 포함
5. **모델 변환**: 딕셔너리 → OrderLogEntry 모델 변환
6. **응답 반환**: 로그 목록 + 전체 개수

## 로그 파일 위치

- **경로**: `logs/order_logs/user_{user_id}.log`
- **형식**: JSONL (JSON Lines) - 한 줄에 하나의 JSON 로그
- **로테이션**: 일별 또는 크기 기반 (설정에 따라 다름)
- **보관 기간**: 설정에 따라 다름 (기본 30일)

## 로그 항목 필드

### 기본 필드
- **timestamp** (string): ISO 8601 형식 타임스탬프
- **user_id** (string): 사용자 식별자
- **symbol** (string): 거래 심볼 (예: BTC-USDT-SWAP)
- **action_type** (string): 주문 액션 (entry, exit, tp, sl, dca, liquidation)
- **position_side** (string): 포지션 방향 (long, short)
- **price** (float, optional): 주문 가격
- **quantity** (float, optional): 주문 수량
- **level** (integer, optional): DCA/피라미딩 레벨
- **message** (string, optional): 로그 메시지

### Extra 필드 (optional)
- **order_id**: 주문 ID
- **leverage**: 레버리지 배율
- **pnl**: 실현 손익
- **fee**: 거래 수수료
- **reason**: 청산 이유
- 기타 커스텀 필드들

## 페이지네이션

- **limit**: 1-1000 범위 (기본 100)
- **offset**: 0부터 시작
- **예시**:
  - 첫 페이지: limit=100, offset=0
  - 두 번째 페이지: limit=100, offset=100
  - 세 번째 페이지: limit=100, offset=200

## 사용 시나리오

- 📜 **거래 이력 조회**: 모든 주문 활동 확인
- 📊 **통계 분석**: action_type별 주문 빈도 분석
- 🔍 **문제 추적**: 특정 주문 이벤트 조사
- 💰 **수익 계산**: PnL 로그로 누적 수익 계산
- 📈 **전략 평가**: 진입/청산 패턴 분석

## 예시 요청

```bash
# 기본 조회 (최근 100개)
curl "http://localhost:8000/order-logs/user/1709556958?limit=100&offset=0"

# 많은 로그 조회 (최대 1000개)
curl "http://localhost:8000/order-logs/user/1709556958?limit=1000&offset=0"

# 두 번째 페이지
curl "http://localhost:8000/order-logs/user/1709556958?limit=100&offset=100"

# 소량 조회 (최근 10개만)
curl "http://localhost:8000/order-logs/user/1709556958?limit=10&offset=0"
```
""",
    responses={
        200: {
            "description": "✅ 주문 로그 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "entry_exit_logs": {
                            "summary": "진입/청산 로그",
                            "value": {
                                "user_id": "1709556958",
                                "total_count": 2,
                                "logs": [
                                    {
                                        "timestamp": "2025-01-15T10:30:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "BTC-USDT-SWAP",
                                        "action_type": "entry",
                                        "position_side": "long",
                                        "price": 92000.0,
                                        "quantity": 0.1,
                                        "level": 1,
                                        "message": "진입 신호 발생 (RSI: 35)",
                                        "extra": {
                                            "order_id": "12345678",
                                            "leverage": 10,
                                            "fee": 0.92
                                        }
                                    },
                                    {
                                        "timestamp": "2025-01-15T10:35:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "BTC-USDT-SWAP",
                                        "action_type": "exit",
                                        "position_side": "long",
                                        "price": 93000.0,
                                        "quantity": 0.1,
                                        "level": None,
                                        "message": "TP1 도달로 부분 청산",
                                        "extra": {
                                            "order_id": "12345679",
                                            "pnl": 100.0,
                                            "fee": 0.93,
                                            "reason": "tp1_reached"
                                        }
                                    }
                                ]
                            }
                        },
                        "dca_logs": {
                            "summary": "DCA (물타기) 로그",
                            "value": {
                                "user_id": "1709556958",
                                "total_count": 3,
                                "logs": [
                                    {
                                        "timestamp": "2025-01-15T10:30:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "ETH-USDT-SWAP",
                                        "action_type": "entry",
                                        "position_side": "long",
                                        "price": 3500.0,
                                        "quantity": 1.0,
                                        "level": 1,
                                        "message": "초기 진입",
                                        "extra": {"leverage": 10}
                                    },
                                    {
                                        "timestamp": "2025-01-15T10:32:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "ETH-USDT-SWAP",
                                        "action_type": "dca",
                                        "position_side": "long",
                                        "price": 3450.0,
                                        "quantity": 1.0,
                                        "level": 2,
                                        "message": "DCA 레벨 2 진입 (-1.43%)",
                                        "extra": {"leverage": 10, "avg_price": 3475.0}
                                    },
                                    {
                                        "timestamp": "2025-01-15T10:34:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "ETH-USDT-SWAP",
                                        "action_type": "dca",
                                        "position_side": "long",
                                        "price": 3400.0,
                                        "quantity": 1.0,
                                        "level": 3,
                                        "message": "DCA 레벨 3 진입 (-2.86%)",
                                        "extra": {"leverage": 10, "avg_price": 3450.0}
                                    }
                                ]
                            }
                        },
                        "empty_logs": {
                            "summary": "로그 없음",
                            "value": {
                                "user_id": "1709556958",
                                "total_count": 0,
                                "logs": []
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 내부 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "file_read_error": {
                            "summary": "로그 파일 읽기 실패",
                            "value": {
                                "detail": "로그 조회 중 오류 발생: File not found"
                            }
                        },
                        "parsing_error": {
                            "summary": "JSON 파싱 오류",
                            "value": {
                                "detail": "로그 조회 중 오류 발생: Invalid JSON format"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_user_order_logs(
    user_id: str,
    limit: int = Query(100, ge=1, le=1000, description="반환할 최대 로그 수"),
    offset: int = Query(0, ge=0, description="건너뛸 로그 수")
) -> OrderLogsResponse:
    """
    ### 사용자별 거래 로그 조회
    - **user_id**: 조회할 사용자 ID
    - **limit**: 반환할 최대 로그 수 (기본값: 100, 최대: 1000)
    - **offset**: 건너뛸 로그 수 (페이지네이션 용)
    
    반환값:
    - 사용자의 거래 로그 목록
    """
    try:
        # 사용자별 로그 파일에서 먼저 조회 시도
        logs = get_user_order_logs_from_file(user_id, limit, offset)
        
        # 응답 형식으로 변환
        formatted_logs = []
        for log in logs:
            # 기본 필드 추출
            entry = {
                "timestamp": log.get("timestamp", ""),
                "user_id": str(log.get("user_id", 0)),
                "symbol": log.get("symbol", ""),
                "action_type": log.get("action_type", ""),
                "position_side": log.get("position_side", ""),
                "price": log.get("price"),
                "quantity": log.get("quantity"),
                "level": log.get("level"),
                "message": log.get("message", "")
            }
            
            # 나머지 필드는 extra에 포함
            extra = {}
            for key, value in log.items():
                if key not in entry:
                    extra[key] = value
            
            entry["extra"] = extra if extra else None
            formatted_logs.append(OrderLogEntry(**entry))
        
        return OrderLogsResponse(
            user_id=str(user_id),
            total_count=len(formatted_logs),
            logs=formatted_logs
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"로그 조회 중 오류 발생: {str(e)}"
        )

@trading_log_router.get(
    "/order-logs/date-range",
    response_model=OrderLogsResponse,
    summary="날짜 범위별 거래 주문 로그 조회",
    description="""
# 날짜 범위별 거래 주문 로그 조회

특정 날짜 범위 내의 거래 주문 로그를 조회합니다. 선택적으로 사용자 ID로 필터링할 수 있으며, 전체 사용자 로그를 조회하거나 특정 사용자만 조회할 수 있습니다.

## 동작 방식

1. **날짜 파싱**: start_date와 end_date를 datetime 객체로 변환 (YYYY-MM-DD 형식)
2. **종료 시간 조정**: end_date를 23:59:59로 설정 (해당 날짜 전체 포함)
3. **로그 조회**: 날짜 범위 + 사용자 ID (선택) 조건으로 로그 파일 탐색
4. **페이지네이션 적용**: offset부터 limit개 로그 가져오기
5. **필드 추출**: 기본 필드 + extra 필드 분리
6. **모델 변환**: 딕셔너리 → OrderLogEntry 모델 변환
7. **응답 반환**: 로그 목록 + 전체 개수

## 날짜 형식

- **입력 형식**: YYYY-MM-DD (예: 2025-01-15)
- **시간 범위**:
  - start_date: 00:00:00부터 시작
  - end_date: 23:59:59까지 포함
- **타임존**: UTC 기준

## 사용자 ID 필터

- **user_id = None**: 모든 사용자의 로그 조회 (관리자 기능)
- **user_id = 1709556958**: 특정 사용자의 로그만 조회
- **활용**: 전체 시스템 분석 vs. 개별 사용자 추적

## 로그 조회 범위

- **날짜 범위**: 2025-01-01 ~ 2025-01-31 (한 달 전체)
- **단일 날짜**: 2025-01-15 ~ 2025-01-15 (하루만)
- **기간**: start_date ≤ timestamp ≤ end_date (양쪽 포함)

## 페이지네이션

- **limit**: 1-1000 범위 (기본 100)
- **offset**: 0부터 시작
- **대용량 조회**: 1000개씩 반복 조회로 전체 데이터 수집 가능

## 사용 시나리오

- 📅 **월별 통계**: 특정 월의 모든 거래 로그 조회
- 📊 **기간별 분석**: 특정 기간 동안의 거래 패턴 분석
- 🔍 **사용자 추적**: 특정 사용자의 기간별 활동 조회
- 💰 **수익 계산**: 기간 내 모든 PnL 집계
- 🎯 **전략 평가**: 날짜별 성과 비교 분석
- 🏢 **관리자 모니터링**: 전체 사용자 활동 추적 (user_id=None)

## 예시 요청

```bash
# 한 달 전체 조회 (모든 사용자)
curl "http://localhost:8000/order-logs/date-range?start_date=2025-01-01&end_date=2025-01-31&limit=1000"

# 특정 사용자의 일주일 로그
curl "http://localhost:8000/order-logs/date-range?start_date=2025-01-10&end_date=2025-01-16&user_id=1709556958&limit=500"

# 하루 로그 조회 (특정 사용자)
curl "http://localhost:8000/order-logs/date-range?start_date=2025-01-15&end_date=2025-01-15&user_id=1709556958"

# 두 번째 페이지
curl "http://localhost:8000/order-logs/date-range?start_date=2025-01-01&end_date=2025-01-31&user_id=1709556958&limit=100&offset=100"

# 전체 사용자의 오늘 로그
curl "http://localhost:8000/order-logs/date-range?start_date=2025-01-15&end_date=2025-01-15&limit=1000"
```
""",
    responses={
        200: {
            "description": "✅ 날짜 범위 로그 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "monthly_logs": {
                            "summary": "월별 로그 (모든 사용자)",
                            "value": {
                                "user_id": "0",
                                "total_count": 5,
                                "logs": [
                                    {
                                        "timestamp": "2025-01-15T10:30:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "BTC-USDT-SWAP",
                                        "action_type": "entry",
                                        "position_side": "long",
                                        "price": 92000.0,
                                        "quantity": 0.1,
                                        "level": 1,
                                        "message": "진입 신호",
                                        "extra": {"leverage": 10}
                                    },
                                    {
                                        "timestamp": "2025-01-15T10:32:00Z",
                                        "user_id": "1234567890",
                                        "symbol": "ETH-USDT-SWAP",
                                        "action_type": "entry",
                                        "position_side": "short",
                                        "price": 3500.0,
                                        "quantity": 1.0,
                                        "level": 1,
                                        "message": "숏 진입",
                                        "extra": {"leverage": 5}
                                    }
                                ]
                            }
                        },
                        "user_weekly_logs": {
                            "summary": "주간 로그 (특정 사용자)",
                            "value": {
                                "user_id": "1709556958",
                                "total_count": 3,
                                "logs": [
                                    {
                                        "timestamp": "2025-01-10T14:00:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "BTC-USDT-SWAP",
                                        "action_type": "entry",
                                        "position_side": "long",
                                        "price": 91000.0,
                                        "quantity": 0.1,
                                        "level": 1,
                                        "message": "롱 진입",
                                        "extra": None
                                    },
                                    {
                                        "timestamp": "2025-01-12T16:30:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "BTC-USDT-SWAP",
                                        "action_type": "exit",
                                        "position_side": "long",
                                        "price": 93000.0,
                                        "quantity": 0.1,
                                        "level": None,
                                        "message": "TP 청산",
                                        "extra": {"pnl": 200.0}
                                    },
                                    {
                                        "timestamp": "2025-01-15T10:00:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "ETH-USDT-SWAP",
                                        "action_type": "entry",
                                        "position_side": "long",
                                        "price": 3500.0,
                                        "quantity": 1.0,
                                        "level": 1,
                                        "message": "새 진입",
                                        "extra": None
                                    }
                                ]
                            }
                        },
                        "daily_log": {
                            "summary": "하루 로그 (특정 사용자)",
                            "value": {
                                "user_id": "1709556958",
                                "total_count": 2,
                                "logs": [
                                    {
                                        "timestamp": "2025-01-15T10:00:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "BTC-USDT-SWAP",
                                        "action_type": "entry",
                                        "position_side": "long",
                                        "price": 92000.0,
                                        "quantity": 0.1,
                                        "level": 1,
                                        "message": "롱 진입",
                                        "extra": None
                                    },
                                    {
                                        "timestamp": "2025-01-15T15:30:00Z",
                                        "user_id": "1709556958",
                                        "symbol": "BTC-USDT-SWAP",
                                        "action_type": "exit",
                                        "position_side": "long",
                                        "price": 93500.0,
                                        "quantity": 0.1,
                                        "level": None,
                                        "message": "익절 청산",
                                        "extra": {"pnl": 150.0}
                                    }
                                ]
                            }
                        },
                        "empty_logs": {
                            "summary": "로그 없음",
                            "value": {
                                "user_id": "1709556958",
                                "total_count": 0,
                                "logs": []
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 잘못된 요청 - 날짜 형식 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_date_format": {
                            "summary": "날짜 형식 오류",
                            "value": {
                                "detail": "날짜 형식이 잘못되었습니다: time data '2025-13-01' does not match format '%Y-%m-%d'"
                            }
                        },
                        "invalid_date_value": {
                            "summary": "존재하지 않는 날짜",
                            "value": {
                                "detail": "날짜 형식이 잘못되었습니다: day is out of range for month"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 내부 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "file_access_error": {
                            "summary": "로그 파일 접근 실패",
                            "value": {
                                "detail": "로그 조회 중 오류 발생: Permission denied"
                            }
                        },
                        "parsing_error": {
                            "summary": "로그 파싱 실패",
                            "value": {
                                "detail": "로그 조회 중 오류 발생: Invalid log format"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_order_logs_by_date(
    start_date: str = Query(..., description="시작 날짜 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="종료 날짜 (YYYY-MM-DD)"),
    user_id: Optional[int] = Query(None, description="조회할 사용자 ID (선택적)"),
    limit: int = Query(100, ge=1, le=1000, description="반환할 최대 로그 수"),
    offset: int = Query(0, ge=0, description="건너뛸 로그 수")
) -> OrderLogsResponse:
    """
    ### 날짜 범위별 거래 로그 조회
    - **start_date**: 시작 날짜 (YYYY-MM-DD)
    - **end_date**: 종료 날짜 (YYYY-MM-DD)
    - **user_id**: 조회할 사용자 ID (선택적)
    - **limit**: 반환할 최대 로그 수 (기본값: 100, 최대: 1000)
    - **offset**: 건너뛸 로그 수 (페이지네이션 용)
    
    반환값:
    - 조건에 맞는 거래 로그 목록
    """
    try:
        # 날짜 문자열을 datetime 객체로 변환
        start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        end_datetime = datetime.strptime(end_date, "%Y-%m-%d")
        end_datetime = datetime(end_datetime.year, end_datetime.month, end_datetime.day, 23, 59, 59)
        
        # 로그 조회
        logs = get_order_logs_by_date_range(start_datetime, end_datetime, user_id, limit, offset)
        
        # 응답 형식으로 변환
        formatted_logs = []
        for log in logs:
            # 기본 필드 추출
            entry = {
                "timestamp": log.get("timestamp", ""),
                "user_id": str(log.get("user_id", 0)),
                "symbol": log.get("symbol", ""),
                "action_type": log.get("action_type", ""),
                "position_side": log.get("position_side", ""),
                "price": log.get("price"),
                "quantity": log.get("quantity"),
                "level": log.get("level"),
                "message": log.get("message", "")
            }
            
            # 나머지 필드는 extra에 포함
            extra = {}
            for key, value in log.items():
                if key not in entry:
                    extra[key] = value
            
            entry["extra"] = extra if extra else None
            formatted_logs.append(OrderLogEntry(**entry))
        
        return OrderLogsResponse(
            user_id=str(user_id or 0),  # user_id가 None이면 0을 문자열로 변환하여 사용
            total_count=len(formatted_logs),
            logs=formatted_logs
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"날짜 형식이 잘못되었습니다: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"로그 조회 중 오류 발생: {str(e)}"
        )