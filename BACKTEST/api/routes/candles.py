"""
캔들 데이터 관리 API

CandlesDB(PostgreSQL)와 Redis에 저장된 캔들 데이터의 지표를 재계산하는 API를 제공합니다.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Any

import psycopg2
from psycopg2.extras import execute_values
import pytz
import redis
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

from shared.indicators import compute_all_indicators, add_auto_trend_state_to_candles
from shared.logging import get_logger
from shared.config import get_settings
from HYPERRSI.src.trading.models import get_auto_trend_timeframe

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter()

# Redis 연결
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=0,
    password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
    decode_responses=True
)

# 타임프레임 맵
TF_MAP = {1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m", 60: "1h", 240: "4h"}
REVERSE_TF_MAP = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}

# 기본 심볼 및 타임프레임
DEFAULT_SYMBOLS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
DEFAULT_TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h"]
MAX_CANDLES = 1000


class RecalculateRequest(BaseModel):
    """캔들 재계산 요청 모델"""
    symbols: Optional[List[str]] = Field(
        default=None,
        description="재계산할 심볼 리스트 (기본값: BTC, ETH, SOL)"
    )
    timeframes: Optional[List[str]] = Field(
        default=None,
        description="재계산할 타임프레임 리스트 (기본값: 모든 타임프레임)"
    )
    max_candles: Optional[int] = Field(
        default=1000,
        description="재계산할 최대 캔들 수",
        ge=100,
        le=5000
    )
    source: Optional[str] = Field(
        default="candlesdb",
        description="데이터 소스: 'candlesdb' (PostgreSQL), 'redis', 'both'"
    )


class RecalculateResponse(BaseModel):
    """캔들 재계산 응답 모델"""
    success: bool
    message: str
    results: List[dict]
    total_processed: int
    total_success: int


# ============================================================
# CandlesDB Helper Functions
# ============================================================

def get_candlesdb_connection():
    """CandlesDB 연결 생성"""
    try:
        return psycopg2.connect(
            host=settings.CANDLES_HOST,
            port=settings.CANDLES_PORT,
            database=settings.CANDLES_DATABASE,
            user=settings.CANDLES_USER,
            password=settings.CANDLES_PASSWORD
        )
    except Exception as e:
        logger.error(f"CandlesDB 연결 실패: {e}")
        return None


def normalize_symbol_for_db(okx_symbol: str) -> str:
    """OKX 심볼을 DB 테이블명으로 변환 (BTC-USDT-SWAP -> btc_usdt)"""
    parts = okx_symbol.replace("-SWAP", "").split("-")
    return "_".join(parts).lower()


def get_candles_from_candlesdb(symbol: str, tf_str: str, limit: int = 1000) -> list:
    """CandlesDB에서 캔들 데이터 가져오기 (OHLCV만)"""
    conn = get_candlesdb_connection()
    if not conn:
        return []

    try:
        table_name = normalize_symbol_for_db(symbol)
        cur = conn.cursor()

        # OHLCV 데이터만 가져오기 (지표는 재계산할 것이므로)
        query = f"""
            SELECT time, open, high, low, close, volume
            FROM {table_name}
            WHERE timeframe = %s
            ORDER BY time DESC
            LIMIT %s;
        """
        cur.execute(query, (tf_str, limit + 200))  # warm-up을 위해 200개 추가
        rows = cur.fetchall()

        if not rows:
            logger.warning(f"CandlesDB에서 데이터 없음: {table_name} {tf_str}")
            return []

        candles = []
        for row in rows:
            ts = int(row[0].timestamp()) if hasattr(row[0], 'timestamp') else int(row[0])
            candles.append({
                "timestamp": ts,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5])
            })

        # 시간순 정렬 (오래된 -> 최신)
        candles.sort(key=lambda x: x["timestamp"])
        logger.info(f"CandlesDB에서 {len(candles)}개 캔들 로드: {table_name} {tf_str}")
        return candles

    except Exception as e:
        logger.error(f"CandlesDB 조회 실패: {e}")
        return []
    finally:
        conn.close()


def save_candles_to_candlesdb(symbol: str, tf_str: str, candles: list) -> bool:
    """재계산된 캔들을 CandlesDB에 저장"""
    conn = get_candlesdb_connection()
    if not conn:
        return False

    try:
        table_name = normalize_symbol_for_db(symbol)
        cur = conn.cursor()

        # Upsert query
        upsert_query = f"""
            INSERT INTO {table_name} (
                time, timeframe, open, high, low, close, volume,
                rsi14, atr, ema7, ma20, trend_state, auto_trend_state
            )
            VALUES %s
            ON CONFLICT (time, timeframe)
            DO UPDATE SET
                rsi14 = EXCLUDED.rsi14,
                atr = EXCLUDED.atr,
                ema7 = EXCLUDED.ema7,
                ma20 = EXCLUDED.ma20,
                trend_state = EXCLUDED.trend_state,
                auto_trend_state = EXCLUDED.auto_trend_state;
        """

        # Prepare rows
        rows = []
        for candle in candles:
            ts = candle["timestamp"]
            time_val = datetime.fromtimestamp(ts, tz=timezone.utc)

            row = (
                time_val,
                tf_str,
                Decimal(str(candle["open"])),
                Decimal(str(candle["high"])),
                Decimal(str(candle["low"])),
                Decimal(str(candle["close"])),
                Decimal(str(candle["volume"])),
                Decimal(str(candle.get("rsi", 0))) if candle.get("rsi") else None,
                Decimal(str(candle.get("atr14", 0))) if candle.get("atr14") else None,
                Decimal(str(candle.get("ema7", 0))) if candle.get("ema7") else None,
                Decimal(str(candle.get("sma20", 0))) if candle.get("sma20") else None,
                int(candle.get("trend_state", 0)) if candle.get("trend_state") is not None else None,
                int(candle.get("auto_trend_state", 0)) if candle.get("auto_trend_state") is not None else None,
            )
            rows.append(row)

        # Execute batch upsert
        execute_values(cur, upsert_query, rows)
        conn.commit()

        logger.info(f"CandlesDB 저장 완료: {table_name} {tf_str} - {len(rows)}개")
        return True

    except Exception as e:
        logger.error(f"CandlesDB 저장 실패: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        conn.close()


# ============================================================
# Redis Helper Functions
# ============================================================

def get_candles_from_redis(symbol: str, tf_str: str) -> list:
    """Redis에서 캔들 데이터 가져오기"""
    key = f"candles_with_indicators:{symbol}:{tf_str}"
    raw_data = redis_client.lrange(key, 0, -1)

    candles = []
    for item in raw_data:
        try:
            candle = json.loads(item)
            candles.append(candle)
        except json.JSONDecodeError:
            continue

    candles.sort(key=lambda x: x.get("timestamp", 0))
    return candles


def get_auto_trend_candles(symbol: str, auto_trend_tf_str: str) -> list:
    """auto_trend 계산용 캔들 가져오기 (Redis)"""
    key = f"candles_with_indicators:{symbol}:{auto_trend_tf_str}"
    raw_data = redis_client.lrange(key, 0, -1)

    candles = []
    for item in raw_data:
        try:
            candle = json.loads(item)
            candles.append(candle)
        except json.JSONDecodeError:
            continue

    candles.sort(key=lambda x: x.get("timestamp", 0))
    return candles


def save_candles_to_redis(symbol: str, tf_str: str, candles: list):
    """재계산된 캔들 Redis에 저장"""
    key = f"candles_with_indicators:{symbol}:{tf_str}"

    candles.sort(key=lambda x: x.get("timestamp", 0))

    if len(candles) > 3000:
        candles = candles[-3000:]

    pipe = redis_client.pipeline()
    pipe.delete(key)
    for candle in candles:
        pipe.rpush(key, json.dumps(candle))
    pipe.execute()


# ============================================================
# Recalculation Logic
# ============================================================

def recalculate_single(
    symbol: str,
    tf_str: str,
    max_candles: int = 1000,
    source: str = "candlesdb"
) -> dict:
    """단일 심볼/타임프레임 재계산"""
    result = {
        "symbol": symbol,
        "timeframe": tf_str,
        "success": False,
        "candle_count": 0,
        "source": source,
        "saved_to": [],
        "message": ""
    }

    try:
        # 1. 데이터 소스에서 캔들 가져오기
        if source == "candlesdb":
            base_candles = get_candles_from_candlesdb(symbol, tf_str, max_candles)
        elif source == "redis":
            raw_candles = get_candles_from_redis(symbol, tf_str)
            # OHLCV만 추출
            base_candles = []
            for c in raw_candles[-max_candles-200:]:
                base_candles.append({
                    "timestamp": c["timestamp"],
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "volume": c["volume"]
                })
        else:
            result["message"] = f"잘못된 소스: {source}"
            return result

        if not base_candles:
            result["message"] = "데이터 없음"
            return result

        logger.info(f"📊 재계산 시작: {symbol} {tf_str} - {len(base_candles)}개 캔들 (소스: {source})")

        # 2. 지표 재계산
        candles_with_ind = compute_all_indicators(base_candles, rsi_period=14, atr_period=14)

        # 3. auto_trend_state 재계산
        auto_trend_tf_str = get_auto_trend_timeframe(tf_str)
        auto_trend_candles = get_auto_trend_candles(symbol, auto_trend_tf_str)

        if auto_trend_candles and len(auto_trend_candles) >= 30:
            timeframe_minutes = REVERSE_TF_MAP.get(tf_str, 5)
            candles_with_ind = add_auto_trend_state_to_candles(
                candles_with_ind,
                auto_trend_candles,
                current_timeframe_minutes=timeframe_minutes
            )
            logger.info(f"  ✅ auto_trend_state 계산 완료 (auto_trend_tf: {auto_trend_tf_str})")
        else:
            for cndl in candles_with_ind:
                cndl["auto_trend_state"] = 0
            logger.warning(f"  ⚠️ auto_trend 캔들 부족, 0으로 설정")

        # 4. 한국 시간 추가
        seoul_tz = pytz.timezone("Asia/Seoul")
        for cndl in candles_with_ind:
            utc_dt = datetime.fromtimestamp(cndl["timestamp"], tz=timezone.utc)
            dt_seoul = utc_dt.astimezone(seoul_tz)
            cndl["human_time"] = utc_dt.strftime("%Y-%m-%d %H:%M:%S")
            cndl["human_time_kr"] = dt_seoul.strftime("%Y-%m-%d %H:%M:%S")

        # 5. CandlesDB에 저장
        if save_candles_to_candlesdb(symbol, tf_str, candles_with_ind):
            result["saved_to"].append("candlesdb")

        # 6. Redis에 저장
        save_candles_to_redis(symbol, tf_str, candles_with_ind)
        result["saved_to"].append("redis")

        result["success"] = True
        result["candle_count"] = len(candles_with_ind)
        result["message"] = f"재계산 완료 → {', '.join(result['saved_to'])}"

        logger.info(f"  ✅ 저장 완료: {symbol} {tf_str} - {len(candles_with_ind)}개 → {result['saved_to']}")

    except Exception as e:
        logger.error(f"재계산 실패: {symbol} {tf_str} - {e}", exc_info=True)
        result["message"] = str(e)

    return result


# ============================================================
# API Endpoints
# ============================================================

@router.post(
    "/recalculate",
    response_model=RecalculateResponse,
    summary="캔들 지표 재계산",
    description="""
