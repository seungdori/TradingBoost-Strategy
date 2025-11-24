#src/trading/services/order_wrapper.py
from typing import Dict, List, Optional

import ccxt.async_support as ccxt

from shared.logging import get_logger

logger = get_logger(__name__)

class OrderWrapper:
    """ORDER_BACKEND를 통한 주문 처리 통합 래퍼"""

    # 사용자별 Exchange 객체 캐시 (싱글톤 패턴)
    _exchange_cache: Dict[str, ccxt.okx] = {}

    def __init__(self, user_id: str, api_keys: Dict[str, str]):
        self.user_id = user_id
        self.api_keys = api_keys

        # 캐시된 Exchange 객체가 있으면 재사용
        if user_id in OrderWrapper._exchange_cache:
            self.exchange = OrderWrapper._exchange_cache[user_id]
            logger.debug(f"[OrderWrapper] Reusing cached exchange for user {user_id}")
        else:
            # 새로운 Exchange 객체 생성 및 캐싱
            self.exchange = ccxt.okx({
                'apiKey': api_keys.get('api_key'),
                'secret': api_keys.get('api_secret'),
                'password': api_keys.get('passphrase'),
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'swap',
                    # SPOT 마켓 로딩 오류 무시 설정
                    'warnOnFetchMarketsTimeout': False,
                }
            })
            OrderWrapper._exchange_cache[user_id] = self.exchange
            logger.info(f"[OrderWrapper] Created and cached new exchange for user {user_id}")
    
    
    async def close(self):
        """리소스 정리 (캐시된 객체는 유지)"""
        # 캐시된 Exchange 객체는 유지 (재사용을 위해)
        # 명시적으로 캐시를 제거하려면 clear_cache() 호출
        logger.debug(f"[OrderWrapper] close() called for user {self.user_id} (cache maintained)")

    @classmethod
    async def clear_cache(cls, user_id: Optional[str] = None):
        """Exchange 캐시 제거 (API 키 변경 시 사용)"""
        if user_id:
            # 특정 사용자 캐시만 제거
            if user_id in cls._exchange_cache:
                exchange = cls._exchange_cache.pop(user_id)
                await exchange.close()
                logger.info(f"[OrderWrapper] Cleared cache for user {user_id}")
        else:
            # 모든 캐시 제거
            for user_id, exchange in cls._exchange_cache.items():
                await exchange.close()
            cls._exchange_cache.clear()
            logger.info(f"[OrderWrapper] Cleared all exchange cache")
    
    async def create_order(self, symbol: str, order_type: str, side: str, amount: float,
                          price: Optional[float] = None, params: Optional[Dict] = None) -> Dict:
        """주문 생성"""
        # CCXT create_order signature: (symbol, type, side, amount, price, params)
        result: Dict = await self.exchange.create_order(
            symbol=symbol,
            type=order_type,
            side=side,
            amount=amount,
            price=price,
            params=params
        )
        return result

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None, params: Optional[Dict] = None) -> Dict:
        """주문 취소"""
        result: Dict = await self.exchange.cancel_order(order_id, symbol, params)
        return result

    async def fetch_order(self, order_id: str, symbol: str, params: Optional[Dict] = None) -> Dict:
        """주문 조회"""
        result: Dict = await self.exchange.fetch_order(order_id, symbol, params)
        return result

    async def fetch_positions(self, symbols: Optional[List[str]] = None, params: Optional[Dict] = None) -> List[Dict]:
        """포지션 조회"""
        result: List[Dict] = await self.exchange.fetch_positions(symbols, params)
        return result

    async def fetch_open_orders(self, symbol: Optional[str] = None, since: Optional[int] = None,
                               limit: Optional[int] = None, params: Optional[Dict] = None) -> List[Dict]:
        """미체결 주문 조회"""
        result: List[Dict] = await self.exchange.fetch_open_orders(symbol, since, limit, params)
        return result
    
    async def cancel_all_orders_for_symbol(self, symbol: str, side: Optional[str] = None) -> Dict:
        """특정 심볼의 모든 주문 취소"""
        # 로컬에서 처리
        open_orders = await self.exchange.fetch_open_orders(symbol)
        if side:
            open_orders = [o for o in open_orders if o['side'] == side]
        
        results = []
        for order in open_orders:
            try:
                result = await self.exchange.cancel_order(order['id'], symbol)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to cancel order {order['id']}: {e}")
        
        return {
            "success": True,
            "cancelled_count": len(results),
            "cancelled_orders": results
        }
    
    async def fetch_balance(self, params: Optional[Dict] = None) -> Dict:
        """잔고 조회"""
        result: Dict = await self.exchange.fetch_balance(params)
        return result

    async def fetch_ticker(self, symbol: str, params: Optional[Dict] = None) -> Dict:
        """현재가 조회"""
        result: Dict = await self.exchange.fetch_ticker(symbol, params)
        return result

    async def fetch_trades(self, symbol: str, since: Optional[int] = None,
                          limit: Optional[int] = None, params: Optional[Dict] = None) -> List[Dict]:
        """거래 내역 조회"""
        result: List[Dict] = await self.exchange.fetch_trades(symbol, since, limit, params)
        return result

    async def set_leverage(self, leverage: int, symbol: str, params: Optional[Dict] = None) -> Dict:
        """레버리지 설정"""
        result: Dict = await self.exchange.set_leverage(leverage, symbol, params)
        return result

    # Private API methods - 모두 로컬 exchange 사용
    async def private_get_account_positions(self, params: Optional[Dict] = None) -> Dict:
        """계정 포지션 조회 (private API)"""
        result: Dict = await self.exchange.private_get_account_positions(params)
        return result

    async def private_post_account_set_leverage(self, params: Dict) -> Dict:
        """레버리지 설정 (private API)"""
        result: Dict = await self.exchange.private_post_account_set_leverage(params)
        return result

    async def privateGetTradeOrdersAlgoPending(self, params: Optional[Dict] = None) -> Dict:
        """활성 알고리즘 주문 조회 (private API)"""
        result: Dict = await self.exchange.private_get_trade_orders_algo_pending(params)
        return result

    async def privateGetTradeOrdersAlgoHistory(self, params: Optional[Dict] = None) -> Dict:
        """알고리즘 주문 히스토리 조회 (private API)"""
        result: Dict = await self.exchange.private_get_trade_orders_algo_history(params)
        return result

    async def private_post_trade_cancel_algos(self, params: Dict) -> Dict:
        """알고리즘 주문 취소 (private API)"""
        result: Dict = await self.exchange.private_post_trade_cancel_algos(params)
        return result

    # Utility methods to mimic ccxt behavior
    def get_market(self, symbol: str) -> Dict:
        """시장 정보 가져오기"""
        if hasattr(self.exchange, 'markets'):
            result: Dict = self.exchange.markets.get(symbol, {})
            return result
        return {}

    @property
    def has(self) -> Dict:
        """지원 기능 확인"""
        return self.exchange.has if hasattr(self.exchange, 'has') else {
            'CORS': None,
            'spot': True,
            'margin': False,
            'swap': True,
            'future': True,
            'option': False,
            'createOrder': True,
            'createMarketOrder': True,
            'createLimitOrder': True,
            'createStopOrder': True,
            'createStopLimitOrder': True,
            'createStopMarketOrder': True,
            'cancelOrder': True,
            'cancelAllOrders': True,
            'fetchOrder': True,
            'fetchOrders': True,
            'fetchOpenOrders': True,
            'fetchClosedOrders': True,
            'fetchMyTrades': True,
            'fetchOrderTrades': True,
            'fetchPositions': True,
            'fetchBalance': True,
            'fetchTicker': True,
            'fetchTickers': True,
            'fetchBidsAsks': True,
            'fetchTrades': True,
            'fetchOHLCV': True,
            'fetchDepositAddress': True,
            'createDepositAddress': True,
            'withdraw': True,
        }