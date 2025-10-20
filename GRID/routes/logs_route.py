import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union, cast

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from GRID.dtos import user
from GRID.routes.connection_manager import ConnectionManager, RedisMessageManager
from GRID.version import __version__

router = APIRouter(prefix="/logs", tags=["logs"])
manager = ConnectionManager()

import logging

from shared.config import settings
from shared.database.redis_patterns import redis_context, RedisTTL
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

def convert_date_to_timestamp(date_str: str | None) -> float | None:
    """Convert date string to Unix timestamp"""
    if date_str is None:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').timestamp()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")


@router.get(
    "/trading_volumes",
    summary="거래량 조회",
    description="""
# 거래량 조회

사용자의 거래량 데이터를 기간별로 조회합니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 ID
- **symbol** (string, optional): 특정 심볼
  - 미지정 시: 모든 활성 심볼의 거래량 조회
  - 지정 시: 해당 심볼만 조회
- **start_date** (string, optional): 시작 날짜
  - 형식: YYYY-MM-DD (예: "2025-01-01")
  - 기본값: 30일 전
- **end_date** (string, optional): 종료 날짜
  - 형식: YYYY-MM-DD (예: "2025-01-31")
  - 기본값: 오늘
- **exchange_name** (string, optional): 거래소 이름
  - 기본값: okx

## 반환 정보

- **user_id** (string): 사용자 ID
- **volumes** (object): 심볼별 거래량 데이터
  - 키: 심볼 이름 (예: "BTC/USDT")
  - 값: 날짜별 거래량 (object)
    - 키: 날짜 (YYYY-MM-DD)
    - 값: 거래량 (float)

## 사용 시나리오

-  **거래 활동 분석**: 일별/주별/월별 거래량 추이 확인
-  **수수료 계산**: 거래량 기반 수수료 할인 조건 확인
-  **거래 패턴 파악**: 활발한 거래 시간대 분석
- 📋 **리포트 생성**: 거래 활동 리포트 작성
-  **전략 평가**: 거래 빈도 및 규모 검토

## 예시 URL

```
GET /logs/trading_volumes?user_id=12345
GET /logs/trading_volumes?user_id=12345&symbol=BTC/USDT
GET /logs/trading_volumes?user_id=12345&start_date=2025-01-01&end_date=2025-01-31
```
""",
    responses={
        200: {
            "description": " 거래량 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "all_symbols": {
                            "summary": "모든 심볼 거래량 조회",
                            "value": {
                                "user_id": "12345",
                                "volumes": {
                                    "BTC/USDT": {
                                        "2025-01-10": 1.5,
                                        "2025-01-11": 2.3,
                                        "2025-01-12": 0.8
                                    },
                                    "ETH/USDT": {
                                        "2025-01-10": 5.2,
                                        "2025-01-11": 3.7
                                    }
                                }
                            }
                        },
                        "single_symbol": {
                            "summary": "특정 심볼 거래량 조회",
                            "value": {
                                "user_id": "12345",
                                "symbol": "BTC/USDT",
                                "volumes": {
                                    "2025-01-10": 1.5,
                                    "2025-01-11": 2.3,
                                    "2025-01-12": 0.8
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_date_format": {
                            "summary": "잘못된 날짜 형식",
                            "value": {
                                "detail": "Invalid date format. Use YYYY-MM-DD"
                            }
                        },
                        "invalid_date_range": {
                            "summary": "잘못된 날짜 범위",
                            "value": {
                                "detail": "Invalid date range"
                            }
                        },
                        "invalid_user_id": {
                            "summary": "잘못된 사용자 ID",
                            "value": {
                                "detail": "Invalid user_id format"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자를 찾을 수 없음",
                            "value": {
                                "detail": "User not found"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "detail": "Failed to connect to Redis"
                            }
                        }
                    }
                }
            }
        }
    }
)
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

    async with redis_context() as redis:
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

