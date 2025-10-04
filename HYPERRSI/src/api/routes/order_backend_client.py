#src/api/routes/order_backend_client.py
import aiohttp
from typing import Dict, Optional, List
from HYPERRSI.src.core.logger import get_logger
from HYPERRSI.src.config import settings
from fastapi import HTTPException

logger = get_logger(__name__)

class OrderBackendClient:
    """ORDER_BACKEND를 통한 주문 처리 클라이언트 (라우트용)"""
    
    def __init__(self):
        self.backend_url = settings.ORDER_BACKEND
        self.timeout = aiohttp.ClientTimeout(total=30)
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self.session
        
    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None
            
    async def _forward_request(self, endpoint: str, method: str = "GET", json_data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict:
        """요청을 ORDER_BACKEND로 전달"""
        session = await self._get_session()
        
        url = f"{self.backend_url}{endpoint}"
        
        # 요청 전 파라미터 로깅
        logger.debug(f"=== Order Backend Request Debug ===")
        logger.debug(f"Endpoint: {endpoint}")
        logger.debug(f"Method: {method}")
        logger.debug(f"Original params: {params}")
        logger.debug(f"JSON data: {json_data}")
        
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": settings.OKX_API_KEY,
            "X-SECRET-KEY": settings.OKX_SECRET_KEY,
            "X-PASSPHRASE": settings.OKX_PASSPHRASE
        }
        
        # boolean 값을 문자열로 변환, None 값은 제거
        if params:
            cleaned_params = {}
            for k, v in params.items():
                logger.debug(f"Processing param: {k} = {v} (type: {type(v)})")
                if v is not None:
                    if isinstance(v, bool):
                        cleaned_params[k] = str(v).lower()
                    else:
                        cleaned_params[k] = v
                else:
                    logger.debug(f"Removing None value for key: {k}")
            params = cleaned_params
            logger.debug(f"Cleaned params: {params}")
        
        logger.info(f"Making request to: {url} with params: {params}")
        
        try:
            async with session.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
                headers=headers
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Backend error response: {response.status} - {error_text}")
                    raise HTTPException(status_code=response.status, detail=error_text)
                
                return await response.json()
                
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error in order backend request: {e}")
            raise HTTPException(status_code=503, detail="Backend connection error")
        except Exception as e:
            logger.error(f"Error in order backend request: {e}")
            raise HTTPException(status_code=500, detail=str(e))
            
    async def get_open_orders(self, user_id: str, symbol: Optional[str] = None) -> List[Dict]:
        """열린 주문 목록 조회"""
        params = {"user_id": user_id}
        if symbol:
            params["symbol"] = symbol
        return await self._forward_request("/order/list", params=params)
        
    async def get_order_detail(self, order_id: str, user_id: str, symbol: Optional[str] = None, is_algo: bool = False, algo_type: str = "trigger") -> Dict:
        """주문 상세 조회"""
        params = {
            "user_id": user_id,
            "is_algo": is_algo,
            "algo_type": algo_type
        }
        if symbol:
            params["symbol"] = symbol
        return await self._forward_request(f"/order/detail/{order_id}", params=params)
        
    async def create_order(self, order_data: Dict, user_id: str) -> Dict:
        """주문 생성"""
        params = {"user_id": user_id}
        return await self._forward_request("/order", method="POST", json_data=order_data, params=params)
        
    async def close_position(self, symbol: str, close_request_data: Dict, user_id: str, side: Optional[str] = None) -> Dict:
        """포지션 종료"""
        params = {"user_id": user_id}
        if side:
            params["side"] = side
        return await self._forward_request(f"/order/position/close/{symbol}", method="POST", json_data=close_request_data, params=params)
        
    async def update_stop_loss(self, params: Dict) -> Dict:
        """스탑로스 업데이트"""
        return await self._forward_request("/order/position/sl", method="POST", params=params)
        
    async def cancel_order(self, order_id: str, user_id: str, symbol: Optional[str] = None) -> Dict:
        """주문 취소"""
        params = {"user_id": user_id}
        if symbol:
            params["symbol"] = symbol
        return await self._forward_request(f"/order/{order_id}", method="DELETE", params=params)
        
    async def cancel_all_orders(self, symbol: str, user_id: str, side: Optional[str] = None) -> Dict:
        """모든 주문 취소"""
        params = {"user_id": user_id}
        if side:
            params["side"] = side
        return await self._forward_request(f"/order/cancel-all/{symbol}", method="DELETE", params=params)
        
    async def cancel_algo_orders(self, symbol: str, user_id: str, side: Optional[str] = None, algo_type: str = "trigger") -> Dict:
        """알고리즘 주문 취소"""
        params = {"user_id": user_id, "algo_type": algo_type}
        if side:
            params["side"] = side
        return await self._forward_request(f"/order/algo-orders/{symbol}", method="DELETE", params=params)
        
    async def get_algo_order_info(self, order_id: str, symbol: str, user_id: str, algo_type: str = "trigger") -> Dict:
        """알고리즘 주문 정보 조회"""
        params = {
            "user_id": user_id,
            "symbol": symbol,
            "algo_type": algo_type
        }
        return await self._forward_request(f"/order/algo/{order_id}", params=params)