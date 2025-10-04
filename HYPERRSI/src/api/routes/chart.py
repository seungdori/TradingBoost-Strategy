from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import redis
import json
from datetime import datetime
from fastapi import WebSocket
from HYPERRSI.src.trading.models import get_timeframe
import asyncio
from HYPERRSI.src.core.config import settings
from pathlib import Path
import time
from typing import Dict, Any, List, Optional

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

active_connections = {}

async def watch_redis_updates(symbol: str, timeframe: str):
    
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

def update_cache_with_new_candle(cache_key: str, new_candle: Dict[str, Any]):
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

@router.get("/api/candles/{symbol}/{timeframe}", 
    summary="캔들 데이터 조회",
    description="""
    특정 심볼과 타임프레임에 대한 캔들 데이터를 조회합니다.
    
    - **symbol**: 거래 심볼 (예: BTC-USDT-SWAP)
    - **timeframe**: 시간 간격 (예: 1, 5, 15, 30, 60, 240, 1D)
    - **limit**: 반환할 캔들 데이터의 최대 개수 (기본값: 100)
    - **from_timestamp**: 특정 시간 이후의 데이터만 조회 (선택사항)
    - **to_timestamp**: 특정 시간 이전의 데이터만 조회 (선택사항)
    
    응답은 시간순으로 정렬된 캔들 데이터와 메타데이터를 포함합니다.
    """,
    response_description="캔들 데이터와 메타데이터를 포함한 JSON 응답",
    responses={
        200: {
            "description": "성공적으로 캔들 데이터를 조회함",
            "content": {
                "application/json": {
                    "example": {
                        "data": [
                            {
                                "timestamp": 1648656000000,
                                "open": "45000.0",
                                "high": "45100.0",
                                "low": "44900.0",
                                "close": "45050.0",
                                "volume": "100.5"
                            }
                        ],
                        "meta": {
                            "symbol": "BTC-USDT-SWAP",
                            "timeframe": "5",
                            "count": 1,
                            "total_available": 1000,
                            "oldest_timestamp": 1648656000000,
                            "newest_timestamp": 1648656000000
                        }
                    }
                }
            }
        },
        404: {
            "description": "요청한 심볼과 타임프레임에 대한 데이터를 찾을 수 없음"
        },
        503: {
            "description": "Redis 연결 오류"
        },
        500: {
            "description": "서버 내부 오류"
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