@router.get(
    "/total_trading_volume",
    summary="총 거래량 조회 (기간 합산)",
    description="""
# 총 거래량 조회 (기간 합산)

특정 사용자의 특정 심볼 총 거래량을 기간별로 합산하여 조회합니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 ID
- **symbol** (string, required): 거래 심볼
  - 형식: "BTC/USDT", "ETH/USDT" 등
  - 거래소별 심볼 표기법 준수
- **start_date** (string, optional): 시작 날짜
  - 형식: YYYY-MM-DD (예: "2025-01-01")
  - 기본값: 30일 전
- **end_date** (string, optional): 종료 날짜
  - 형식: YYYY-MM-DD (예: "2025-01-31")
  - 기본값: 오늘
- **exchange_name** (string, optional): 거래소 이름
  - 기본값: okx

## 반환 정보

- **user_id** (string): 사용자 ID
- **symbol** (string): 거래 심볼
- **start_date** (string): 조회 시작 날짜
- **end_date** (string): 조회 종료 날짜
- **total_volume** (float): 기간 내 총 거래량 (합산)
  - 단위: 거래 수량 (코인 개수)
  - 매수/매도 거래량 모두 포함

## 사용 시나리오

-  **월별 거래량 집계**: 월간 거래 활동 분석
-  **수수료 할인 조건 확인**: VIP 등급 조건 충족 여부 검증
-  **분기별 리포트**: 분기 실적 집계 및 리포트 생성
-  **거래 목표 달성률**: 설정한 거래량 목표 대비 달성률 확인
- 📋 **세무 신고 자료**: 거래량 기반 세무 신고 자료 준비

## 예시 URL

```
GET /logs/total_trading_volume?user_id=12345&symbol=BTC/USDT
GET /logs/total_trading_volume?user_id=12345&symbol=ETH/USDT&start_date=2025-01-01&end_date=2025-01-31
GET /logs/total_trading_volume?user_id=12345&symbol=SOL/USDT&exchange_name=binance
```
""",
    responses={
        200: {
            "description": " 총 거래량 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "btc_monthly": {
                            "summary": "BTC 월간 거래량",
                            "value": {
                                "user_id": "12345",
                                "symbol": "BTC/USDT",
                                "start_date": "2025-01-01",
                                "end_date": "2025-01-31",
                                "total_volume": 45.7
                            }
                        },
                        "eth_weekly": {
                            "summary": "ETH 주간 거래량",
                            "value": {
                                "user_id": "12345",
                                "symbol": "ETH/USDT",
                                "start_date": "2025-01-06",
                                "end_date": "2025-01-12",
                                "total_volume": 128.3
                            }
                        },
                        "zero_volume": {
                            "summary": "거래 없음",
                            "value": {
                                "user_id": "12345",
                                "symbol": "BTC/USDT",
                                "start_date": "2025-01-01",
                                "end_date": "2025-01-31",
                                "total_volume": 0.0
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청 - 날짜 형식 또는 범위 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_date_range": {
                            "summary": "잘못된 날짜 범위",
                            "value": {
                                "detail": "Invalid date range"
                            }
                        },
                        "invalid_date_format": {
                            "summary": "잘못된 날짜 형식",
                            "value": {
                                "detail": "Invalid date format. Use YYYY-MM-DD"
                            }
                        },
                        "future_date": {
                            "summary": "미래 날짜",
                            "value": {
                                "detail": "End date cannot be in the future"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자 또는 심볼을 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자 없음",
                            "value": {
                                "detail": "User not found"
                            }
                        }
                    }
                }
            }
        },
        422: {
            "description": "🚫 유효성 검증 실패 - 필수 파라미터 누락",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_symbol": {
                            "summary": "심볼 누락",
                            "value": {
                                "detail": "Field required: symbol"
                            }
                        },
                        "missing_user_id": {
                            "summary": "사용자 ID 누락",
                            "value": {
                                "detail": "Field required: user_id"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류 - Redis 연결 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "detail": "Failed to connect to Redis"
                            }
                        }
                    }
                }
            }
        }
    }
)
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

    async with redis_context() as redis:
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


