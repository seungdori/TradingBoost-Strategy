"""거래소 API 추상 베이스 클래스

모든 거래소 구현체가 따라야 하는 공통 인터페이스
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from decimal import Decimal

# 공통 모델 import
from shared.models.exchange import (
    OrderRequest, 
    OrderResponse, 
    CancelOrdersResponse,
    OrderType,
    OrderSide,
    OrderStatus
)


class ExchangeBase(ABC):
    """거래소 API 추상 베이스 클래스
    
    모든 거래소(OKX, Binance, Upbit, Bitget 등)는 이 클래스를 상속받아 구현해야 합니다.
    """
    
    def __init__(self, api_key: str, api_secret: str, passphrase: Optional[str] = None):
        """
        거래소 클라이언트 초기화
        
        Args:
            api_key: API 키
            api_secret: API 시크릿
            passphrase: API 패스프레이즈 (OKX 등 일부 거래소에서 필요)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
    
    # ==================== 잔고 관련 ====================
    
    @abstractmethod
    async def get_balance(self, currency: Optional[str] = None) -> Dict[str, Any]:
        """
        잔고를 조회합니다.
        
        Args:
            currency: 화폐 심볼 (예: "BTC", "USDT"). None이면 전체 잔고
            
        Returns:
            Dict: 잔고 정보
            {
                "currency": "USDT",
                "total": Decimal("1000.0"),
                "free": Decimal("800.0"),
                "used": Decimal("200.0")
            }
        """
        raise NotImplementedError
    
    # ==================== 주문 관련 ====================
    
    @abstractmethod
    async def create_order(self, order: OrderRequest) -> OrderResponse:
        """
        주문을 생성합니다.
        
        Args:
            order: 주문 요청 정보
            
        Returns:
            OrderResponse: 주문 응답 정보
        """
        raise NotImplementedError
    
    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """
        주문을 취소합니다.
        
        Args:
            order_id: 취소할 주문 ID
            symbol: 심볼 (일부 거래소에서 필요)
            
        Returns:
            bool: 취소 성공 여부
        """
        raise NotImplementedError
    
    @abstractmethod
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> CancelOrdersResponse:
        """
        모든 주문을 취소합니다.
        
        Args:
            symbol: 특정 심볼의 주문만 취소. None이면 전체 취소
            
        Returns:
            CancelOrdersResponse: 취소 결과
        """
        raise NotImplementedError
    
    @abstractmethod
    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> OrderResponse:
        """
        주문 정보를 조회합니다.
        
        Args:
            order_id: 주문 ID
            symbol: 심볼 (일부 거래소에서 필요)
            
        Returns:
            OrderResponse: 주문 정보
        """
        raise NotImplementedError
    
    @abstractmethod
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderResponse]:
        """
        미체결 주문 목록을 조회합니다.
        
        Args:
            symbol: 특정 심볼의 주문만 조회. None이면 전체 조회
            
        Returns:
            List[OrderResponse]: 미체결 주문 목록
        """
        raise NotImplementedError
    
    # ==================== 포지션 관련 ====================
    
    @abstractmethod
    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        현재 보유 중인 포지션 목록을 조회합니다.
        
        Args:
            symbol: 특정 심볼의 포지션만 조회. None이면 전체 조회
            
        Returns:
            List[Dict]: 포지션 목록
        """
        raise NotImplementedError
    
    @abstractmethod
    async def close_position(
        self, 
        symbol: str, 
        side: Optional[str] = None,
        percent: float = 100.0
    ) -> Dict[str, Any]:
        """
        포지션을 청산합니다.
        
        Args:
            symbol: 청산할 포지션의 심볼
            side: 포지션 방향 ("long" 또는 "short"). None이면 전체
            percent: 청산 비율 (0-100)
            
        Returns:
            Dict: 청산 결과
        """
        raise NotImplementedError
    
    # ==================== 시장 정보 ====================
    
    @abstractmethod
    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        특정 심볼의 현재가 정보를 조회합니다.
        
        Args:
            symbol: 거래 쌍 심볼 (예: "BTC-USDT-SWAP")
            
        Returns:
            Dict: 현재가 정보
            {
                "symbol": "BTC-USDT-SWAP",
                "last_price": Decimal("50000.0"),
                "bid": Decimal("49999.0"),
                "ask": Decimal("50001.0"),
                "high": Decimal("51000.0"),
                "low": Decimal("49000.0"),
                "volume": Decimal("1000.0"),
                "timestamp": 1234567890
            }
        """
        raise NotImplementedError
    
    @abstractmethod
    async def get_orderbook(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """
        오더북(호가창)을 조회합니다.
        
        Args:
            symbol: 거래 쌍 심볼
            limit: 조회할 호가 개수
            
        Returns:
            Dict: 오더북 정보
            {
                "symbol": "BTC-USDT-SWAP",
                "bids": [[price, amount], ...],
                "asks": [[price, amount], ...],
                "timestamp": 1234567890
            }
        """
        raise NotImplementedError
    
    # ==================== 레버리지 관련 ====================
    
    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: float) -> bool:
        """
        레버리지를 설정합니다.
        
        Args:
            symbol: 심볼
            leverage: 레버리지 배수
            
        Returns:
            bool: 설정 성공 여부
        """
        raise NotImplementedError
