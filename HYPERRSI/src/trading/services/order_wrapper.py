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
        return await self.exchange.create_order(symbol, order_type, side, amount, price, params)
    
    async def cancel_order(self, order_id: str, symbol: Optional[str] = None, params: Optional[Dict] = None) -> Dict:
        """주문 취소"""
        return await self.exchange.cancel_order(order_id, symbol, params)
    
    async def fetch_order(self, order_id: str, symbol: str, params: Optional[Dict] = None) -> Dict:
        """주문 조회"""
        return await self.exchange.fetch_order(order_id, symbol, params)
    
    async def fetch_positions(self, symbols: Optional[List[str]] = None, params: Optional[Dict] = None) -> List[Dict]:
        """포지션 조회"""
        return await self.exchange.fetch_positions(symbols, params)
    
    async def fetch_open_orders(self, symbol: Optional[str] = None, since: Optional[int] = None, 
                               limit: Optional[int] = None, params: Optional[Dict] = None) -> List[Dict]:
        """미체결 주문 조회"""
        return await self.exchange.fetch_open_orders(symbol, since, limit, params)
    
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
        return await self.exchange.fetch_balance(params)
    
    async def fetch_ticker(self, symbol: str, params: Optional[Dict] = None) -> Dict:
        """현재가 조회"""
        return await self.exchange.fetch_ticker(symbol, params)
    
    async def fetch_trades(self, symbol: str, since: Optional[int] = None, 
                          limit: Optional[int] = None, params: Optional[Dict] = None) -> List[Dict]:
        """거래 내역 조회"""
        return await self.exchange.fetch_trades(symbol, since, limit, params)
    
    async def set_leverage(self, leverage: int, symbol: str, params: Optional[Dict] = None) -> Dict:
        """레버리지 설정"""
        return await self.exchange.set_leverage(leverage, symbol, params)
    
    # Private API methods
    async def private_get_account_positions(self, params: Optional[Dict] = None) -> Dict:
        """계정 포지션 조회 (private API)"""
        if self.use_backend:
            return await self._backend_request("/account/positions", params=params)
        else:
            return await self.exchange.private_get_account_positions(params)
    
    async def private_post_account_set_leverage(self, params: Dict) -> Dict:
        """레버리지 설정 (private API)"""
        if self.use_backend:
            return await self._backend_request("/account/set-leverage", method="POST", json_data=params)
        else:
            return await self.exchange.private_post_account_set_leverage(params)
    
    async def privateGetTradeOrdersAlgoPending(self, params: Optional[Dict] = None) -> Dict:
        """활성 알고리즘 주문 조회 (private API)"""
        if self.use_backend:
            return await self._backend_request("/trade/orders-algo-pending", params=params)
        else:
            return await self.exchange.private_get_trade_orders_algo_pending(params)
    
    async def privateGetTradeOrdersAlgoHistory(self, params: Optional[Dict] = None) -> Dict:
        """알고리즘 주문 히스토리 조회 (private API)"""
        if self.use_backend:
            return await self._backend_request("/trade/orders-algo-history", params=params)
        else:
            return await self.exchange.private_get_trade_orders_algo_history(params)
    
    async def private_post_trade_cancel_algos(self, params: Dict) -> Dict:
        """알고리즘 주문 취소 (private API)"""
        if self.use_backend:
            return await self._backend_request("/trade/cancel-algos", method="POST", json_data=params)
        else:
            return await self.exchange.private_post_trade_cancel_algos(params)
    
    # Utility methods to mimic ccxt behavior
    def get_market(self, symbol: str) -> Dict:
        """시장 정보 가져오기"""
        if not self.use_backend and hasattr(self.exchange, 'markets'):
            return self.exchange.markets.get(symbol, {})
        return {}
    
    @property
    def has(self) -> Dict:
        """지원 기능 확인"""
        if not self.use_backend:
            return self.exchange.has
        # 백엔드 사용 시 기본값 반환
        return {
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