@router.get(
    "/trading_pnl",
    summary="거래 손익 내역 조회 (일별 PnL)",
    description="""
# 거래 손익 내역 조회 (일별 PnL)

사용자의 실현 손익(Profit and Loss) 데이터를 심볼별, 날짜별로 조회합니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 ID
- **symbol** (string, optional): 특정 심볼
  - 미지정 시: 모든 활성 심볼의 손익 조회
  - 지정 시: 해당 심볼만 조회
  - 형식: "BTC/USDT", "ETH/USDT" 등
- **start_date** (string, optional): 시작 날짜
  - 형식: YYYY-MM-DD (예: "2025-01-01")
  - 기본값: 30일 전
- **end_date** (string, optional): 종료 날짜
  - 형식: YYYY-MM-DD (예: "2025-01-31")
  - 기본값: 오늘
- **exchange_name** (string, optional): 거래소 이름
  - 기본값: okx

## 반환 정보

- **user_id** (string): 사용자 ID
- **pnl** (object): 심볼별 손익 데이터
  - 키: 심볼 이름 (예: "BTC/USDT")
  - 값: 날짜별 실현 손익 (object)
    - 키: 날짜 (YYYY-MM-DD)
    - 값: 실현 손익 (float, USDT 단위)
    - 양수: 수익, 음수: 손실

## 사용 시나리오

-  **수익률 분석**: 일별/주별/월별 수익 추이 분석
-  **거래 성과 평가**: 전략별 손익 비교 및 성과 측정
-  **포트폴리오 관리**: 심볼별 수익 기여도 분석
- 💼 **세금 계산 자료**: 실현 손익 기반 양도소득세 계산
-  **목표 달성 추적**: 수익 목표 대비 달성률 모니터링

## 예시 URL

```
GET /logs/trading_pnl?user_id=12345
GET /logs/trading_pnl?user_id=12345&symbol=BTC/USDT
GET /logs/trading_pnl?user_id=12345&start_date=2025-01-01&end_date=2025-01-31
GET /logs/trading_pnl?user_id=12345&symbol=ETH/USDT&exchange_name=binance
```
""",
    responses={
        200: {
            "description": " 손익 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "all_symbols_pnl": {
                            "summary": "모든 심볼 손익",
                            "value": {
                                "user_id": "12345",
                                "pnl": {
                                    "BTC/USDT": {
                                        "2025-01-10": 150.25,
                                        "2025-01-11": -50.75,
                                        "2025-01-12": 320.50
                                    },
                                    "ETH/USDT": {
                                        "2025-01-10": 75.30,
                                        "2025-01-11": 120.45
                                    }
                                }
                            }
                        },
                        "single_symbol_pnl": {
                            "summary": "특정 심볼 손익",
                            "value": {
                                "user_id": "12345",
                                "symbol": "BTC/USDT",
                                "pnl": {
                                    "2025-01-10": 150.25,
                                    "2025-01-11": -50.75,
                                    "2025-01-12": 320.50
                                }
                            }
                        },
                        "no_trades": {
                            "summary": "거래 없음",
                            "value": {
                                "user_id": "12345",
                                "pnl": {}
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청 - 날짜 형식 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_date_format": {
                            "summary": "잘못된 날짜 형식",
                            "value": {
                                "detail": "Invalid date format. Use YYYY-MM-DD"
                            }
                        },
                        "invalid_date_range": {
                            "summary": "잘못된 날짜 범위",
                            "value": {
                                "detail": "Invalid date range"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자를 찾을 수 없음",
                            "value": {
                                "detail": "User not found"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류 - Redis 연결 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "detail": "Failed to connect to Redis"
                            }
                        }
                    }
                }
            }
        }
    }
)
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

    async with redis_context() as redis:
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
    
    
@router.get(
    "/total_trading_pnl",
    summary="총 손익 조회 (기간 합산)",
    description="""
# 총 손익 조회 (기간 합산)

특정 사용자의 특정 심볼 총 실현 손익을 기간별로 합산하여 조회합니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 ID
- **symbol** (string, required): 거래 심볼
  - 형식: "BTC/USDT", "ETH/USDT" 등
  - 거래소별 심볼 표기법 준수
- **start_date** (string, optional): 시작 날짜
  - 형식: YYYY-MM-DD (예: "2025-01-01")
  - 기본값: 30일 전
- **end_date** (string, optional): 종료 날짜
  - 형식: YYYY-MM-DD (예: "2025-01-31")
  - 기본값: 오늘
- **exchange_name** (string, optional): 거래소 이름
  - 기본값: okx

## 반환 정보

- **user_id** (string): 사용자 ID
- **symbol** (string): 거래 심볼
- **start_date** (string): 조회 시작 날짜
- **end_date** (string): 조회 종료 날짜
- **total_pnl** (float): 기간 내 총 실현 손익 (합산)
  - 단위: USDT
  - 양수: 총 수익, 음수: 총 손실
  - 모든 일별 손익 합산 값

## 사용 시나리오

-  **월별 수익 집계**: 월간 실현 손익 합산 및 성과 평가
-  **분기별 리포트**: 분기 실적 집계 및 투자 보고서 작성
- 💼 **세무 신고 자료**: 양도소득세 계산을 위한 연간 실현 손익 집계
-  **목표 달성 평가**: 수익 목표 대비 실제 실현 손익 비교
-  **전략 성과 분석**: 거래 전략별 수익률 및 효율성 평가

## 예시 URL

```
GET /logs/total_trading_pnl?user_id=12345&symbol=BTC/USDT
GET /logs/total_trading_pnl?user_id=12345&symbol=ETH/USDT&start_date=2025-01-01&end_date=2025-01-31
GET /logs/total_trading_pnl?user_id=12345&symbol=SOL/USDT&exchange_name=binance
```
""",
    responses={
        200: {
            "description": " 총 손익 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "profit_month": {
                            "summary": "월간 수익",
                            "value": {
                                "user_id": "12345",
                                "symbol": "BTC/USDT",
                                "start_date": "2025-01-01",
                                "end_date": "2025-01-31",
                                "total_pnl": 1250.50
                            }
                        },
                        "loss_week": {
                            "summary": "주간 손실",
                            "value": {
                                "user_id": "12345",
                                "symbol": "ETH/USDT",
                                "start_date": "2025-01-06",
                                "end_date": "2025-01-12",
                                "total_pnl": -320.75
                            }
                        },
                        "breakeven": {
                            "summary": "손익 없음",
                            "value": {
                                "user_id": "12345",
                                "symbol": "BTC/USDT",
                                "start_date": "2025-01-01",
                                "end_date": "2025-01-31",
                                "total_pnl": 0.0
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청 - 날짜 형식 또는 범위 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_date_range": {
                            "summary": "잘못된 날짜 범위",
                            "value": {
                                "detail": "Invalid date range"
                            }
                        },
                        "invalid_date_format": {
                            "summary": "잘못된 날짜 형식",
                            "value": {
                                "detail": "Invalid date format. Use YYYY-MM-DD"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자 또는 심볼을 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자 없음",
                            "value": {
                                "detail": "User not found"
                            }
                        }
                    }
                }
            }
        },
        422: {
            "description": "🚫 유효성 검증 실패 - 필수 파라미터 누락",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_symbol": {
                            "summary": "심볼 누락",
                            "value": {
                                "detail": "Field required: symbol"
                            }
                        },
                        "missing_user_id": {
                            "summary": "사용자 ID 누락",
                            "value": {
                                "detail": "Field required: user_id"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류 - Redis 연결 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 실패",
                            "value": {
                                "detail": "Failed to connect to Redis"
                            }
                        }
                    }
                }
            }
        }
    }
)
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

    async with redis_context() as redis:
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

