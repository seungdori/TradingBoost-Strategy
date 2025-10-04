#scr.api.exchange.okx.client.py
from decimal import Decimal
import hmac
import base64
import time
import aiohttp
import asyncio
import json
import hashlib
from typing import Dict, List, Optional
from HYPERRSI.src.core.config import settings
from HYPERRSI.src.core.logger import get_logger
from ..base import ExchangeBase
from ..models import OrderRequest, OrderResponse, Balance, Position, OrderSide
from .constants import BASE_URL, V5_API, ENDPOINTS, ERROR_CODES
from .exceptions import OKXAPIException
from fastapi import APIRouter, Depends, HTTPException
from HYPERRSI.src.api.exchange.models import (
    OrderRequest, OrderResponse, Balance, Position,
    OrderSide, BalanceResponseModel,
    PositionResponseModel, TickerResponseModel
)
from HYPERRSI.src.trading.models import tf_mapping, get_timeframe
import ssl
import datetime

logger = get_logger(__name__)

class OKXClient(ExchangeBase):
    """
    OKX 거래소 API 클라이언트 (싱글턴 패턴)
    
    Attributes:
        api_key (str): OKX API 키
        api_secret (str): OKX API 시크릿
        passphrase (str): OKX API 패스프레이즈
    """
    _instances = {}  # API 키별로 다른 인스턴스를 유지하기 위한 딕셔너리
    _lock = asyncio.Lock()
    
    def __new__(cls, api_key: str = None, api_secret: str = None, passphrase: str = None):
        api_key = api_key or settings.OKX_API_KEY
        instance_key = f"{api_key}"  # API 키를 기반으로 한 고유 키
        
        if instance_key not in cls._instances:
            cls._instances[instance_key] = super().__new__(cls)
        return cls._instances[instance_key]
    
    def __init__(self, api_key: str = None, api_secret: str = None, passphrase: str = None):
        if not hasattr(self, '_initialized'):
            self.api_key = api_key or settings.OKX_API_KEY
            self.api_secret = api_secret or settings.OKX_SECRET_KEY
            self.passphrase = passphrase or settings.OKX_PASSPHRASE
            self.session = None
            self.inst_type = "SWAP"
            self._initialized = True

    @classmethod
    async def get_instance(cls, api_key: str = None, api_secret: str = None, passphrase: str = None):
        """
        비동기 싱글턴 인스턴스 getter
        
        Returns:
            OKXClient: 클라이언트 인스턴스
        """
        async with cls._lock:
            instance = cls(api_key, api_secret, passphrase)
            await instance._init_session()
            return instance
    async def cleanup(self):
        """인스턴스 정리"""
        if self.session:
            await self.session.close()
            print("OKX Client session closed.2")
            self.session = None
        if self.api_key in self.__class__._instances:
            del self.__class__._instances[self.api_key]    

    async def _init_session(self):
        if self.session is None:
            # SSL 검증을 비활성화하는 컨텍스트 생성
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            # 커넥터 생성
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            # 세션 생성 시 커넥터 사용
            self.session = aiohttp.ClientSession(connector=connector)
    def _generate_signature(self, timestamp: str, method: str, request_path: str, body_dict: dict = None) -> str:
        """타임스탬프를 서버 시간 기준으로 생성"""
        body_str = ""
        if body_dict is not None and method in ["POST", "PUT"]:  
        # GET/DELETE는 일반적으로 OKX에서 body 없이 처리
            body_str = json.dumps(body_dict, separators=(',', ':'))
        message = f"{timestamp}{method}{request_path}{body_str}"
        print("Signature Components:")
        print(f"Timestamp: {timestamp}")
        print(f"Method: {method}")
        print(f"Path: {request_path}")
        print(f"Final message: {message}")
        mac = hmac.new(
        self.api_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    )
        return base64.b64encode(mac.digest()).decode()
    async def _request(self, method: str, endpoint: str, params: Dict=None, data: Dict=None) -> Dict:
        await self._init_session()
        request_path = V5_API + endpoint  # => "/api/v5/account/positions"
        url = BASE_URL + request_path     # => "https://www.okx.com/api/v5/account/positions"

        # Timestamp(UTC ISO8601)
        timestamp = str(int(time.time()))

    # GET/DELETE는 보통 data=None → body = "" 로 서명
    # POST/PUT만 data를 json.dumps 로 전송 & 서명
        signature = self._generate_signature(timestamp, method, request_path, data if method in ["POST","PUT"] else None)

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }
        print("====================================")
        print("headers", headers)
        print("====================================")
        try:
            async with self.session.request(method, url, headers=headers, params=params, json=data if method in ["POST","PUT"] else None) as resp:
                result = await resp.json()
                
                if resp.status != 200:
                    error_code = result.get("code", "Unknown")
                    error_msg = ERROR_CODES.get(error_code, result.get("msg", "Unknown error"))
                    raise OKXAPIException(f"API request failed: {error_msg} (code: {error_code})")
                
                return result
        except aiohttp.ClientError as e:
            logger.error(f"Network error in OKX API request: {str(e)}")
            raise OKXAPIException(f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Error in OKX API request: {str(e)}")
            raise
    
    async def _request_with_retry(self, method: str, endpoint: str, 
                                params: Dict = None, data: Dict = None,
                                max_retries: int = 3) -> Dict:
        for attempt in range(max_retries):
            try:
                return await self._request(method, endpoint, params, data)
            except OKXAPIException as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(1 * (attempt + 1))
    async def get_current_price(self, symbol: str) -> float:
        response = await self._request("GET", f"{ENDPOINTS['GET_TICKER']}?instId={symbol}")
        return float(response['data'][0]['last'])

    async def get_all_active_positions(self) -> List[Position]:
        positions_data = await self.get_positions()  # self.client 대신 직접 호출
        positions = []
        for pos in positions_data:
            positions.append(
                Position(
                    side="long" if float(pos.size) > 0 else "short",
                    size=abs(float(pos.size)),
                    entry_price=float(pos.entry_price),
                    leverage=int(pos.leverage),
                    tp_prices=[],
                    sl_price=None
                )
            )
        return positions
    
    async def get_balance(self, currency: str = None) -> Balance:
        try:
            response = await self._request(
                "GET", 
                ENDPOINTS["GET_BALANCE"],
                params={"instType": self.inst_type}
            )
            balance_data = response["data"][0]
        
            print(balance_data)
            # Ensure values are strings and handle potential None values
            # 값이 없거나 빈 문자열인 경우 "0"으로 기본값 설정
            total = balance_data.get("totalEq", "0") or "0"
            free = balance_data.get("adjEq", "0") or "0"
            used = balance_data.get("frozenBal", "0") or "0"

            return Balance(
                currency=currency or "USDT",
                total=total,
                free=free,
                used=used
            )
        except Exception as e:
            logger.error(f"Error in get_balance: {str(e)}")
            print('OKX API : ', self.api_key, self.api_secret, self.passphrase)
            # Return default balance on error
            return Balance(
                currency=currency or "USDT",
                total="0",
                free="0",
                used="0"
            )
        
    async def get_klines(self, symbol: str, timeframe: str, limit: int = 200):
        """
        K-line 데이터 조회
        :param symbol: 거래 쌍 (예: "BTC-USDT")
        :param timeframe: 시간단위 (예: "1m", "5m", "15m", "1H", "4H", "1D")
        :param limit: 조회할 캔들 개수
        """
        # OKX API의 K-line endpoint
        endpoint = f"/api/v5/market/candles"
        tf_str = get_timeframe(timeframe)
        if tf_str is None:
            tf_str = "15m"
        
        params = {
            "instId": symbol,
            "bar": tf_str,  # 기본값 15m
            "limit": str(limit)
        }
        
        response = await self._request("GET", endpoint, params=params)
        
        # OKX API 응답 형식: [timestamp, open, high, low, close, volume, ...]
        return [
            {
                'timestamp': int(candle[0]),
                'open': float(candle[1]),
                'high': float(candle[2]),
                'low': float(candle[3]),
                'close': float(candle[4]),
                'volume': float(candle[5])
            }
            for candle in response['data']
        ]    

    async def create_order(self, order: OrderRequest) -> OrderResponse:
        """
        새로운 주문 생성
        
        Args:
            order (OrderRequest): 주문 요청 객체
                - symbol (str): 거래 쌍
                - side (OrderSide): 매수/매도 구분
                - type (OrderType): 주문 유형
                - amount (Decimal): 주문 수량
                - price (Decimal, optional): 주문 가격
                
        Returns:
            OrderResponse: 주문 응답 객체
                - order_id (str): 주문 ID
                - symbol (str): 거래 쌍
                - status (str): 주문 상태
                - side (OrderSide): 매수/매도 구분
                - amount (Decimal): 주문 수량
                - filled_amount (Decimal): 체결된 수량
                - price (Decimal): 주문 가격
                - average_price (Decimal): 평균 체결 가격
                
        Raises:
            OKXAPIException: API 요청 실패 시
        """
        data = {
            "instId": order.symbol,
            "tdMode": "cross",  # 또는 "isolated"
            "side": order.side.value,
            "ordType": order.type.value,
            "sz": str(order.amount),
            "px": str(order.price) if order.price else None
        }
        
        response = await self._request("POST", ENDPOINTS["CREATE_ORDER"], data=data)
        order_data = response["data"][0]
        
        return OrderResponse(
            order_id=order_data["ordId"],
            symbol=order_data["instId"],
            status=order_data["state"],
            side=OrderSide(order_data["side"]),
            amount=Decimal(order_data["sz"]),
            filled_amount=Decimal(order_data.get("fillSz", "0")),
            price=Decimal(order_data["px"]) if order_data.get("px") else None,
            average_price=Decimal(order_data["avgPx"]) if order_data.get("avgPx") else None
        )

    async def cancel_order(self, order_id: str) -> bool:
        """
        주문 취소
        
        Args:
            order_id (str): 취소할 주문의 ID
            
        Returns:
            bool: 취소 성공 여부
            
        Raises:
            OKXAPIException: API 요청 실패 시
        """
        try:
            response = await self._request(
                "POST", 
                ENDPOINTS["CANCEL_ORDER"], 
                data={"ordId": order_id}
            )
            return response["data"][0]["sCode"] == "0"
        except Exception as e:
            logger.error(f"Cancel order failed: {e}")
            return False

    async def get_positions(self) -> List[Position]:
        """
        보유 중인 포지션 조회
        
        Returns:
            List[Position]: 포지션 목록
                - symbol (str): 거래 쌍
                - size (Decimal): 포지션 크기
                - entry_price (Decimal): 진입 가격
                - leverage (Decimal): 레버리지
                
        Raises:
            OKXAPIException: API 요청 실패 시
        """
        response = await self._request("GET", ENDPOINTS["GET_POSITIONS"])
        print(response)
        positions = []
        for pos_data in response["data"]:
            positions.append(Position(
                symbol=pos_data["instId"],
                size=Decimal(pos_data["pos"]),
                entry_price=Decimal(pos_data["avgPx"]),
                leverage=Decimal(pos_data["lever"])
            ))
        return positions

    async def get_ticker(self, symbol: str) -> Dict:
        """
        현재가 정보 조회
        
        Args:
            symbol (str): 거래 쌍
            
        Returns:
            Dict: 현재가 정보를 포함하는 딕셔너리
            
        Raises:
            OKXAPIException: API 요청 실패 시
        """
        response = await self._request(
            "GET", 
            ENDPOINTS["GET_TICKER"], 
            params={"instId": symbol}
        )
        return response["data"][0]

    async def get_order(self, order_id: str) -> OrderResponse:
        """
        주문 상세 정보 조회
        
        Args:
            order_id (str): 조회할 주문의 ID
            
        Returns:
            OrderResponse: 주문 정보 객체
            
        Raises:
            OKXAPIException: API 요청 실패 시
        """
        response = await self._request(
            "GET", 
            ENDPOINTS["GET_ORDER"], 
            params={"ordId": order_id}
        )
        order_data = response["data"][0]
        return self._parse_order_response(order_data)

    async def get_orders(self) -> List[OrderResponse]:
        """
        미체결 주문 목록 조회
        
        Returns:
            List[OrderResponse]: 주문 정보 객체 목록
            
        Raises:
            OKXAPIException: API 요청 실패 시
        """
        response = await self._request("GET", ENDPOINTS["GET_ORDERS"])
        return [self._parse_order_response(order) for order in response["data"]]

    async def get_funding_rate(self, symbol: str) -> Dict:
        """
        자금 조달 비율 조회
        
        Args:
            symbol (str): 거래 쌍
            
        Returns:
            Dict: 자금 조달 비율 정보를 포함하는 딕셔너리
            
        Raises:
            OKXAPIException: API 요청 실패 시
        """
        response = await self._request(
            "GET",
            ENDPOINTS["GET_FUNDING_RATE"],
            params={"instId": symbol}
        )
        return response["data"][0]

    def _parse_order_response(self, order_data: Dict) -> OrderResponse:
        """주문 응답 데이터 파싱 헬퍼 메서드"""
        return OrderResponse(
            order_id=order_data["ordId"],
            symbol=order_data["instId"],
            status=order_data["state"],
            side=OrderSide(order_data["side"]),
            amount=Decimal(order_data["sz"]),
            filled_amount=Decimal(order_data.get("fillSz", "0")),
            price=Decimal(order_data["px"]) if order_data.get("px") else None,
            average_price=Decimal(order_data["avgPx"]) if order_data.get("avgPx") else None
        )

    async def close(self):
        """클라이언트 세션 정리"""
        if self.session:
            await self.session.close()
            print("OKX Client session closed.")
            self.session = None 

router = APIRouter(prefix="/okx", tags=["OKX"])

async def get_okx_client():
    client = await OKXClient.get_instance()
    try:
        yield client
    finally:
        if client.session:
            await client.close()

@router.get("/balance", response_model=BalanceResponseModel,
            summary="계정 잔고 조회",
            description="지정된 화폐의 계정 잔고를 조회합니다.")
async def get_balance(
    currency: str = None,
    client: OKXClient = Depends(get_okx_client)
):
    try:
        balance = await client.get_balance(currency)
        return BalanceResponseModel(
            currency=balance.currency,
            total=balance.total,
            free=balance.free,
            used=balance.used
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/orders", response_model=OrderResponse,
             summary="새로운 주문 생성",
             description="새로운 거래 주문을 생성합니다.")
async def create_order(
    order: OrderRequest,
    client: OKXClient = Depends(get_okx_client)
):
    try:
        response = await client.create_order(order)
        return OrderResponse(
            order_id=response.order_id,
            symbol=response.symbol,
            status=response.status,
            side=response.side.value,
            amount=response.amount,
            filled_amount=response.filled_amount,
            price=response.price,
            average_price=response.average_price
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/positions", response_model=List[PositionResponseModel],
            summary="포지션 목록 조회",
            description="현재 보유 중인 모든 포지션을 조회합니다.")
async def get_positions(
    client: OKXClient = Depends(get_okx_client)
):
    try:
        positions = await client.get_positions()
        return [
            PositionResponseModel(
                symbol=pos.symbol,
                size=pos.size,
                entry_price=pos.entry_price,
                leverage=pos.leverage
            ) for pos in positions
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/ticker/{symbol}", response_model=TickerResponseModel,
            summary="현재가 정보 조회",
            description="특정 거래쌍의 현재가 정보를 조회합니다.")
async def get_ticker(
    symbol: str,
    client: OKXClient = Depends(get_okx_client)
):
    try:
        ticker = await client.get_ticker(symbol)
        return TickerResponseModel(
            symbol=ticker["instId"],
            last_price=Decimal(ticker["last"]),
            bid=Decimal(ticker["bidPx"]),
            ask=Decimal(ticker["askPx"]),
            volume_24h=Decimal(ticker["vol24h"])
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) 