CandlesDB(PostgreSQL)와 Redis에 저장된 캔들 데이터의 지표를 재계산합니다.

## 재계산 대상
- RSI, ATR, EMA, SMA 등 기술적 지표
- trend_state (CYCLE 기반 추세 상태)
- auto_trend_state (자동 트렌드 타임프레임)

## 데이터 소스
- **candlesdb** (기본값): PostgreSQL에서 OHLCV를 읽어서 지표 재계산
- **redis**: Redis에서 읽어서 재계산
- **both**: 두 소스 모두에서 재계산

## 저장 위치
- 재계산된 데이터는 **CandlesDB와 Redis 모두에 저장**됩니다.

## 기본 동작
- 심볼 미지정 시: BTC, ETH, SOL
- 타임프레임 미지정 시: 1m, 3m, 5m, 15m, 30m, 1h, 4h
- 최대 캔들 수: 1000개 (기본값)

## 주의사항
- 상위 타임프레임부터 순서대로 처리됨 (auto_trend 의존성)
- 대량 재계산 시 시간이 소요될 수 있음
"""
)
async def recalculate_candles(request: RecalculateRequest):
    """캔들 데이터 지표 재계산"""

    symbols = request.symbols or DEFAULT_SYMBOLS
    timeframes = request.timeframes or DEFAULT_TIMEFRAMES
    max_candles = request.max_candles or MAX_CANDLES
    source = request.source or "candlesdb"

    # 유효성 검사
    invalid_tfs = [tf for tf in timeframes if tf not in REVERSE_TF_MAP]
    if invalid_tfs:
        raise HTTPException(
            status_code=400,
            detail=f"잘못된 타임프레임: {invalid_tfs}. 지원: {list(REVERSE_TF_MAP.keys())}"
        )

    if source not in ["candlesdb", "redis", "both"]:
        raise HTTPException(
            status_code=400,
            detail=f"잘못된 소스: {source}. 지원: candlesdb, redis, both"
        )

    logger.info(f"🔄 캔들 재계산 시작: {symbols} x {timeframes} (소스: {source})")

    # 상위 타임프레임부터 처리 (auto_trend 의존성)
    ordered_timeframes = sorted(
        timeframes,
        key=lambda x: REVERSE_TF_MAP.get(x, 0),
        reverse=True
    )

    results = []

    for symbol in symbols:
        for tf_str in ordered_timeframes:
            result = recalculate_single(symbol, tf_str, max_candles, source)
            results.append(result)

    success_count = sum(1 for r in results if r["success"])

    return RecalculateResponse(
        success=success_count > 0,
        message=f"{len(symbols)}개 심볼, {len(timeframes)}개 타임프레임 재계산 완료 (소스: {source})",
        results=results,
        total_processed=len(results),
        total_success=success_count
    )


@router.post(
    "/recalculate/quick",
    summary="빠른 재계산 (BTC, ETH, SOL)",
    description="CandlesDB에서 BTC, ETH, SOL의 모든 타임프레임을 재계산하고 CandlesDB + Redis에 저장합니다."
)
async def quick_recalculate(
    max_candles: int = Query(default=1000, ge=100, le=3000, description="최대 캔들 수"),
    source: str = Query(default="candlesdb", description="데이터 소스: candlesdb, redis")
):
    """빠른 재계산 (기본 심볼)"""
    request = RecalculateRequest(
        symbols=DEFAULT_SYMBOLS,
        timeframes=DEFAULT_TIMEFRAMES,
        max_candles=max_candles,
        source=source
    )
    return await recalculate_candles(request)


@router.get(
    "/symbols",
    summary="사용 가능한 심볼 목록",
    description="Redis에 저장된 캔들 데이터가 있는 심볼 목록을 반환합니다."
)
async def get_available_symbols():
    """사용 가능한 심볼 목록 조회"""
    try:
        keys = redis_client.keys("candles_with_indicators:*")

        symbols = set()
        for key in keys:
            parts = key.split(":")
            if len(parts) >= 2:
                symbols.add(parts[1])

        return {
            "symbols": sorted(list(symbols)),
            "count": len(symbols)
        }
    except Exception as e:
        logger.error(f"심볼 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/info/{symbol}",
    summary="심볼별 캔들 정보",
    description="특정 심볼의 타임프레임별 캔들 데이터 정보를 반환합니다."
)
async def get_symbol_info(symbol: str):
    """심볼별 캔들 정보 조회"""
    try:
        info = {"redis": {}, "candlesdb": {}}

        # Redis 정보
        for tf_str in DEFAULT_TIMEFRAMES:
            key = f"candles_with_indicators:{symbol}:{tf_str}"
            count = redis_client.llen(key)

            if count > 0:
                latest_raw = redis_client.lindex(key, -1)
                oldest_raw = redis_client.lindex(key, 0)

                latest = json.loads(latest_raw) if latest_raw else None
                oldest = json.loads(oldest_raw) if oldest_raw else None

                info["redis"][tf_str] = {
                    "count": count,
                    "oldest_time": oldest.get("human_time_kr") if oldest else None,
                    "latest_time": latest.get("human_time_kr") if latest else None,
                    "latest_close": latest.get("close") if latest else None,
                    "latest_trend_state": latest.get("trend_state") if latest else None,
                    "latest_auto_trend_state": latest.get("auto_trend_state") if latest else None
                }

        # CandlesDB 정보
        conn = get_candlesdb_connection()
        if conn:
            try:
                table_name = normalize_symbol_for_db(symbol)
                cur = conn.cursor()

                for tf_str in DEFAULT_TIMEFRAMES:
                    query = f"""
                        SELECT
                            COUNT(*) as count,
                            MIN(time) as oldest,
                            MAX(time) as latest
                        FROM {table_name}
                        WHERE timeframe = %s;
                    """
                    cur.execute(query, (tf_str,))
                    row = cur.fetchone()

                    if row and row[0] > 0:
                        info["candlesdb"][tf_str] = {
                            "count": row[0],
                            "oldest_time": row[1].strftime("%Y-%m-%d %H:%M:%S") if row[1] else None,
                            "latest_time": row[2].strftime("%Y-%m-%d %H:%M:%S") if row[2] else None
                        }

                cur.close()
            except Exception as e:
                logger.warning(f"CandlesDB 정보 조회 실패: {e}")
            finally:
                conn.close()

        if not info["redis"] and not info["candlesdb"]:
            raise HTTPException(
                status_code=404,
                detail=f"심볼 {symbol}의 캔들 데이터가 없습니다."
            )

        return {
            "symbol": symbol,
            "data": info
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"심볼 정보 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/candlesdb/tables",
    summary="CandlesDB 테이블 목록",
    description="CandlesDB에 존재하는 캔들 테이블 목록을 반환합니다."
)
async def get_candlesdb_tables():
    """CandlesDB 테이블 목록 조회"""
    conn = get_candlesdb_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="CandlesDB 연결 실패")

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        tables = [row[0] for row in cur.fetchall()]

        return {
            "tables": tables,
            "count": len(tables)
        }
    except Exception as e:
        logger.error(f"테이블 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