@router.websocket(
    "/ws/{user_id}",
)
async def websocket_endpoint(websocket: WebSocket, user_id: str) -> None:
    """
    실시간 로그 메시지를 위한 WebSocket 연결 엔드포인트

    **파라미터:**
    - `user_id`: 사용자 ID

    **동작 방식:**
    1. WebSocket 연결 수립
    2. 실시간 메시지 송수신
    3. 연결 해제 시 정리

    **사용 시나리오:**
    - 실시간 거래 로그 모니터링
    - 시스템 알림 수신
    - 봇 상태 업데이트

    **연결 예시:**
    ```javascript
    const ws = new WebSocket('ws://localhost:8012/logs/ws/12345');
    ws.onmessage = (event) => console.log(event.data);
    ```
    """
    print('️️😈 : ', user_id)
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
        logging.error(f" [ERROR] WebSocket error for user {user_id}: {str(e)}")
        await manager.disconnect(websocket, user_id_int)

@router.post(
    "/send/{user_id}",
    summary="사용자에게 메시지 전송",
    description="""
특정 사용자에게 WebSocket을 통해 메시지를 전송합니다.

**파라미터:**
- `user_id`: 메시지를 받을 사용자 ID
- `message`: 전송할 메시지 내용

**사용 시나리오:**
- 시스템 알림 발송
- 거래 체결 알림
- 에러 메시지 전달
""",
    responses={
        200: {
            "description": "메시지 전송 성공",
            "content": {
                "application/json": {
                    "example": {"status": "success"}
                }
            }
        }
    }
)
async def send_message_to_user(user_id: int, message: str) -> dict[str, str]:
    await manager.send_message_to_user(user_id, message)
    return {"status": "success"}

