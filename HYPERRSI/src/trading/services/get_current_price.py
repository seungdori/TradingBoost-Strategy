
import json

import ccxt.async_support as ccxt

from HYPERRSI.src.trading.models import get_timeframe
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger
from shared.utils import safe_float

logger = get_logger(__name__)


# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")


async def get_current_price(symbol: str, timeframe: str = "1m", exchange: ccxt.Exchange = None) -> float:
    """
        Redis latest 키에서 현재가 조회
        
        Args:
            symbol: 거래 심볼 (예: "SOL-USDT-SWAP")
            timeframe: 시간단위 (기본값 "1m")
            
        Returns:
            float: 현재가
        
        Raises:
            ValueError: 유효하지 않은 시간단위나 현재가일 경우
        """
    try:
        redis = await get_redis_client()
        # 시간단위 매핑 확
        # 
        #print(f"timeframe: {timeframe}")
        tf_str = get_timeframe(timeframe)
        #print(f"tf: {tf}")
        if not tf_str:
            raise ValueError(f"지원하지 않는 시간단위입니다: {timeframe}")
        
        # Redis에서 latest 데이터 조회
        latest_key = f"latest:{symbol}:{tf_str}"
        latest_data = await redis.get(latest_key)
        
        if not latest_data:
            logger.warning(f"Redis에서 현재가를 찾을 수 없습니다: {latest_key}")
            # Redis에 데이터가 없으면 OKX API로 대체
            ticker = await exchange.fetch_ticker(symbol)
            return float(ticker['last'])

        candle_data = json.loads(latest_data)
        current_price = safe_float(candle_data.get('close', 0))

        if current_price <= 0:
            raise ValueError(f"유효하지 않은 현재가: {current_price}")
            
        return current_price

    except Exception as e:
        logger.error(f"현재가 조회 실패: {str(e)}")
        # 에러 발생 시 OKX API로 폴백
        if exchange:
            ticker = await exchange.fetch_ticker(symbol)
            return float(ticker['last'])

    
