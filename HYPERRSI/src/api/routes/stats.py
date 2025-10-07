from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import json

from shared.logging import get_logger
from HYPERRSI.src.trading.stats import (
    get_user_trading_statistics,
    get_pnl_history,
    get_trading_stats,
    get_trade_history
)
from HYPERRSI.src.api.routes.account import get_balance
from HYPERRSI.src.core.database import Cache  # 캐시 모듈 추가
import time
logger = get_logger(__name__)

# Dynamic redis_client access
def _get_redis_client():
    """Get redis_client dynamically to avoid import-time errors"""
    from HYPERRSI.src.core import database as db_module
    return db_module.redis_client

redis_client = _get_redis_client()

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

@router.get("/summary")
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

@router.get("/trade-amount")
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

@router.get("/profit-amount")
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

@router.get("/trade-history")
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
        current_latest_trade = await redis_client.lindex(history_key, 0)
        
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
        keys = await redis_client.keys(cache_pattern)
        
        # 모든 키 삭제
        if keys:
            pipeline = redis_client.pipeline()
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