@router.post(
    "/broadcast",
    summary="모든 사용자에게 메시지 브로드캐스트",
    description="""
연결된 모든 사용자에게 메시지를 동시에 전송합니다.

**파라미터:**
- `message`: 브로드캐스트할 메시지 내용

**사용 시나리오:**
- 시스템 점검 공지
- 긴급 알림
- 전체 사용자 공지사항

**주의사항:**
- 연결된 모든 사용자에게 전송되므로 신중하게 사용하세요
""",
    responses={
        200: {
            "description": "브로드캐스트 성공",
            "content": {
                "application/json": {
                    "example": {"status": "success"}
                }
            }
        }
    }
)
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
        logging.error(f" [ERROR] Failed to get connected users: {str(e)}")
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
        logging.info(f" [LOG] Adding message for user {user_id}: {log_message}")

        # 사용자 존재 여부 확인
        user_exists = await check_user_exists(user_id)
        if not user_exists:
            logging.warning(f" [WARNING] User {user_id} not found")
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
            logging.info(f" [SUCCESS] Message saved for user {user_id}")
        except Exception as redis_error:
            logging.error(f" [ERROR] Redis operation failed: {str(redis_error)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save message: {str(redis_error)}"
            )

        # 웹소켓으로 메시지 전송
        try:
            await manager.send_message_to_user(user_id_int, formatted_message)
            logging.info(f"📢 [BROADCAST] Message sent to user {user_id}")
        except Exception as ws_error:
            logging.warning(f" [WARNING] Failed to broadcast message: {str(ws_error)}")
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
        logging.error(f" [ERROR] {error_msg}")
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
        async with redis_context() as redis:
            key = f"user:{user_id}:messages"
            await redis.delete(key)
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
        logging.info(f" Connection status for user {user_id}: {status}")
        return status
    except Exception as e:
        logging.error(f" [ERROR] Failed to get user status: {str(e)}")
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