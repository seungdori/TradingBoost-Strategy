import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from HYPERRSI.src.api.routes.account import get_balance
from HYPERRSI.src.core.database import Cache  # 캐시 모듈 추가
from HYPERRSI.src.trading.stats import (
    get_pnl_history,
    get_trade_history,
    get_trading_stats,
    get_user_trading_statistics,
)
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger

logger = get_logger(__name__)

# FastAPI 라우터 설정
router = APIRouter(prefix="/stats", tags=["Trading Statistics"])
# 캐시 객체 초기화
cache = Cache()

# 통계 데이터별 최적 캐시 시간 설정 (초 단위)
CACHE_TTL = {
    "summary": 400,          # 5분 (요약 정보는 자주 변경되지 않음)
    "trade_amount": 600,     # 10분 (거래량 데이터는 상대적으로 자주 변경되지 않음)
    "profit_amount": 600,    # 10분 (수익 데이터는 상대적으로 자주 변경되지 않음) 
    "trade_history": 120     # 2분 (거래 내역은 보다 최신 정보가 필요함)
}

# 최근 거래 감지를 위한 최신 거래 ID 캐싱
last_trade_keys = {}

@router.get(
    "/summary",
    summary="거래 요약 통계 조회",
    description="""
# 거래 요약 통계 조회

사용자의 핵심 거래 통계를 한눈에 확인할 수 있는 대시보드용 요약 정보를 제공합니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환
- **refresh** (boolean, optional): 캐시 무시 및 최신 데이터 조회
  - true: 항상 최신 데이터를 조회
  - false: 캐시된 데이터 사용 (기본값, 5분 TTL)

## 동작 방식

1. **캐시 확인**: refresh=false인 경우 캐시된 데이터 확인 (5분 TTL)
2. **통계 조회**: get_user_trading_statistics()로 거래 통계 가져오기
3. **잔고 조회**: get_balance()로 실시간 계정 잔고 가져오기
4. **데이터 가공**: 프론트엔드 요구 형식에 맞게 변환
5. **캐시 저장**: 결과를 Redis에 캐싱 (5분)
6. **응답 반환**: 요약 통계 정보

## 반환 정보

- **status** (string): 응답 상태
  - "success": 정상 조회
  - "no_api_key": API 키 미등록
- **message** (string, optional): 오류 메시지 (status="no_api_key"인 경우)
- **data** (object): 요약 통계 데이터
  - **total_balance** (object): 총 잔고
    - **label** (string): "총 잔고"
    - **value** (float): 잔고 금액 (USDT)
    - **unit** (string): "달러"
  - **total_volume** (object): 총 거래량
    - **label** (string): "거래량"
    - **value** (float): 거래량 (USDT)
    - **unit** (string): "달러"
  - **total_profit** (object): 총 수익금액
    - **label** (string): "수익금액"
    - **value** (float): 누적 손익 (USDT)
    - **unit** (string): "달러"

## 캐시 전략

- **TTL**: 5분 (300초)
- **캐시 키**: `stats:summary:{user_id}`
- **갱신 조건**:
  - refresh=true 파라미터
  - 캐시 만료
  - 최근 거래 감지

## 사용 시나리오

- 📊 **대시보드**: 메인 대시보드의 핵심 지표 표시
- 💰 **계정 현황**: 총 자산 및 수익 한눈에 확인
- 📈 **성과 추적**: 거래량 및 수익률 모니터링
- 🎯 **빠른 개요**: 전체 통계의 요약본 제공

## 예시 URL

```
GET /stats/summary?user_id=518796558012178692
GET /stats/summary?user_id=1709556958&refresh=true
```
""",
    responses={
        200: {
            "description": "✅ 요약 통계 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "profitable_trader": {
                            "summary": "수익 중인 계정",
                            "value": {
                                "status": "success",
                                "data": {
                                    "total_balance": {
                                        "label": "총 잔고",
                                        "value": 5000.0,
                                        "unit": "달러"
                                    },
                                    "total_volume": {
                                        "label": "거래량",
                                        "value": 50000.0,
                                        "unit": "달러"
                                    },
                                    "total_profit": {
                                        "label": "수익금액",
                                        "value": 500.0,
                                        "unit": "달러"
                                    }
                                }
                            }
                        },
                        "losing_trader": {
                            "summary": "손실 중인 계정",
                            "value": {
                                "status": "success",
                                "data": {
                                    "total_balance": {
                                        "label": "총 잔고",
                                        "value": 950.0,
                                        "unit": "달러"
                                    },
                                    "total_volume": {
                                        "label": "거래량",
                                        "value": 10000.0,
                                        "unit": "달러"
                                    },
                                    "total_profit": {
                                        "label": "수익금액",
                                        "value": -50.0,
                                        "unit": "달러"
                                    }
                                }
                            }
                        },
                        "no_api_key": {
                            "summary": "API 키 미등록",
                            "value": {
                                "status": "no_api_key",
                                "message": "API 키가 등록되지 않았습니다. API 키를 먼저 등록해주세요.",
                                "data": {
                                    "total_balance": {
                                        "label": "총 잔고",
                                        "value": 0,
                                        "unit": "달러"
                                    },
                                    "total_volume": {
                                        "label": "거래량",
                                        "value": 0,
                                        "unit": "달러"
                                    },
                                    "total_profit": {
                                        "label": "수익금액",
                                        "value": 0,
                                        "unit": "달러"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": "🔍 리소스를 찾을 수 없음",
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
        500: {
            "description": "💥 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "server_error": {
                            "summary": "서버 내부 오류",
                            "value": {
                                "detail": "Failed to fetch statistics"
                            }
                        },
                        "redis_error": {
                            "summary": "Redis 연결 오류",
                            "value": {
                                "detail": "Cache connection failed"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_stats_summary(
    user_id: str = Query(..., description="사용자 ID"),
    refresh: bool = Query(False, description="캐시를 무시하고 최신 데이터 조회")
) -> Dict[str, Any]:
    """
    거래 요약 통계 정보를 반환합니다.

    Returns:
        Dict: 총 잔고, 거래량, 수익금액 등의 요약 정보
    """
    try:
        start_time = time.time()
        # 캐시 키 생성 및 캐시 확인
        cache_key = f"stats:summary:{user_id}"
        
        if not refresh:
            cached_data = await cache.get(cache_key)
            if cached_data:
                return cached_data
            
        # 기존 통계 정보 가져오기
        trading_stats = await get_user_trading_statistics(user_id)
        # 실제 계정 잔고 정보 가져오기
        balance_info = await get_balance(str(user_id))
        
        # 프론트엔드 요구 형식에 맞게 데이터 가공
        result = {
            "status": "success",
            "data": {
                "total_balance": {
                    "label": "총 잔고",
                    "value": round(balance_info.total_equity, 2),
                    "unit": "달러"
                },
                "total_volume": {
                    "label": "거래량",
                    "value": round(trading_stats.get("total_volume", 0), 2),
                    "unit": "달러"
                },
                "total_profit": {
                    "label": "수익금액",
                    "value": round(trading_stats.get("total_pnl", 0), 2),
                    "unit": "달러"
                }
            }
        }
        
        # 결과 캐싱
        await cache.set(cache_key, result, expire=CACHE_TTL["summary"])
        print("================================================")
        end_time = time.time()
        print(f"get_stats_summary 소요시간: {end_time - start_time}초")
        print("================================================")
        return result
    except HTTPException as e:
        # API 키가 없는 경우 적절한 에러 반환
        if e.status_code == 404 and "API keys not found" in str(e.detail):
            logger.info(f"사용자 {user_id}의 API 키가 등록되지 않음")
            return {
                "status": "no_api_key",
                "message": "API 키가 등록되지 않았습니다. API 키를 먼저 등록해주세요.",
                "data": {
                    "total_balance": {
                        "label": "총 잔고",
                        "value": 0,
                        "unit": "달러"
                    },
                    "total_volume": {
                        "label": "거래량",
                        "value": 0,
                        "unit": "달러"
                    },
                    "total_profit": {
                        "label": "수익금액",
                        "value": 0,
                        "unit": "달러"
                    }
                }
            }
        # 기타 HTTPException은 그대로 전달
        raise e
    except Exception as e:
        logger.error(f"통계 요약 정보 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/trade-amount",
    summary="일별 거래량 차트 데이터 조회",
    description="""
# 일별 거래량 차트 데이터 조회

사용자의 일별 거래량(거래 금액)을 시각화하기 위한 차트 데이터를 제공합니다. 지정된 기간 동안의 거래 활동을 추적하고 분석할 수 있습니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 예시: "518796558012178692", "1709556958"
- **start_date** (string, optional): 조회 시작일 (YYYY-MM-DD 형식)
  - 미지정 시: end_date 기준 9일 전 (총 10일 데이터)
  - 예시: "2025-01-01"
- **end_date** (string, optional): 조회 종료일 (YYYY-MM-DD 형식)
  - 미지정 시: 오늘 날짜
  - 예시: "2025-01-10"
- **refresh** (boolean, optional): 캐시 무시 플래그
  - true: 최신 데이터 강제 조회
  - false: 캐시 사용 (기본값, 10분 TTL)

## 동작 방식

1. **날짜 범위 설정**: start_date, end_date 파라미터로 조회 기간 결정
2. **캐시 확인**: refresh=false인 경우 Redis 캐시 확인 (10분 TTL)
3. **거래 내역 조회**: get_trade_history()로 최근 100건 조회
4. **가격 계수 적용**: 심볼별 가격 범위에 따라 적절한 계수 적용
   - 가격 >10,000: 계수 0.01 (BTC, ETH 등)
   - 가격 1,000~10,000: 계수 0.1 (중간 가격대)
   - 가격 0.1~1,000: 계수 1.0 (알트코인)
5. **일별 집계**: 거래 금액 = size × entry_price × coefficient
6. **차트 데이터 생성**: 날짜별 거래량을 배열 형태로 변환
7. **캐시 저장**: 결과를 Redis에 캐싱 (10분)
8. **응답 반환**: 기간 정보와 차트 데이터

## 거래량 계산 로직

거래량은 다음 공식으로 계산됩니다:

```
거래량 = 거래 크기(size) × 진입 가격(entry_price) × 가격 계수(coefficient)
```

**가격 계수 적용 기준**:
- **>10,000 USDT**: 계수 0.01 (예: BTC $92,000 → 0.01배)
- **1,000~10,000 USDT**: 계수 0.1 (예: ETH $3,500 → 0.1배)
- **0.1~1,000 USDT**: 계수 1.0 (예: XRP $2.5 → 1배)

## 반환 데이터 구조

- **status** (string): 응답 상태 ("success" 또는 "no_api_key")
- **message** (string, optional): 오류 메시지 (API 키 미등록 시)
- **data** (object): 차트 데이터
  - **period** (string): 조회 기간 (예: "2025-01-01 - 2025-01-10")
  - **chart_data** (array of objects): 일별 거래량 데이터
    - **date** (string): 날짜 (YYYY-MM-DD)
    - **amount** (float): 거래량 (USDT)

## 캐시 전략

- **TTL**: 10분 (600초)
- **캐시 키**: `stats:trade_amount:{user_id}:{start_date}:{end_date}`
- **갱신 조건**:
  - refresh=true 파라미터
  - 캐시 만료
  - 날짜 범위 변경

## 사용 시나리오

- 📊 **활동 분석**: 일별 거래 활동 추이 모니터링
- 📈 **거래 패턴**: 활발한 거래 시기와 조용한 시기 파악
- 💰 **볼륨 추적**: 거래량 변화를 통한 전략 효과 분석
- 🎯 **성과 평가**: 거래 활동과 수익률 간의 상관관계 분석
- 📅 **기간 비교**: 주별/월별 거래량 비교 분석

## 예시 URL

```
GET /stats/trade-amount?user_id=518796558012178692
GET /stats/trade-amount?user_id=1709556958&start_date=2025-01-01&end_date=2025-01-10
GET /stats/trade-amount?user_id=518796558012178692&refresh=true
```

## 예시 curl 명령

```bash
curl -X GET "http://localhost:8000/stats/trade-amount?user_id=518796558012178692&start_date=2025-01-01&end_date=2025-01-10"
```
""",
    responses={
        200: {
            "description": "✅ 거래량 차트 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "active_trading_period": {
                            "summary": "활발한 거래 기간",
                            "value": {
                                "status": "success",
                                "data": {
                                    "period": "2025-01-01 - 2025-01-10",
                                    "chart_data": [
                                        {"date": "2025-01-01", "amount": 1500.50},
                                        {"date": "2025-01-02", "amount": 2300.75},
                                        {"date": "2025-01-03", "amount": 1800.25},
                                        {"date": "2025-01-04", "amount": 3200.00},
                                        {"date": "2025-01-05", "amount": 2700.50},
                                        {"date": "2025-01-06", "amount": 1900.00},
                                        {"date": "2025-01-07", "amount": 2500.75},
                                        {"date": "2025-01-08", "amount": 3100.25},
                                        {"date": "2025-01-09", "amount": 2400.50},
                                        {"date": "2025-01-10", "amount": 2800.00}
                                    ]
                                }
                            }
                        },
                        "quiet_period": {
                            "summary": "조용한 거래 기간",
                            "value": {
                                "status": "success",
                                "data": {
                                    "period": "2025-01-01 - 2025-01-10",
                                    "chart_data": [
                                        {"date": "2025-01-01", "amount": 0},
                                        {"date": "2025-01-02", "amount": 0},
                                        {"date": "2025-01-03", "amount": 500.50},
                                        {"date": "2025-01-04", "amount": 0},
                                        {"date": "2025-01-05", "amount": 750.25},
                                        {"date": "2025-01-06", "amount": 0},
                                        {"date": "2025-01-07", "amount": 0},
                                        {"date": "2025-01-08", "amount": 300.00},
                                        {"date": "2025-01-09", "amount": 0},
                                        {"date": "2025-01-10", "amount": 0}
                                    ]
                                }
                            }
                        },
                        "no_api_key": {
                            "summary": "API 키 미등록",
                            "value": {
                                "status": "no_api_key",
                                "message": "API 키가 등록되지 않았습니다. API 키를 먼저 등록해주세요.",
                                "data": {
                                    "period": "2025-01-01 - 2025-01-10",
                                    "chart_data": [
                                        {"date": "2025-01-01", "amount": 0},
                                        {"date": "2025-01-02", "amount": 0},
                                        {"date": "2025-01-03", "amount": 0},
                                        {"date": "2025-01-04", "amount": 0},
                                        {"date": "2025-01-05", "amount": 0},
                                        {"date": "2025-01-06", "amount": 0},
                                        {"date": "2025-01-07", "amount": 0},
                                        {"date": "2025-01-08", "amount": 0},
                                        {"date": "2025-01-09", "amount": 0},
                                        {"date": "2025-01-10", "amount": 0}
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_date_format": {
                            "summary": "날짜 형식 오류",
                            "value": {
                                "detail": "Invalid date format. Use YYYY-MM-DD"
                            }
                        },
                        "invalid_date_range": {
                            "summary": "날짜 범위 오류",
                            "value": {
                                "detail": "start_date must be before end_date"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": "🔍 리소스를 찾을 수 없음",
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
        500: {
            "description": "💥 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "server_error": {
                            "summary": "서버 내부 오류",
                            "value": {
                                "detail": "거래 금액 차트 데이터를 불러오는 데 실패했습니다."
                            }
                        },
                        "redis_error": {
                            "summary": "Redis 연결 오류",
                            "value": {
                                "detail": "Cache connection failed"
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "🔧 서비스 이용 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_api_unavailable": {
                            "summary": "거래소 API 다운타임",
                            "value": {
                                "detail": "Exchange API is temporarily unavailable"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_trade_amount_chart(
    user_id: str = Query(..., description="사용자 ID"),
    start_date: Optional[str] = Query(None, description="시작일 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="종료일 (YYYY-MM-DD)"),
    refresh: bool = Query(False, description="캐시를 무시하고 최신 데이터 조회")
) -> Dict[str, Any]:
    """
    기간별 거래 금액 차트 데이터를 반환합니다.

    Returns:
        Dict: 일별 거래 금액 데이터
    """
    # 날짜 범위 설정 (기본값: 최근 10일)
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=9)
        start_date = start.strftime("%Y-%m-%d")
    
    # 날짜 범위 생성 (catch 블록에서도 사용하기 위해 먼저 생성)
    date_range = []
    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while current_date <= end:
        date_str = current_date.strftime("%Y-%m-%d")
        date_range.append(date_str)
        current_date += timedelta(days=1)
    
    try:
        
        # 캐시 키 생성 및 캐시 확인
        cache_key = f"stats:trade_amount:{user_id}:{start_date}:{end_date}"
        
        if not refresh:
            cached_data = await cache.get(cache_key)
            if cached_data:
                return cached_data
            
        # 거래 내역 가져오기
        trade_history = await get_trade_history(user_id, limit=100)
        
        # 날짜별 거래 금액 집계
        daily_amounts = {}
        for date in date_range:
            daily_amounts[date] = 0
        
        # 거래 내역에서 날짜별 금액 계산
        for trade in trade_history:
            if 'timestamp' in trade and 'size' in trade and 'entry_price' in trade:
                try:
                    trade_date = datetime.strptime(trade['timestamp'].split(' ')[0], "%Y-%m-%d")
                    date_str = trade_date.strftime("%Y-%m-%d")
                    
                    if date_str in daily_amounts and start_date <= date_str <= end_date:
                        # 거래 금액 = 수량 x 진입 가격 (가격 범위에 따라 계수 적용)
                        entry_price = float(trade['entry_price'])
                        size = float(trade['size'])
                        
                        # 가격 범위에 따른 계수 적용
                        if entry_price > 10000:
                            coefficient = 0.01
                        elif 1000 <= entry_price <= 10000:
                            coefficient = 0.1
                        elif 0.1 <= entry_price < 1000:
                            coefficient = 1
                        else:
                            coefficient = 1  # 기본값
                            
                        amount = size * entry_price * coefficient
                        daily_amounts[date_str] += amount
                except Exception as e:
                    logger.error(f"거래 데이터 처리 오류: {str(e)}")
        
        # 차트 데이터 형식으로 변환
        chart_data = [
            {
                "date": date,
                "amount": round(daily_amounts[date], 2)
            }
            for date in date_range
        ]
        
        result = {
            "status": "success",
            "data": {
                "period": f"{start_date} - {end_date}",
                "chart_data": chart_data
            }
        }
        
        # 결과 캐싱
        await cache.set(cache_key, result, expire=CACHE_TTL["trade_amount"])
        return result
    except HTTPException as e:
        # API 키가 없는 경우 적절한 에러 반환
        if e.status_code == 404 and "API keys not found" in str(e.detail):
            logger.info(f"사용자 {user_id}의 API 키가 등록되지 않음")
            return {
                "status": "no_api_key",
                "message": "API 키가 등록되지 않았습니다. API 키를 먼저 등록해주세요.",
                "data": {
                    "period": f"{start_date} - {end_date}",
                    "chart_data": [{"date": date, "amount": 0} for date in date_range]
                }
            }
        raise e
    except Exception as e:
        logger.error(f"거래 금액 차트 데이터 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="거래 금액 차트 데이터를 불러오는 데 실패했습니다.")

@router.get(
    "/profit-amount",
    summary="일별 수익 차트 데이터 조회",
    description="""
# 일별 수익 차트 데이터 조회

사용자의 일별 손익(PnL)과 누적 수익을 시각화하기 위한 차트 데이터를 제공합니다. 거래 성과와 승률을 함께 추적하여 전략 효율성을 평가할 수 있습니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 예시: "518796558012178692", "1709556958"
- **start_date** (string, optional): 조회 시작일 (YYYY-MM-DD 형식)
  - 미지정 시: end_date 기준 9일 전 (총 10일 데이터)
  - 예시: "2025-01-01"
- **end_date** (string, optional): 조회 종료일 (YYYY-MM-DD 형식)
  - 미지정 시: 오늘 날짜
  - 예시: "2025-01-10"
- **refresh** (boolean, optional): 캐시 무시 플래그
  - true: 최신 데이터 강제 조회
  - false: 캐시 사용 (기본값, 10분 TTL)

## 동작 방식

1. **날짜 범위 설정**: start_date, end_date 파라미터로 조회 기간 결정
2. **캐시 확인**: refresh=false인 경우 Redis 캐시 확인 (10분 TTL)
3. **PnL 내역 조회**: get_pnl_history()로 최근 100건의 손익 기록 조회
4. **일별 집계**: 날짜별 손익 합산 (realized PnL 기준)
5. **누적 손익 계산**: 기간 내 누적 수익 추이 계산
6. **통계 조회**: 총 거래 횟수, 승률, 승리/패배 거래 수 조회
7. **차트 데이터 생성**: 날짜별 수익과 누적 수익을 배열 형태로 변환
8. **캐시 저장**: 결과를 Redis에 캐싱 (10분)
9. **응답 반환**: 기간 정보, 차트 데이터, 거래 통계

## 수익 계산 로직

**일별 수익**: 해당 날짜에 청산된 모든 포지션의 realized PnL 합계

**누적 수익**: 기간 시작일부터 현재 날짜까지의 누적 손익

```
일별_수익 = Σ(해당_날짜_청산된_포지션의_PnL)
누적_수익 = 전일_누적_수익 + 당일_수익
```

## 반환 데이터 구조

- **status** (string): 응답 상태 ("success" 또는 "no_api_key")
- **message** (string, optional): 오류 메시지 (API 키 미등록 시)
- **data** (object): 차트 및 통계 데이터
  - **period** (string): 조회 기간 (예: "2025-01-01 - 2025-01-10")
  - **chart_data** (array of objects): 일별 수익 데이터
    - **date** (string): 날짜 (YYYY-MM-DD)
    - **profit** (float): 일별 수익 (USDT)
    - **cumulative_profit** (float): 누적 수익 (USDT)
  - **stats** (object): 거래 통계
    - **total_trades** (integer): 총 거래 횟수
    - **win_rate** (float): 승률 (%)
    - **winning_trades** (integer): 수익 거래 수
    - **losing_trades** (integer): 손실 거래 수

## 캐시 전략

- **TTL**: 10분 (600초)
- **캐시 키**: `stats:profit_amount:{user_id}:{start_date}:{end_date}`
- **갱신 조건**:
  - refresh=true 파라미터
  - 캐시 만료
  - 날짜 범위 변경

## 사용 시나리오

- 📊 **성과 추적**: 일별 손익 추이 모니터링 및 분석
- 💰 **수익성 평가**: 누적 수익을 통한 전략 수익성 검증
- 📈 **트렌드 분석**: 수익 증가/감소 추세 파악
- 🎯 **승률 모니터링**: 승률 및 거래 성공률 추적
- 🔍 **손실 분석**: 손실 발생 패턴 및 원인 파악
- 📅 **기간 비교**: 주별/월별 수익 성과 비교

## 예시 URL

```
GET /stats/profit-amount?user_id=518796558012178692
GET /stats/profit-amount?user_id=1709556958&start_date=2025-01-01&end_date=2025-01-10
GET /stats/profit-amount?user_id=518796558012178692&refresh=true
```

## 예시 curl 명령

```bash
curl -X GET "http://localhost:8000/stats/profit-amount?user_id=518796558012178692&start_date=2025-01-01&end_date=2025-01-10"
```
""",
    responses={
        200: {
            "description": "✅ 수익 차트 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "profitable_period": {
                            "summary": "수익 발생 기간",
                            "value": {
                                "status": "success",
                                "data": {
                                    "period": "2025-01-01 - 2025-01-10",
                                    "chart_data": [
                                        {"date": "2025-01-01", "profit": 50.25, "cumulative_profit": 50.25},
                                        {"date": "2025-01-02", "profit": 75.50, "cumulative_profit": 125.75},
                                        {"date": "2025-01-03", "profit": -20.00, "cumulative_profit": 105.75},
                                        {"date": "2025-01-04", "profit": 100.00, "cumulative_profit": 205.75},
                                        {"date": "2025-01-05", "profit": 30.75, "cumulative_profit": 236.50},
                                        {"date": "2025-01-06", "profit": -15.50, "cumulative_profit": 221.00},
                                        {"date": "2025-01-07", "profit": 60.25, "cumulative_profit": 281.25},
                                        {"date": "2025-01-08", "profit": 90.00, "cumulative_profit": 371.25},
                                        {"date": "2025-01-09", "profit": -10.25, "cumulative_profit": 361.00},
                                        {"date": "2025-01-10", "profit": 80.50, "cumulative_profit": 441.50}
                                    ],
                                    "stats": {
                                        "total_trades": 42,
                                        "win_rate": 71.4,
                                        "winning_trades": 30,
                                        "losing_trades": 12
                                    }
                                }
                            }
                        },
                        "losing_period": {
                            "summary": "손실 발생 기간",
                            "value": {
                                "status": "success",
                                "data": {
                                    "period": "2025-01-01 - 2025-01-10",
                                    "chart_data": [
                                        {"date": "2025-01-01", "profit": -30.00, "cumulative_profit": -30.00},
                                        {"date": "2025-01-02", "profit": -45.50, "cumulative_profit": -75.50},
                                        {"date": "2025-01-03", "profit": 20.00, "cumulative_profit": -55.50},
                                        {"date": "2025-01-04", "profit": -60.00, "cumulative_profit": -115.50},
                                        {"date": "2025-01-05", "profit": -25.75, "cumulative_profit": -141.25},
                                        {"date": "2025-01-06", "profit": 15.00, "cumulative_profit": -126.25},
                                        {"date": "2025-01-07", "profit": -40.00, "cumulative_profit": -166.25},
                                        {"date": "2025-01-08", "profit": -55.25, "cumulative_profit": -221.50},
                                        {"date": "2025-01-09", "profit": 10.50, "cumulative_profit": -211.00},
                                        {"date": "2025-01-10", "profit": -35.00, "cumulative_profit": -246.00}
                                    ],
                                    "stats": {
                                        "total_trades": 28,
                                        "win_rate": 35.7,
                                        "winning_trades": 10,
                                        "losing_trades": 18
                                    }
                                }
                            }
                        },
                        "mixed_performance": {
                            "summary": "혼합 성과 (승률 높음, 손실 큼)",
                            "value": {
                                "status": "success",
                                "data": {
                                    "period": "2025-01-01 - 2025-01-10",
                                    "chart_data": [
                                        {"date": "2025-01-01", "profit": 10.00, "cumulative_profit": 10.00},
                                        {"date": "2025-01-02", "profit": 15.50, "cumulative_profit": 25.50},
                                        {"date": "2025-01-03", "profit": 8.25, "cumulative_profit": 33.75},
                                        {"date": "2025-01-04", "profit": -150.00, "cumulative_profit": -116.25},
                                        {"date": "2025-01-05", "profit": 12.50, "cumulative_profit": -103.75},
                                        {"date": "2025-01-06", "profit": 9.00, "cumulative_profit": -94.75},
                                        {"date": "2025-01-07", "profit": 11.25, "cumulative_profit": -83.50},
                                        {"date": "2025-01-08", "profit": 13.75, "cumulative_profit": -69.75},
                                        {"date": "2025-01-09", "profit": 10.50, "cumulative_profit": -59.25},
                                        {"date": "2025-01-10", "profit": 14.00, "cumulative_profit": -45.25}
                                    ],
                                    "stats": {
                                        "total_trades": 35,
                                        "win_rate": 88.6,
                                        "winning_trades": 31,
                                        "losing_trades": 4
                                    }
                                }
                            }
                        },
                        "no_api_key": {
                            "summary": "API 키 미등록",
                            "value": {
                                "status": "no_api_key",
                                "message": "API 키가 등록되지 않았습니다. API 키를 먼저 등록해주세요.",
                                "data": {
                                    "period": "2025-01-01 - 2025-01-10",
                                    "chart_data": [
                                        {"date": "2025-01-01", "profit": 0, "cumulative_profit": 0},
                                        {"date": "2025-01-02", "profit": 0, "cumulative_profit": 0},
                                        {"date": "2025-01-03", "profit": 0, "cumulative_profit": 0},
                                        {"date": "2025-01-04", "profit": 0, "cumulative_profit": 0},
                                        {"date": "2025-01-05", "profit": 0, "cumulative_profit": 0},
                                        {"date": "2025-01-06", "profit": 0, "cumulative_profit": 0},
                                        {"date": "2025-01-07", "profit": 0, "cumulative_profit": 0},
                                        {"date": "2025-01-08", "profit": 0, "cumulative_profit": 0},
                                        {"date": "2025-01-09", "profit": 0, "cumulative_profit": 0},
                                        {"date": "2025-01-10", "profit": 0, "cumulative_profit": 0}
                                    ],
                                    "stats": {
                                        "total_trades": 0,
                                        "win_rate": 0,
                                        "winning_trades": 0,
                                        "losing_trades": 0
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_date_format": {
                            "summary": "날짜 형식 오류",
                            "value": {
                                "detail": "Invalid date format. Use YYYY-MM-DD"
                            }
                        },
                        "invalid_date_range": {
                            "summary": "날짜 범위 오류",
                            "value": {
                                "detail": "start_date must be before end_date"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": "🔍 리소스를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자 없음",
                            "value": {
                                "detail": "User not found"
                            }
                        },
                        "no_pnl_data": {
                            "summary": "손익 데이터 없음",
                            "value": {
                                "detail": "No PnL data found for the specified period"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "server_error": {
                            "summary": "서버 내부 오류",
                            "value": {
                                "detail": "수익 금액 차트 데이터를 불러오는 데 실패했습니다."
                            }
                        },
                        "redis_error": {
                            "summary": "Redis 연결 오류",
                            "value": {
                                "detail": "Cache connection failed"
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "🔧 서비스 이용 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_api_unavailable": {
                            "summary": "거래소 API 다운타임",
                            "value": {
                                "detail": "Exchange API is temporarily unavailable"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_profit_amount_chart(
    user_id: str = Query(..., description="사용자 ID"),
    start_date: Optional[str] = Query(None, description="시작일 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="종료일 (YYYY-MM-DD)"),
    refresh: bool = Query(False, description="캐시를 무시하고 최신 데이터 조회")
) -> Dict[str, Any]:
    """
    기간별 수익 금액 차트 데이터를 반환합니다.

    Returns:
        Dict: 일별 수익 금액 데이터
    """
    # 날짜 범위 설정 (기본값: 최근 10일)
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=9)
        start_date = start.strftime("%Y-%m-%d")
    
    # 날짜 범위 생성 (catch 블록에서도 사용하기 위해 먼저 생성)
    date_range = []
    current_date = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while current_date <= end:
        date_str = current_date.strftime("%Y-%m-%d")
        date_range.append(date_str)
        current_date += timedelta(days=1)
    
    try:
        
        # 캐시 키 생성 및 캐시 확인
        cache_key = f"stats:profit_amount:{user_id}:{start_date}:{end_date}"
        
        if not refresh:
            cached_data = await cache.get(cache_key)
            if cached_data:
                return cached_data
            
        # PnL 내역 가져오기
        pnl_history = await get_pnl_history(user_id, limit=100)
        
        # 날짜별 수익 금액 집계
        daily_profits = {}
        for date in date_range:
            daily_profits[date] = 0
        
        # PnL 내역에서 날짜별 수익 계산
        for pnl_record in pnl_history:
            if 'timestamp' in pnl_record and 'pnl' in pnl_record:
                try:
                    pnl_date = datetime.strptime(pnl_record['timestamp'].split(' ')[0], "%Y-%m-%d")
                    date_str = pnl_date.strftime("%Y-%m-%d")
                    
                    if date_str in daily_profits and start_date <= date_str <= end_date:
                        daily_profits[date_str] += float(pnl_record['pnl'])
                except Exception as e:
                    logger.error(f"PnL 데이터 처리 오류: {str(e)}")
        
        # 차트 데이터 형식으로 변환 (누적 수익)
        cumulative_profit = 0
        chart_data = []
        
        for date in date_range:
            cumulative_profit += daily_profits[date]
            chart_data.append({
                "date": date,
                "profit": round(daily_profits[date], 2),
                "cumulative_profit": round(cumulative_profit, 2)
            })
        
        # 거래 통계 정보 조회
        trading_stats = await get_user_trading_statistics(user_id)
        
        result = {
            "status": "success",
            "data": {
                "period": f"{start_date} - {end_date}",
                "chart_data": chart_data,
                "stats": {
                    "total_trades": trading_stats.get("total_trades", 0),
                    "win_rate": round(trading_stats.get("win_rate", 0), 1),
                    "winning_trades": trading_stats.get("winning_trades", 0),
                    "losing_trades": trading_stats.get("losing_trades", 0)
                }
            }
        }
        
        # 결과 캐싱
        await cache.set(cache_key, result, expire=CACHE_TTL["profit_amount"])
        return result
    except HTTPException as e:
        # API 키가 없는 경우 적절한 에러 반환
        if e.status_code == 404 and "API keys not found" in str(e.detail):
            logger.info(f"사용자 {user_id}의 API 키가 등록되지 않음")
            return {
                "status": "no_api_key",
                "message": "API 키가 등록되지 않았습니다. API 키를 먼저 등록해주세요.",
                "data": {
                    "period": f"{start_date} - {end_date}",
                    "chart_data": [{"date": date, "profit": 0, "cumulative_profit": 0} for date in date_range],
                    "stats": {
                        "total_trades": 0,
                        "win_rate": 0,
                        "winning_trades": 0,
                        "losing_trades": 0
                    }
                }
            }
        raise e
    except Exception as e:
        logger.error(f"수익 금액 차트 데이터 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="수익 금액 차트 데이터를 불러오는 데 실패했습니다.")

@router.get(
    "/trade-history",
    summary="거래 내역 조회",
    description="""
# 거래 내역 조회

사용자의 상세 거래 내역을 조회합니다. 진입/청산 가격, 손익, 거래 상태 등 모든 거래 정보를 제공하며, 상태별 필터링이 가능합니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 예시: "518796558012178692", "1709556958"
- **limit** (integer, optional): 조회할 거래 내역 수
  - 기본값: 10
  - 범위: 1-100
  - 예시: 20, 50, 100
- **status** (string, optional): 거래 상태 필터
  - "open": 진행 중인 포지션
  - "closed": 청산 완료된 포지션
  - 미지정: 모든 상태
- **refresh** (boolean, optional): 캐시 무시 플래그
  - true: 최신 데이터 강제 조회
  - false: 캐시 사용 (기본값, 2분 TTL)

## 동작 방식

1. **캐시 키 생성**: user_id, limit, status 기반 캐시 키 생성
2. **최신 거래 확인**: Redis에서 최근 거래 ID 확인 (스마트 캐시 무효화)
3. **캐시 확인**: 새 거래가 없고 refresh=false인 경우 캐시 사용 (2분 TTL)
4. **거래 내역 조회**: get_trade_history()로 거래 내역 조회
5. **상태 필터링**: status 파라미터에 따른 필터링 적용
6. **데이터 가공**: 프론트엔드 형식으로 변환
   - timestamp, symbol, coin_name 추출
   - entry_price, exit_price, size 파싱
   - pnl, pnl_percent 계산 및 변환
   - status, side, close_type 정보 포함
7. **캐시 저장**: 결과를 Redis에 캐싱 (2분)
8. **응답 반환**: 거래 내역 배열

## 스마트 캐시 무효화

이 엔드포인트는 지능형 캐시 무효화 메커니즘을 사용합니다:

- **거래 감지**: Redis의 `user:{user_id}:history` 키에서 최신 거래 ID 추적
- **자동 갱신**: 새로운 거래가 감지되면 자동으로 캐시 무효화
- **빠른 응답**: 거래가 없을 때는 캐시된 데이터로 빠른 응답 (<50ms)

## 반환 데이터 구조

- **status** (string): 응답 상태 ("success" 또는 "no_api_key")
- **message** (string, optional): 오류 메시지 (API 키 미등록 시)
- **data** (array of objects): 거래 내역 배열
  - **timestamp** (string): 거래 시간 (YYYY-MM-DD HH:MM:SS)
  - **symbol** (string): 거래 심볼 (예: "BTC-USDT-SWAP")
  - **coin_name** (string): 코인 이름 (예: "BTC")
  - **entry_price** (float): 진입 가격 (USDT)
  - **exit_price** (float, nullable): 청산 가격 (USDT, open 상태인 경우 null)
  - **size** (float): 거래 크기 (계약 수)
  - **pnl** (float, nullable): 실현 손익 (USDT, open 상태인 경우 null)
  - **pnl_percent** (float, nullable): 손익률 (%, open 상태인 경우 null)
  - **status** (string): 거래 상태 ("open" 또는 "closed")
  - **side** (string): 포지션 방향 ("long" 또는 "short")
  - **close_type** (string): 청산 유형 (예: "tp", "sl", "manual", "market")

## 캐시 전략

- **TTL**: 2분 (120초)
- **캐시 키**: `stats:trade_history:{user_id}:{limit}:{status or 'all'}`
- **무효화 조건**:
  - refresh=true 파라미터
  - 캐시 만료
  - 새로운 거래 감지 (최신 거래 ID 변경)
  - limit 또는 status 파라미터 변경

## 사용 시나리오

- 📊 **거래 분석**: 과거 거래 패턴 및 성과 분석
- 💰 **손익 추적**: 개별 거래의 수익/손실 확인
- 📈 **전략 검증**: 진입/청산 가격으로 전략 효과 평가
- 🎯 **포지션 모니터링**: 현재 진행 중인 포지션 실시간 추적
- 🔍 **상세 내역**: 특정 심볼이나 기간의 거래 상세 정보
- 📅 **거래 기록**: 전체 거래 히스토리 관리 및 보관

## 예시 URL

```
GET /stats/trade-history?user_id=518796558012178692
GET /stats/trade-history?user_id=1709556958&limit=20&status=closed
GET /stats/trade-history?user_id=518796558012178692&limit=50&refresh=true
```

## 예시 curl 명령

```bash
# 최근 10건 조회
curl -X GET "http://localhost:8000/stats/trade-history?user_id=518796558012178692"

# 청산된 거래 20건 조회
curl -X GET "http://localhost:8000/stats/trade-history?user_id=518796558012178692&limit=20&status=closed"

# 캐시 무시하고 최신 50건 조회
curl -X GET "http://localhost:8000/stats/trade-history?user_id=518796558012178692&limit=50&refresh=true"
```
""",
    responses={
        200: {
            "description": "✅ 거래 내역 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "closed_trades": {
                            "summary": "청산 완료된 거래 내역",
                            "value": {
                                "status": "success",
                                "data": [
                                    {
                                        "timestamp": "2025-01-10 14:30:25",
                                        "symbol": "BTC-USDT-SWAP",
                                        "coin_name": "BTC",
                                        "entry_price": 92000.0,
                                        "exit_price": 92500.0,
                                        "size": 0.1,
                                        "pnl": 50.0,
                                        "pnl_percent": 0.54,
                                        "status": "closed",
                                        "side": "long",
                                        "close_type": "tp"
                                    },
                                    {
                                        "timestamp": "2025-01-10 12:15:30",
                                        "symbol": "ETH-USDT-SWAP",
                                        "coin_name": "ETH",
                                        "entry_price": 3500.0,
                                        "exit_price": 3450.0,
                                        "size": 1.0,
                                        "pnl": -50.0,
                                        "pnl_percent": -1.43,
                                        "status": "closed",
                                        "side": "long",
                                        "close_type": "sl"
                                    },
                                    {
                                        "timestamp": "2025-01-09 18:45:12",
                                        "symbol": "SOL-USDT-SWAP",
                                        "coin_name": "SOL",
                                        "entry_price": 180.0,
                                        "exit_price": 185.0,
                                        "size": 10.0,
                                        "pnl": 50.0,
                                        "pnl_percent": 2.78,
                                        "status": "closed",
                                        "side": "long",
                                        "close_type": "manual"
                                    }
                                ]
                            }
                        },
                        "open_positions": {
                            "summary": "진행 중인 포지션",
                            "value": {
                                "status": "success",
                                "data": [
                                    {
                                        "timestamp": "2025-01-10 16:20:15",
                                        "symbol": "BTC-USDT-SWAP",
                                        "coin_name": "BTC",
                                        "entry_price": 92450.0,
                                        "exit_price": None,
                                        "size": 0.2,
                                        "pnl": None,
                                        "pnl_percent": None,
                                        "status": "open",
                                        "side": "long",
                                        "close_type": ""
                                    },
                                    {
                                        "timestamp": "2025-01-10 15:10:30",
                                        "symbol": "ETH-USDT-SWAP",
                                        "coin_name": "ETH",
                                        "entry_price": 3520.0,
                                        "exit_price": None,
                                        "size": 0.5,
                                        "pnl": None,
                                        "pnl_percent": None,
                                        "status": "open",
                                        "side": "short",
                                        "close_type": ""
                                    }
                                ]
                            }
                        },
                        "mixed_trades": {
                            "summary": "혼합 거래 내역 (진행중 + 완료)",
                            "value": {
                                "status": "success",
                                "data": [
                                    {
                                        "timestamp": "2025-01-10 16:20:15",
                                        "symbol": "BTC-USDT-SWAP",
                                        "coin_name": "BTC",
                                        "entry_price": 92450.0,
                                        "exit_price": None,
                                        "size": 0.2,
                                        "pnl": None,
                                        "pnl_percent": None,
                                        "status": "open",
                                        "side": "long",
                                        "close_type": ""
                                    },
                                    {
                                        "timestamp": "2025-01-10 14:30:25",
                                        "symbol": "BTC-USDT-SWAP",
                                        "coin_name": "BTC",
                                        "entry_price": 92000.0,
                                        "exit_price": 92500.0,
                                        "size": 0.1,
                                        "pnl": 50.0,
                                        "pnl_percent": 0.54,
                                        "status": "closed",
                                        "side": "long",
                                        "close_type": "tp"
                                    }
                                ]
                            }
                        },
                        "no_api_key": {
                            "summary": "API 키 미등록",
                            "value": {
                                "status": "no_api_key",
                                "message": "API 키가 등록되지 않았습니다. API 키를 먼저 등록해주세요.",
                                "data": []
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_limit": {
                            "summary": "잘못된 limit 값",
                            "value": {
                                "detail": "limit must be between 1 and 100"
                            }
                        },
                        "invalid_status": {
                            "summary": "잘못된 status 값",
                            "value": {
                                "detail": "status must be 'open' or 'closed'"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": "🔍 리소스를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자 없음",
                            "value": {
                                "detail": "User not found"
                            }
                        },
                        "no_trade_data": {
                            "summary": "거래 내역 없음",
                            "value": {
                                "detail": "No trade history found for this user"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "server_error": {
                            "summary": "서버 내부 오류",
                            "value": {
                                "detail": "거래 내역을 불러오는 데 실패했습니다."
                            }
                        },
                        "redis_error": {
                            "summary": "Redis 연결 오류",
                            "value": {
                                "detail": "Cache connection failed"
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": "🔧 서비스 이용 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_api_unavailable": {
                            "summary": "거래소 API 다운타임",
                            "value": {
                                "detail": "Exchange API is temporarily unavailable"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_user_trade_history(
    user_id: str = Query(..., description="사용자 ID"),
    limit: int = Query(10, description="조회할 거래 내역 수"),
    status: Optional[str] = Query(None, description="필터링할 거래 상태"),
    refresh: bool = Query(False, description="캐시를 무시하고 최신 데이터 조회")
) -> Dict[str, Any]:
    """
    사용자의 거래 내역을 조회합니다.

    Returns:
        Dict: 거래 내역 데이터
    """
    try:
        # 캐시 키 생성
        cache_key = f"stats:trade_history:{user_id}:{limit}:{status or 'all'}"
        
        # 최근 거래 확인을 위한 키
        history_key = f"user:{user_id}:history"
        current_latest_trade = await get_redis_client().lindex(history_key, 0)
        
        # 새로운 거래가 있는지 확인 (캐시 무효화 조건)
        if not refresh and user_id in last_trade_keys:
            if current_latest_trade == last_trade_keys[user_id]:
                cached_data = await cache.get(cache_key)
                if cached_data:
                    return cached_data
        
        # 새로운 거래 ID 업데이트
        if current_latest_trade:
            last_trade_keys[user_id] = current_latest_trade
        
        # 최신 데이터 조회
        trade_history = await get_trade_history(user_id, limit=limit, status=status)
        
        # 프론트엔드 요구 형식에 맞게 데이터 가공
        formatted_history = []
        for trade in trade_history:
            formatted_trade = {
                "timestamp": trade.get("timestamp", ""),
                "symbol": trade.get("symbol", ""),
                "coin_name": trade.get("symbol", "").split("-")[0] if "-" in trade.get("symbol", "") else "",
                "entry_price": float(trade.get("entry_price", 0)),
                "exit_price": float(trade.get("exit_price", 0)) if trade.get("exit_price") else None,
                "size": float(trade.get("size", 0)),
                "pnl": float(trade.get("pnl", 0)) if trade.get("pnl") else None,
                "pnl_percent": float(trade.get("pnl_percent", 0)) if trade.get("pnl_percent") else None,
                "status": trade.get("status", ""),
                "side": trade.get("side", ""),
                "close_type": trade.get("close_type", "")
            }
            formatted_history.append(formatted_trade)
        
        result = {
            "status": "success",
            "data": formatted_history
        }
        
        # 결과 캐싱 (거래 내역은 더 짧게 캐싱)
        await cache.set(cache_key, result, expire=CACHE_TTL["trade_history"])
        return result
    except HTTPException as e:
        # API 키가 없는 경우 적절한 에러 반환
        if e.status_code == 404 and "API keys not found" in str(e.detail):
            logger.info(f"사용자 {user_id}의 API 키가 등록되지 않음")
            return {
                "status": "no_api_key",
                "message": "API 키가 등록되지 않았습니다. API 키를 먼저 등록해주세요.",
                "data": []
            }
        raise e
    except Exception as e:
        logger.error(f"거래 내역 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="거래 내역을 불러오는 데 실패했습니다.")

# 통계 캐시 수동 무효화 API
@router.post("/clear-cache")
async def clear_stats_cache(user_id: str = Query(..., description="사용자 ID")) -> Dict[str, Any]:
    """
    특정 사용자의 모든 통계 관련 캐시를 무효화합니다.
    """
    try:
        # 사용자의 모든 통계 캐시 키 패턴
        cache_pattern = f"stats:*:{user_id}*"
        
        # Redis에서 패턴과 일치하는 모든 키 조회
        keys = await get_redis_client().keys(cache_pattern)
        
        # 모든 키 삭제
        if keys:
            pipeline = get_redis_client().pipeline()
            for key in keys:
                pipeline.delete(key)
            await pipeline.execute()
        
        return {
            "status": "success",
            "message": f"{len(keys)}개의 캐시가 삭제되었습니다.",
            "cleared_keys_count": len(keys)
        }
    except Exception as e:
        logger.error(f"캐시 삭제 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="캐시 삭제에 실패했습니다.") 