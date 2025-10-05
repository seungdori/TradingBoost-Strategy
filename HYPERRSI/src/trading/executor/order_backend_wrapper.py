#src/trading/executor/order_backend_wrapper.py
import os
import aiohttp
import asyncio
from typing import Optional, Dict, Any
from decimal import Decimal
from dataclasses import dataclass, asdict
from shared.logging import get_logger
from HYPERRSI.src.config import settings
from HYPERRSI.src.api.exchange.models import (
    OrderRequest, OrderResponse, OrderType, OrderSide, 
    TimeInForce
)

logger = get_logger(__name__)

class OrderBackendClient:
    """ORDER_BACKEND를 통한 주문 처리 클라이언트"""
    
    def __init__(self, backend_url: str, timeout: int = 30):
        self.backend_url = backend_url.rstrip('/')
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """aiohttp 세션 획득"""
        if self.session is None:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self.session
        
    async def close(self):
        """세션 종료"""
        if self.session:
            await self.session.close()
            self.session = None
            
    async def create_order(self, order_request: OrderRequest) -> OrderResponse:
        """ORDER_BACKEND를 통해 주문 생성"""
        session = await self._get_session()
        
        # OrderRequest를 JSON으로 변환 가능한 딕셔너리로 변환
        payload = {
            "symbol": order_request.symbol,
            "type": order_request.type.value,
            "side": order_request.side.value,
            "amount": str(order_request.amount),
            "price": str(order_request.price) if order_request.price else None,
            "time_in_force": order_request.time_in_force.value,
            "reduce_only": order_request.reduce_only,
            "post_only": order_request.post_only,
            "client_order_id": order_request.client_order_id
        }
        
        # None 값 제거
        payload = {k: v for k, v in payload.items() if v is not None}
        
        # API 키와 기타 인증 정보 추가
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": settings.OKX_API_KEY,
            "X-SECRET-KEY": settings.OKX_SECRET_KEY,
            "X-PASSPHRASE": settings.OKX_PASSPHRASE
        }
        
        try:
            async with session.post(
                f"{self.backend_url}/api/order/create",
                json=payload,
                headers=headers
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Backend error: {response.status} - {error_text}")
                
                result = await response.json()
                
                # 응답을 OrderResponse 객체로 변환
                return OrderResponse(
                    order_id=result["order_id"],
                    client_order_id=result.get("client_order_id"),
                    status=result["status"],
                    timestamp=result.get("timestamp"),
                    filled_amount=Decimal(result.get("filled_amount", "0")),
                    remaining_amount=Decimal(result.get("remaining_amount", "0")),
                    average_price=Decimal(result.get("average_price", "0")) if result.get("average_price") else None,
                    fee=result.get("fee"),
                    trades=result.get("trades", [])
                )
                
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error in order creation: {e}")
            raise
        except Exception as e:
            logger.error(f"Error creating order via backend: {e}")
            raise
            
    async def cancel_order(self, order_id: str) -> bool:
        """ORDER_BACKEND를 통해 주문 취소"""
        session = await self._get_session()
        
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": settings.OKX_API_KEY,
            "X-SECRET-KEY": settings.OKX_SECRET_KEY,
            "X-PASSPHRASE": settings.OKX_PASSPHRASE
        }
        
        try:
            async with session.post(
                f"{self.backend_url}/api/order/cancel",
                json={"order_id": order_id},
                headers=headers
            ) as response:
                if response.status != 200:
                    return False
                    
                result = await response.json()
                return result.get("success", False)
                
        except Exception as e:
            logger.error(f"Error canceling order via backend: {e}")
            return False
            
    async def get_order(self, order_id: str) -> OrderResponse:
        """ORDER_BACKEND를 통해 주문 정보 조회"""
        session = await self._get_session()
        
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": settings.OKX_API_KEY,
            "X-SECRET-KEY": settings.OKX_SECRET_KEY,
            "X-PASSPHRASE": settings.OKX_PASSPHRASE
        }
        
        try:
            async with session.get(
                f"{self.backend_url}/api/order/{order_id}",
                headers=headers
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Backend error: {response.status} - {error_text}")
                
                result = await response.json()
                
                # 응답을 OrderResponse 객체로 변환
                return OrderResponse(
                    order_id=result["order_id"],
                    client_order_id=result.get("client_order_id"),
                    status=result["status"],
                    timestamp=result.get("timestamp"),
                    filled_amount=Decimal(result.get("filled_amount", "0")),
                    remaining_amount=Decimal(result.get("remaining_amount", "0")),
                    average_price=Decimal(result.get("average_price", "0")) if result.get("average_price") else None,
                    fee=result.get("fee"),
                    trades=result.get("trades", [])
                )
                
        except Exception as e:
            logger.error(f"Error getting order via backend: {e}")
            raise

class OrderBackendWrapper:
    """주문 처리 래퍼 - 로컬 또는 원격 백엔드 자동 선택"""
    
    def __init__(self, exchange_client):
        self.exchange = exchange_client
        self.backend_url = settings.ORDER_BACKEND
        
        # ORDER_BACKEND가 설정되어 있고 localhost가 아닌 경우 백엔드 클라이언트 사용
        if self.backend_url and "localhost" not in self.backend_url and "127.0.0.1" not in self.backend_url:
            self.backend_client = OrderBackendClient(self.backend_url)
            self.use_backend = True
            #logger.info(f"Using ORDER_BACKEND: {self.backend_url}")
        else:
            self.backend_client = None
            self.use_backend = False
            logger.info("Using local exchange client for orders")
            
    async def create_order(self, order_request: OrderRequest) -> OrderResponse:
        """주문 생성 - 백엔드 또는 로컬 자동 선택"""
        if self.use_backend:
            return await self.backend_client.create_order(order_request)
        else:
            return await self.exchange.create_order(order_request)
            
    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소 - 백엔드 또는 로컬 자동 선택"""
        if self.use_backend:
            return await self.backend_client.cancel_order(order_id)
        else:
            result = await self.exchange.cancel_order(order_id)
            return bool(result)
            
    async def get_order(self, order_id: str) -> OrderResponse:
        """주문 조회 - 백엔드 또는 로컬 자동 선택"""
        if self.use_backend:
            return await self.backend_client.get_order(order_id)
        else:
            return await self.exchange.get_order(order_id)
            
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> bool:
        """모든 주문 취소"""
        if self.use_backend and hasattr(self.backend_client, 'cancel_all_orders'):
            # 백엔드가 일괄 취소를 지원하는 경우
            return await self.backend_client.cancel_all_orders(symbol)
        elif not self.use_backend:
            # 로컬 exchange client 사용
            result = await self.exchange.cancel_all_orders(symbol)
            return bool(result)
        else:
            # 백엔드 사용이지만 일괄 취소 미지원 시 개별 취소
            # 이 경우 active orders 목록을 관리해야 함
            logger.warning("Backend doesn't support cancel_all_orders")
            return False
            
    async def close(self):
        """리소스 정리"""
        if self.backend_client:
            await self.backend_client.close()