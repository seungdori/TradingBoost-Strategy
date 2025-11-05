# HYPERRSI/src/trading/modules/market_data_service.py
"""
Market Data Service

시장 데이터 조회 및 인디케이터 관련 기능
"""

import json
import traceback
from typing import Optional

import httpx
import pandas as pd

from HYPERRSI.src.trading.models import get_timeframe
from HYPERRSI.src.trading.services.get_current_price import get_current_price
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger
from shared.utils import safe_float
from shared.config import get_settings

logger = get_logger(__name__)

# Get settings instance for API URL
_settings = get_settings()

# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
    raise AttributeError(f"module has no attribute {name}")


class MarketDataService:
    """시장 데이터 조회 및 인디케이터 서비스"""

    def __init__(self, trading_service):
        """
        Args:
            trading_service: TradingService 인스턴스 (client 등에 접근하기 위함)
        """
        self.trading_service = trading_service

    async def get_atr_value(self, symbol: str, timeframe: str = "1m", current_price: float = None) -> float:
        """
        주어진 심볼에 대한 ATR 값을 조회
        - 캐시된 ATR 값이 있는 경우 캐시에서 가져오고, 없는 경우 OKX API로 조회
        - 조회된 ATR 값을 반환
        """
        try:
            redis = await get_redis_client()
            tf_str = get_timeframe(timeframe)
            candle_key = f"candles_with_indicators:{symbol}:{tf_str}"
            candle_data = await redis.lindex(candle_key, -1)
            if candle_data:
                candle_json = json.loads(candle_data)
                atr_value = float(candle_json.get('atr14', 0.0))
                if atr_value is None or atr_value <= current_price * 0.001:
                    atr_value = current_price * 0.001
                return atr_value if atr_value > 0 else 0.0
            else:
                return 0.0
        except Exception as e:
            logger.error(f"Failed to get ATR value for {symbol}: {str(e)}")
            return 0.0

    async def get_historical_prices(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """Redis에서 과거 데이터(캔들+인디케이터) 가져오기"""
        try:
            redis = await get_redis_client()
            tf_str = get_timeframe(timeframe)
            candles_key = f"candles_with_indicators:{symbol}:{tf_str}"
            cached_data = await redis.lrange(candles_key, -limit, -1)
            if cached_data:
                df = pd.DataFrame([
                    {
                        'timestamp': pd.to_datetime(json.loads(item)['timestamp'], unit='s'),
                        'open': float(json.loads(item)['open']),
                        'high': float(json.loads(item)['high']),
                        'low': float(json.loads(item)['low']),
                        'close': float(json.loads(item)['close']),
                        'volume': float(json.loads(item)['volume'])
                    }
                    for item in cached_data
                ])
                if not df.empty:
                    df.set_index('timestamp', inplace=True)
                    df.sort_index(inplace=True)
                return df
            else:
                # 없으면 OKX API로 추가 조회 (생략)
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"과거 가격 데이터 조회 실패: {str(e)}")
            print(traceback.format_exc())
            return pd.DataFrame()

    async def check_rsi_signals(self, rsi_values: list, rsi_settings: dict) -> dict:
        """RSI 신호 확인 로직"""
        try:
            # RSI 값 유효성 검사
            if not rsi_values or len(rsi_values) < 2:
                logger.warning("충분한 RSI 데이터가 없습니다.")
                return {
                    'rsi': None,
                    'is_oversold': False,
                    'is_overbought': False
                }

            # 현재 RSI와 이전 RSI 값
            current_rsi = rsi_values[-1]
            previous_rsi = rsi_values[-2]

            # 진입 옵션에 따른 처리
            entry_option = rsi_settings.get('entry_option', '')
            rsi_oversold = rsi_settings['rsi_oversold']
            rsi_overbought = rsi_settings['rsi_overbought']

            # 디버깅: RSI 설정 로그
            logger.info(f"🔍 RSI 신호 체크:")
            logger.info(f"  - entry_option: '{entry_option}'")
            logger.info(f"  - rsi_oversold: {rsi_oversold}")
            logger.info(f"  - rsi_overbought: {rsi_overbought}")
            logger.info(f"  - previous_rsi: {previous_rsi:.3f}")
            logger.info(f"  - current_rsi: {current_rsi:.3f}")

            is_oversold = False
            is_overbought = False

            if entry_option == '돌파':
                # 롱: crossunder the rsi_oversold
                is_oversold = previous_rsi > rsi_oversold and current_rsi <= rsi_oversold

                # 숏: crossunder the rsi_overbought
                is_overbought = previous_rsi < rsi_overbought and current_rsi >= rsi_overbought
            elif entry_option == '변곡':
                # 롱: oversold 영역에서 RSI 상승 시작 (방향 전환)
                is_oversold = ((previous_rsi < rsi_oversold) or (current_rsi < rsi_oversold)) and current_rsi > previous_rsi

                # 숏: overbought 영역에서 RSI 하락 시작 (방향 전환)
                is_overbought = ((previous_rsi > rsi_overbought) or (current_rsi > rsi_overbought)) and current_rsi < previous_rsi

            elif entry_option == '변곡돌파':
                # 롱: oversold 위로 crossover (oversold 돌파)
                is_oversold = current_rsi >= rsi_oversold and previous_rsi < rsi_oversold

                # 숏: overbought 아래로 crossunder (overbought 돌파)
                is_overbought = current_rsi <= rsi_overbought and previous_rsi > rsi_overbought

            elif entry_option == '초과':
                # 롱: current_rsi < rsi_oversold
                is_oversold = current_rsi < rsi_oversold
                # 숏: current_rsi > rsi_overbought
                is_overbought = current_rsi > rsi_overbought

            else:
                # 기본 동작 (기존 코드와 동일)
                is_oversold = current_rsi < rsi_oversold
                is_overbought = current_rsi > rsi_overbought

            # 디버깅: 결과 로그
            logger.info(f"🎯 RSI 신호 결과:")
            logger.info(f"  - is_oversold: {is_oversold}")
            logger.info(f"  - is_overbought: {is_overbought}")
            if entry_option == '돌파':
                logger.info(f"  - '돌파' 조건:")
                logger.info(f"    롱(oversold): prev({previous_rsi:.3f}) > {rsi_oversold} and curr({current_rsi:.3f}) <= {rsi_oversold}")
                logger.info(f"    숏(overbought): prev({previous_rsi:.3f}) < {rsi_overbought} and curr({current_rsi:.3f}) >= {rsi_overbought}")
            elif entry_option == '변곡돌파':
                logger.info(f"  - '변곡돌파' 조건:")
                logger.info(f"    롱(oversold): curr({current_rsi:.3f}) < {rsi_oversold} and prev({previous_rsi:.3f}) >= {rsi_oversold}")
                logger.info(f"    숏(overbought): curr({current_rsi:.3f}) > {rsi_overbought} and prev({previous_rsi:.3f}) <= {rsi_overbought}")

            return {
                'rsi': current_rsi,
                'is_oversold': is_oversold,
                'is_overbought': is_overbought
            }
        except Exception as e:
            logger.error(f"RSI 신호 확인 중 오류 발생: {str(e)}", exc_info=True)
            return {
                'rsi': None,
                'is_oversold': False,
                'is_overbought': False
            }

    async def get_contract_info(
        self,
        symbol: str,
        user_id: str = None,
        size_usdt: float = None,
        leverage: float = None,
        current_price: Optional[float] = None
    ) -> dict:
        """
        주어진 심볼의 계약 정보를 조회하고 계약 수량을 계산합니다.

        Args:
            user_id: 사용자 ID
            symbol: 거래 심볼 (예: "BTC-USDT-SWAP")
            size_usdt: 주문 금액
            leverage: 레버리지
            current_price: 현재가 (None이면 자동으로 조회)

        Returns:
            dict: {
                "symbol": str,
                "contractSize": float,  # 계약 단위
                "contracts_amount": float,      # 계산된 계약 수량
                "minSize": float,       # 최소 주문 수량
                "tickSize": float,      # 틱 크기
                "current_price": float   # 사용된 현재가
            }
        """
        try:
            redis = await get_redis_client()
            # 1. 계약 사양 정보 조회
            specs_json = await redis.get("symbol_info:contract_specifications")
            if not specs_json:
                if not user_id:
                    print("user_id가 없어서 계약사항 새로운 정보를 조회하지 않습니다.")
                    return None
                logger.info(f"계약 사양 정보가 없어 새로 조회합니다: {symbol}")
                async with httpx.AsyncClient() as client:
                    # Use dynamic API URL from settings
                    api_url = f"{_settings.hyperrsi_api_url}/account/contract-specs"
                    response = await client.get(
                        api_url,
                        params={
                            "user_id": str(user_id),
                            "force_update": True
                        }
                    )
                    if response.status_code != 200:
                        raise ValueError("계약 사양 정보 조회 실패")

                    specs_json = await redis.get(f"symbol_info:contract_specifications")
                    if not specs_json:
                        raise ValueError(f"계약 사양 정보를 찾을 수 없습니다: {symbol}")

            # 2. 계약 정보 파싱
            specs_dict = json.loads(specs_json)
            contract_info = specs_dict.get(symbol)
            if not contract_info:
                raise ValueError(f"해당 심볼의 계약 정보가 없습니다: {symbol}")

            # 3. 현재가 조회 (필요시)
            if current_price is None:
                current_price = await self.get_current_price(symbol)

            # 4. 계약 수량 계산

            contract_size = contract_info.get('contractSize', 0)
            if contract_size <= 0:
                raise ValueError(f"유효하지 않은 계약 크기: {contract_size}")

            if leverage is None or leverage <= 0:
                leverage = 1
            contracts_amount = 0.0
            tick_size = contract_info.get('tickSize', 0.001)
            min_size = contract_info.get('minSize', 1)
            if size_usdt is None or size_usdt <= 0:
                contracts_amount = 0
            else:
                contract_size = float(contract_size)
                size_usdt = float(size_usdt)

                contracts_amount = (size_usdt * leverage) / (contract_size * current_price)
                contracts_amount = max(min_size, safe_float(contracts_amount))
                # minSize 단위로 내림 처리 (이중 반올림 방지)
                contracts_amount = (contracts_amount // min_size) * min_size
                # 소수점 정밀도 유지 (최대 8자리)
                contracts_amount = round(contracts_amount, 8)

            return {
                "symbol": symbol,
                "contractSize": contract_size,
                "contracts_amount": contracts_amount,
                "minSize": min_size,
                "tickSize": tick_size,
                "current_price": current_price,
            }

        except Exception as e:
            logger.error(f"계약 정보 조회 실패: {str(e)}")
            raise ValueError(f"계약 정보 조회 실패: {str(e)}")

    async def get_current_price(self, symbol: str, timeframe: str = "1m") -> float:
        """현재가 조회"""
        exchange = self.trading_service.client
        return await get_current_price(symbol, timeframe, exchange)
