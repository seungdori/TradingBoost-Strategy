#src/trading/services/order_wrapper.py
from typing import Dict, Optional, List
from shared.logging import get_logger
import ccxt.async_support as ccxt

logger = get_logger(__name__)

class OrderWrapper:
    """ORDER_BACKEND를 통한 주문 처리 통합 래퍼"""
    
    def __init__(self, user_id: str, api_keys: Dict[str, str]):
        self.user_id = user_id
        self.api_keys = api_keys
        
        # ORDER_BACKEND는 항상 자기 자신을 가리키므로 사용하지 않음
        # 항상 로컬 exchange 사용
        
        logger.info("Using local exchange client for orders")
        self.exchange = ccxt.okx({
            'apiKey': api_keys.get('api_key'),
            'secret': api_keys.get('api_secret'),
            'password': api_keys.get('passphrase'),
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
    
    
    async def close(self):
        """리소스 정리"""
        if hasattr(self, 'exchange'):
            await self.exchange.close()
    
    async def create_order(self, symbol: str, order_type: str, side: str, amount: float,
                          price: Optional[float] = None, params: Optional[Dict] = None) -> Dict:
        """주문 생성"""
        result: Dict = await self.exchange.create_order(symbol, order_type, side, amount, price, params)
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