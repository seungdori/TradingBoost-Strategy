import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis
from fastapi import APIRouter, HTTPException, Query, Request, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from HYPERRSI.src.core.config import settings
from HYPERRSI.src.trading.models import get_timeframe

router = APIRouter(tags=["chart"])
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "src" / "static"))

# Redis 연결
if settings.REDIS_PASSWORD:
    redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0, decode_responses=True, password=settings.REDIS_PASSWORD)
else:
    redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0, decode_responses=True)

# 메모리 캐시 구현
_candle_cache: Dict[str, List[Dict[str, Any]]] = {}
_cache_timestamps: Dict[str, float] = {}
_last_candle_timestamps: Dict[str, int] = {}
CACHE_TTL = 60  # 캐시 유효 시간 (초)
DEFAULT_LIMIT = 100  # 기본 반환 캔들 개수

active_connections: dict[str, list] = {}

async def watch_redis_updates(symbol: str, timeframe: str) -> None:
    
    tf_str = get_timeframe(timeframe)
    while True:
        try:
            for websocket in active_connections.get(f"{symbol}:{tf_str}", []):
                latest_data = redis_client.get(f"latest:{symbol}:{tf_str}")
                if latest_data:
                    candle_data = json.loads(latest_data)
                    await websocket.send_json(candle_data)
                    
                    # 캐시 업데이트
                    cache_key = f"candles:{symbol}:{tf_str}"
                    if cache_key in _candle_cache:
                        update_cache_with_new_candle(cache_key, candle_data)
        except Exception as e:
            print(f"Error sending updates: {e}")
        await asyncio.sleep(1)


def normalize_okx_symbol(input: str) -> str:
    """
    입력된 심볼을 OKX 형식으로 변환합니다.
    예: BTCUSDT -> BTC-USDT-SWAP
    """
    if not input:
        return input
        
    # 이미 OKX 형식이면 그대로 반환
    if '-' in input:
        return input
        
    # USDT가 포함된 경우
    if 'USDT' in input.upper():
        base = input.upper().replace('USDT', '')
        return f"{base}-USDT-SWAP"
        
    return input

def update_cache_with_new_candle(cache_key: str, new_candle: Dict[str, Any]) -> None:
    """캐시에 새 캔들 데이터를 추가하고 오래된 캔들 제거"""
    if cache_key not in _candle_cache:
        return
    
    cache_data = _candle_cache[cache_key]
    
    # 이미 같은 timestamp의 캔들이 있는지 확인
    existing_idx = None
    for idx, candle in enumerate(cache_data):
        if candle.get('timestamp') == new_candle.get('timestamp'):
            existing_idx = idx
            break
            
    if existing_idx is not None:
        # 기존 캔들 업데이트
        cache_data[existing_idx] = new_candle
    else:
        # 새 캔들 추가 (맨 뒤에)
        cache_data.append(new_candle)
        
    # 캐시 타임스탬프 업데이트
    _cache_timestamps[cache_key] = time.time()
    _last_candle_timestamps[cache_key] = new_candle.get('timestamp', 0)


@router.get("/chart", response_class=HTMLResponse)
async def get_chart(request: Request):
    # 기본 심볼과 타임프레임을 템플릿에 전달
    return templates.TemplateResponse("index.html", {
        "request": request,
        "default_symbol": "BTC-USDT-SWAP",
        "default_timeframe": "5"
    })

@router.get(
    "/api/candles/{symbol}/{timeframe}",
    summary="캔들 데이터 조회 (OHLCV + 지표)",
    description="""
# 캔들 데이터 조회 (OHLCV + 지표)

특정 심볼과 타임프레임에 대한 캔들 데이터를 조회합니다. OHLCV(시가/고가/저가/종가/거래량)와 함께 계산된 기술적 지표(RSI, EMA, 볼린저 밴드 등)를 포함합니다.

## 경로 파라미터

- **symbol** (string, required): 거래 심볼
  - OKX 형식: "BTC-USDT-SWAP", "ETH-USDT-SWAP"
  - 자동 변환: "BTCUSDT" → "BTC-USDT-SWAP"
  - 예시: "BTC-USDT-SWAP", "ETHUSDT"
- **timeframe** (string, required): 시간 간격
  - 지원 형식: 1, 3, 5, 15, 30, 60, 120, 240, 1D
  - 자동 변환: "5m" → "5", "1h" → "60", "1d" → "1D"
  - 예시: "5", "15", "60", "1D"

## 쿼리 파라미터

- **limit** (integer, optional): 반환할 캔들 수
  - 기본값: 100
  - 범위: 1-1000
  - 예시: 200, 500
- **from_timestamp** (integer, optional): 시작 타임스탬프 (밀리초)
  - 이 시간 이후의 데이터만 조회
  - 예시: 1648656000000
- **to_timestamp** (integer, optional): 종료 타임스탬프 (밀리초)
  - 이 시간 이전의 데이터만 조회
  - 예시: 1648742400000

## 동작 방식

1. **심볼 정규화**: 입력된 심볼을 OKX 형식으로 변환
2. **타임프레임 변환**: get_timeframe()으로 표준 형식 변환
3. **캐시 확인**: 메모리 캐시에서 데이터 조회 (TTL: 60초)
4. **Redis 조회**: 캐시 미스 시 Redis에서 데이터 로드
   - 키: `candles_with_indicators:{symbol}:{timeframe}`
5. **데이터 파싱**: JSON 파싱 및 유효성 검증
6. **시간순 정렬**: 타임스탬프 기준 오름차순 정렬
7. **필터링**: from_timestamp, to_timestamp 범위 필터링
8. **최신순 선택**: limit 개수만큼 최신 데이터 선택
9. **캐시 업데이트**: 메모리 캐시 및 최신 타임스탬프 갱신
10. **메타데이터 생성**: 응답 메타정보 구성
11. **응답 반환**: 캔들 데이터 + 메타데이터

## 반환 데이터 구조

- **data** (array of objects): 캔들 데이터 배열 (오래된 → 최신 순)
  - **timestamp** (integer): 타임스탬프 (밀리초)
  - **open** (string): 시가 (USDT)
  - **high** (string): 고가 (USDT)
  - **low** (string): 저가 (USDT)
  - **close** (string): 종가 (USDT)
  - **volume** (string): 거래량
  - **rsi** (float, optional): RSI 지표 (0-100)
  - **ema_short** (float, optional): 단기 EMA
  - **ema_long** (float, optional): 장기 EMA
  - **bb_upper** (float, optional): 볼린저 밴드 상단
  - **bb_middle** (float, optional): 볼린저 밴드 중간
  - **bb_lower** (float, optional): 볼린저 밴드 하단
- **meta** (object): 메타데이터
  - **symbol** (string): 거래 심볼
  - **timeframe** (string): 시간 간격
  - **count** (integer): 반환된 캔들 수
  - **total_available** (integer): 전체 사용 가능한 캔들 수
  - **oldest_timestamp** (integer): 가장 오래된 캔들 시간
  - **newest_timestamp** (integer): 가장 최신 캔들 시간

## 캐시 전략

### 메모리 캐시
- **TTL**: 60초
- **키 형식**: `candles:{symbol}:{timeframe}`
- **갱신 조건**:
  - 캐시 만료
  - 새로운 캔들 감지 (타임스탬프 변경)
  - 첫 조회

### Redis 저장소
- **키 형식**: `candles_with_indicators:{symbol}:{timeframe}`
- **데이터 타입**: List (JSON 문자열)
- **업데이트**: 데이터 수집기가 실시간 업데이트

## 사용 시나리오

-  **차트 표시**: 실시간 가격 차트 렌더링
-  **기술적 분석**: RSI, EMA, 볼린저 밴드 등 지표 활용
-  **신호 생성**: 매매 신호 판단 및 전략 실행
-  **백테스팅**: 과거 데이터로 전략 검증
-  **패턴 인식**: 가격 패턴 및 추세 분석
-  **실시간 모니터링**: 시장 상황 실시간 추적

## WebSocket 지원

이 API는 WebSocket을 통한 실시간 업데이트를 지원합니다:
- **WebSocket 엔드포인트**: `ws://localhost:8000/ws/candles`
- **구독 형식**: `{{"action": "subscribe", "symbol": "BTC-USDT-SWAP", "timeframe": "5"}}`
- **업데이트 주기**: 새 캔들 생성 시 자동 전송
- **Redis Pub/Sub**: `latest:{symbol}:{timeframe}` 채널 사용

## 예시 URL

```
GET /api/candles/BTC-USDT-SWAP/5
GET /api/candles/ETHUSDT/15?limit=200
GET /api/candles/BTC-USDT-SWAP/1D?from_timestamp=1648656000000&to_timestamp=1648742400000
```

## 예시 curl 명령

```bash
# 최근 100개 5분봉 조회
curl -X GET "http://localhost:8000/api/candles/BTC-USDT-SWAP/5"

# 최근 200개 15분봉 조회
curl -X GET "http://localhost:8000/api/candles/BTC-USDT-SWAP/15?limit=200"

# 특정 기간 일봉 조회
curl -X GET "http://localhost:8000/api/candles/BTC-USDT-SWAP/1D?from_timestamp=1648656000000&to_timestamp=1648742400000"
```
""",
    response_description="캔들 데이터와 메타데이터를 포함한 JSON 응답",
    responses={
        200: {
            "description": " 캔들 데이터 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "btc_5min_with_indicators": {
                            "summary": "BTC 5분봉 (지표 포함)",
                            "value": {
                                "data": [
                                    {
                                        "timestamp": 1648656000000,
                                        "open": "45000.0",
                                        "high": "45100.0",
                                        "low": "44900.0",
                                        "close": "45050.0",
                                        "volume": "100.5",
                                        "rsi": 62.5,
                                        "ema_short": 45020.3,
                                        "ema_long": 44980.7,
                                        "bb_upper": 45200.0,
                                        "bb_middle": 45000.0,
                                        "bb_lower": 44800.0
                                    },
                                    {
                                        "timestamp": 1648656300000,
                                        "open": "45050.0",
                                        "high": "45200.0",
                                        "low": "45000.0",
                                        "close": "45150.0",
                                        "volume": "120.3",
                                        "rsi": 65.8,
                                        "ema_short": 45085.5,
                                        "ema_long": 45010.2,
                                        "bb_upper": 45300.0,
                                        "bb_middle": 45100.0,
                                        "bb_lower": 44900.0
                                    }
                                ],
                                "meta": {
                                    "symbol": "BTC-USDT-SWAP",
                                    "timeframe": "5",
                                    "count": 2,
                                    "total_available": 1000,
                                    "oldest_timestamp": 1648656000000,
                                    "newest_timestamp": 1648656300000
                                }
                            }
                        },
                        "eth_1hour": {
                            "summary": "ETH 1시간봉",
                            "value": {
                                "data": [
                                    {
                                        "timestamp": 1648652400000,
                                        "open": "3500.0",
                                        "high": "3550.0",
                                        "low": "3480.0",
                                        "close": "3520.0",
                                        "volume": "850.2",
                                        "rsi": 58.3,
                                        "ema_short": 3510.5,
                                        "ema_long": 3495.8
                                    }
                                ],
                                "meta": {
                                    "symbol": "ETH-USDT-SWAP",
                                    "timeframe": "60",
                                    "count": 1,
                                    "total_available": 720,
                                    "oldest_timestamp": 1648652400000,
                                    "newest_timestamp": 1648652400000
                                }
                            }
                        },
                        "btc_daily": {
                            "summary": "BTC 일봉",
                            "value": {
                                "data": [
                                    {
                                        "timestamp": 1648598400000,
                                        "open": "44500.0",
                                        "high": "45500.0",
                                        "low": "44200.0",
                                        "close": "45200.0",
                                        "volume": "12500.8",
                                        "rsi": 61.2,
                                        "ema_short": 44980.0,
                                        "ema_long": 44650.0
                                    }
                                ],
                                "meta": {
                                    "symbol": "BTC-USDT-SWAP",
                                    "timeframe": "1D",
                                    "count": 1,
                                    "total_available": 365,
                                    "oldest_timestamp": 1648598400000,
                                    "newest_timestamp": 1648598400000
                                }
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 데이터를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "no_data": {
                            "summary": "캔들 데이터 없음",
                            "value": {
                                "detail": "No data found for BTC-USDT-SWAP 5"
                            }
                        },
                        "invalid_symbol": {
                            "summary": "잘못된 심볼",
                            "value": {
                                "detail": "No data found for INVALID-SYMBOL 5"
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
                        "server_error": {
                            "summary": "서버 내부 오류",
                            "value": {
                                "detail": "Unexpected error: Internal server error"
                            }
                        },
                        "json_parse_error": {
                            "summary": "JSON 파싱 오류",
                            "value": {
                                "detail": "Unexpected error: Failed to parse candle data"
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": " 서비스 이용 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "redis_error": {
                            "summary": "Redis 연결 오류",
                            "value": {
                                "detail": "Redis connection error: Connection refused"
                            }
                        },
                        "redis_timeout": {
                            "summary": "Redis 타임아웃",
                            "value": {
                                "detail": "Redis connection error: Timeout"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_candle_data(
    symbol: str,
    timeframe: str,
    limit: Optional[int] = Query(DEFAULT_LIMIT, description="가져올 캔들 데이터 개수", ge=1, le=1000), 
    from_timestamp: Optional[int] = Query(None, description="이 시간 이후의 데이터만 가져옴 (밀리초 단위)"),
    to_timestamp: Optional[int] = Query(None, description="이 시간 이전의 데이터만 가져옴 (밀리초 단위)")
):
    
    symbol = normalize_okx_symbol(symbol)
    
    tf_str = get_timeframe(timeframe)
    cache_key = f"candles:{symbol}:{tf_str}"
    
    try:
        # 전체 데이터를 가져오거나 캐시에서 조회
        full_data = []
        
        # 캐시가 유효한지 확인
        cache_valid = (
            cache_key in _candle_cache and
            time.time() - _cache_timestamps.get(cache_key, 0) < CACHE_TTL
        )
        
        if cache_valid:
            full_data = _candle_cache[cache_key]
        else:
            # Redis에서 데이터 가져오기
            key = f"candles_with_indicators:{symbol}:{tf_str}"
            raw_data = redis_client.lrange(key, 0, -1)
            if not raw_data:
                raise HTTPException(status_code=404, detail=f"No data found for {symbol} {timeframe}")
            
            latest_timestamp = 0
            
            for item in raw_data:
                try:
                    candle = json.loads(item)
                    full_data.append(candle)
                    
                    # 가장 최신 타임스탬프 추적
                    timestamp = candle.get('timestamp', 0)
                    if timestamp > latest_timestamp:
                        latest_timestamp = timestamp
                        
                except (json.JSONDecodeError, KeyError) as e:
                    continue
            
            # 시간순 정렬 (오래된 -> 최신)
            full_data.sort(key=lambda x: x.get('timestamp', 0))
            
            # 캐시 업데이트
            _candle_cache[cache_key] = full_data
            _cache_timestamps[cache_key] = time.time()
            _last_candle_timestamps[cache_key] = latest_timestamp
        
        # 필터링 및 슬라이싱
        filtered_data = full_data.copy()
        
        # 시간 범위로 필터링
        if from_timestamp:
            filtered_data = [candle for candle in filtered_data if candle.get('timestamp', 0) >= from_timestamp]
        
        if to_timestamp:
            filtered_data = [candle for candle in filtered_data if candle.get('timestamp', 0) <= to_timestamp]
        
        # 최신 데이터를 우선적으로 반환하기 위해 정렬 및 슬라이싱
        filtered_data.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        result_data = filtered_data[:limit]
        
        # 다시 시간순 정렬해서 반환 (오래된 -> 최신)
        result_data.sort(key=lambda x: x.get('timestamp', 0))
        
        # 결과 메타데이터 추가
        response = {
            "data": result_data,
            "meta": {
                "symbol": symbol,
                "timeframe": timeframe,
                "count": len(result_data),
                "total_available": len(full_data),
                "oldest_timestamp": full_data[0].get('timestamp') if full_data else None,
                "newest_timestamp": full_data[-1].get('timestamp') if full_data else None
            }
        }
        
        return response

    except redis.RedisError as e:
        raise HTTPException(status_code=503, detail=f"Redis connection error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")