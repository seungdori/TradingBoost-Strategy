"""통합 OKX API 클라이언트

HYPERRSI와 GRID 전략에서 공통으로 사용되는 OKX 거래소 API 클라이언트
"""
from decimal import Decimal
import hmac
import base64
import time
import aiohttp
import asyncio
import json
import hashlib
import ssl
from typing import Any, Dict, List, Optional

from shared.config import get_settings
from shared.logging import get_logger
from shared.exchange.base import ExchangeBase
from shared.models.exchange import (
    OrderRequest, OrderResponse,
    OrderSide, PositionSide, OrderStatus, OrderType,
    CancelOrdersResponse
)
# HYPERRSI 전용 모델은 HYPERRSI에서 import
try:
    from HYPERRSI.src.api.exchange.models import Position
except ImportError:
    # Position이 필요한 경우를 위한 임시 정의
    from pydantic import BaseModel, Field
    from decimal import Decimal
    from typing import Optional, List

    class Position(BaseModel):  # type: ignore[no-redef]
        symbol: str
        side: PositionSide
        size: Decimal
        entry_price: Decimal
        mark_price: Decimal
        liquidation_price: Optional[Decimal] = None
        unrealized_pnl: Decimal
        leverage: float
        margin_type: str = "cross"
        maintenance_margin: Optional[Decimal] = None
        margin_ratio: Optional[Decimal] = None
        sl_price: Optional[Decimal] = None
        sl_order_id: Optional[str] = None
        sl_contracts_amount: Optional[Decimal] = None
        tp_prices: List[Decimal] = []
        tp_state: Optional[str] = None
        get_tp1: Optional[Decimal] = None
        get_tp2: Optional[Decimal] = None
        get_tp3: Optional[Decimal] = None
        sl_data: Optional[dict] = None
        tp_data: Optional[dict] = None
        tp_contracts_amounts: Optional[Decimal] = None
        last_update_time: Optional[int] = None

        class Config:
            arbitrary_types_allowed = True
from shared.exchange.okx.constants import BASE_URL, V5_API, ENDPOINTS, ERROR_CODES
from shared.exchange.okx.exceptions import OKXAPIException

logger = get_logger(__name__)


class OKXClient(ExchangeBase):
    """
    OKX 거래소 API 통합 클라이언트 (싱글턴 패턴)

    HYPERRSI와 GRID 전략에서 공통으로 사용되는 OKX API 기능 제공
    - 잔고 조회
    - 포지션 관리
    - 주문 생성/취소
    - 시장 데이터 조회
    - K-line 데이터 조회

    Attributes:
        api_key (str): OKX API 키
        api_secret (str): OKX API 시크릿
        passphrase (str): OKX API 패스프레이즈
    """

    _instances: Dict[str, "OKXClient"] = {}
    _lock: asyncio.Lock = asyncio.Lock()

    def __new__(
        cls,
        api_key: str | None = None,
        api_secret: str | None = None,
        passphrase: str | None = None
    ) -> "OKXClient":
        settings = get_settings()
        api_key = api_key or settings.OKX_API_KEY
        instance_key = f"{api_key}"

        if instance_key not in cls._instances:
            cls._instances[instance_key] = super().__new__(cls)
        return cls._instances[instance_key]

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        passphrase: str | None = None
    ) -> None:
        if not hasattr(self, '_initialized'):
            settings = get_settings()
            self.api_key = api_key or settings.OKX_API_KEY
            self.api_secret = api_secret or settings.OKX_SECRET_KEY
            self.passphrase = passphrase or settings.OKX_PASSPHRASE
            self.session: Optional[aiohttp.ClientSession] = None
            self.inst_type: str = "SWAP"
            self._initialized: bool = True

    @classmethod
    async def get_instance(
        cls,
        api_key: str | None = None,
        api_secret: str | None = None,
        passphrase: str | None = None
    ) -> "OKXClient":
        """
        비동기 싱글턴 인스턴스 getter

        Returns:
            OKXClient: 클라이언트 인스턴스
        """
        async with cls._lock:
            instance = cls(api_key, api_secret, passphrase)
            await instance._init_session()
            return instance

    async def cleanup(self) -> None:
        """인스턴스 정리"""
        if self.session:
            await self.session.close()
            logger.info("OKX Client session closed")
            self.session = None
        if self.api_key in self.__class__._instances:
            del self.__class__._instances[self.api_key]

    async def _init_session(self) -> None:
        """HTTP 세션 초기화"""
        if self.session is None:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self.session = aiohttp.ClientSession(connector=connector)

    def _generate_signature(
        self,
        timestamp: str,
        method: str,
        request_path: str,
        body_dict: Dict[str, Any] | None = None
    ) -> str:
        """API 요청 서명 생성"""
        body_str = ""
        if body_dict is not None and method in ["POST", "PUT"]:
            body_str = json.dumps(body_dict, separators=(',', ':'))
        message = f"{timestamp}{method}{request_path}{body_str}"
        mac = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Dict[str, Any] | None = None,
        data: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """OKX API 요청 실행"""
        await self._init_session()
        request_path = V5_API + endpoint
        url = BASE_URL + request_path

        timestamp = str(int(time.time()))
        signature = self._generate_signature(
            timestamp,
            method,
            request_path,
            data if method in ["POST", "PUT"] else None
        )

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

        try:
            if self.session is None:
                raise OKXAPIException("Session not initialized")

            async with self.session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=data if method in ["POST", "PUT"] else None
            ) as resp:
                result: Dict[str, Any] = await resp.json()

                if resp.status != 200:
                    error_code = result.get("code", "Unknown")
                    error_msg = ERROR_CODES.get(error_code, result.get("msg", "Unknown error"))
                    raise OKXAPIException(
                        f"API request failed: {error_msg} (code: {error_code})"
                    )

                return result

        except aiohttp.ClientError as e:
            logger.error(f"Network error in OKX API request: {str(e)}")
            raise OKXAPIException(f"Network error: {str(e)}")
        except Exception as e:
            logger.error(f"Error in OKX API request: {str(e)}")
            raise

    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        params: Dict[str, Any] | None = None,
        data: Dict[str, Any] | None = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """재시도 로직이 포함된 API 요청"""
        for attempt in range(max_retries):
            try:
                return await self._request(method, endpoint, params, data)
            except OKXAPIException as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(1 * (attempt + 1))
        raise OKXAPIException("Max retries exceeded")

    # ==================== 가격 정보 ====================

    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회"""
        response = await self._request("GET", f"{ENDPOINTS['GET_TICKER']}?instId={symbol}")
        return float(response['data'][0]['last'])

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """현재가 정보 조회"""
        response = await self._request(
            "GET",
            ENDPOINTS["GET_TICKER"],
            params={"instId": symbol}
        )
        ticker_data: Dict[str, Any] = response["data"][0]
        return ticker_data

    # ==================== K-line 데이터 ====================

    async def get_klines(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """
        K-line 데이터 조회

        Args:
            symbol: 거래 쌍 (예: "BTC-USDT")
            timeframe: 시간단위 (예: "1m", "5m", "15m", "1H", "4H", "1D")
            limit: 조회할 캔들 개수

        Returns:
            List[Dict]: K-line 데이터 목록
        """
        # Timeframe 매핑 (필요시 shared/utils/timeframe.py로 이동 가능)
        from HYPERRSI.src.trading.models import get_timeframe
        tf_str = get_timeframe(timeframe) or "15m"

        endpoint = "/api/v5/market/candles"
        params = {
            "instId": symbol,
            "bar": tf_str,
            "limit": str(limit)
        }

        response = await self._request("GET", endpoint, params=params)

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

    # ==================== 잔고 조회 ====================

    async def get_balance(self, currency: str | None = None) -> Dict[str, Any]:
        """잔고 조회"""
        try:
            response = await self._request(
                "GET",
                ENDPOINTS["GET_BALANCE"],
                params={"instType": self.inst_type}
            )
            balance_data = response["data"][0]

            total = balance_data.get("totalEq", "0") or "0"
            free = balance_data.get("adjEq", "0") or "0"
            used = balance_data.get("frozenBal", "0") or "0"

            return {
                "currency": currency or "USDT",
                "total": Decimal(total),
                "free": Decimal(free),
                "used": Decimal(used)
            }
        except Exception as e:
            logger.error(f"Error in get_balance: {str(e)}")
            return {
                "currency": currency or "USDT",
                "total": Decimal("0"),
                "free": Decimal("0"),
                "used": Decimal("0")
            }

    # ==================== 포지션 조회 ====================

    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """보유 중인 포지션 조회"""
        response = await self._request("GET", ENDPOINTS["GET_POSITIONS"])
        positions: List[Dict[str, Any]] = []
        for pos_data in response["data"]:
            positions.append({
                "symbol": pos_data["instId"],
                "size": Decimal(pos_data["pos"]),
                "entry_price": Decimal(pos_data["avgPx"]),
                "leverage": Decimal(pos_data["lever"])
            })
        return positions

    async def get_all_active_positions(self) -> List[Position]:
        """모든 활성 포지션 조회 (HYPERRSI 호환)"""
        positions_data = await self.get_positions()
        positions = []
        for pos in positions_data:
            size_val = float(pos["size"])
            positions.append(
                Position(
                    symbol=pos["symbol"],
                    side=PositionSide.LONG if size_val > 0 else PositionSide.SHORT,
                    size=Decimal(str(abs(size_val))),
                    entry_price=Decimal(str(float(pos["entry_price"]))),
                    mark_price=Decimal(str(float(pos["entry_price"]))),
                    liquidation_price=None,
                    unrealized_pnl=Decimal("0"),
                    leverage=float(pos["leverage"]),
                    margin_type="cross",
                    maintenance_margin=None,
                    margin_ratio=None,
                    sl_price=None,
                    sl_order_id=None,
                    sl_contracts_amount=None,
                    tp_prices=[],
                    tp_state=None,
                    get_tp1=None,
                    get_tp2=None,
                    get_tp3=None,
                    sl_data=None,
                    tp_data=None,
                    tp_contracts_amounts=None,
                    last_update_time=None
                )
            )
        return positions

    # ==================== 주문 관리 ====================

    async def create_order(self, order: OrderRequest) -> OrderResponse:
        """주문 생성"""
        data = {
            "instId": order.symbol,
            "tdMode": "cross",
            "side": order.side.value,
            "ordType": order.type.value,
            "sz": str(order.amount),
            "px": str(order.price) if order.price else None
        }

        response = await self._request("POST", ENDPOINTS["CREATE_ORDER"], data=data)
        order_data = response["data"][0]

        return self._parse_order_response(order_data)

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """주문 취소"""
        try:
            response = await self._request(
                "POST",
                ENDPOINTS["CANCEL_ORDER"],
                data={"ordId": order_id}
            )
            result: bool = response["data"][0]["sCode"] == "0"
            return result
        except Exception as e:
            logger.error(f"Cancel order failed: {e}")
            return False

    async def get_order(self, order_id: str, symbol: Optional[str] = None) -> OrderResponse:
        """주문 상세 정보 조회"""
        response = await self._request(
            "GET",
            ENDPOINTS["GET_ORDER"],
            params={"ordId": order_id}
        )
        order_data = response["data"][0]
        return self._parse_order_response(order_data)

    async def get_orders(self) -> List[OrderResponse]:
        """미체결 주문 목록 조회"""
        response = await self._request("GET", ENDPOINTS["GET_ORDERS"])
        return [self._parse_order_response(order) for order in response["data"]]

    async def get_funding_rate(self, symbol: str) -> Dict[str, Any]:
        """자금 조달 비율 조회"""
        response = await self._request(
            "GET",
            ENDPOINTS["GET_FUNDING_RATE"],
            params={"instId": symbol}
        )
        funding_data: Dict[str, Any] = response["data"][0]
        return funding_data

    def _parse_order_response(self, order_data: Dict[str, Any]) -> OrderResponse:
        """주문 응답 데이터 파싱"""
        status_mapping = {
            "live": OrderStatus.OPEN,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELED,
            "rejected": OrderStatus.REJECTED
        }

        filled_amt = float(order_data.get("fillSz", "0"))
        total_amt = float(order_data["sz"])

        return OrderResponse(
            order_id=order_data["ordId"],
            client_order_id=order_data.get("clOrdId"),
            symbol=order_data["instId"],
            status=status_mapping.get(order_data["state"], OrderStatus.OPEN),
            side=OrderSide(order_data["side"]),
            type=OrderType(order_data["ordType"]),
            amount=total_amt,
            filled_amount=filled_amt,
            remaining_amount=total_amt - filled_amt,
            price=Decimal(order_data["px"]) if order_data.get("px") else None,
            average_price=Decimal(order_data["avgPx"]) if order_data.get("avgPx") else None,
            created_at=int(order_data.get("cTime", 0)) if order_data.get("cTime") else None,
            updated_at=int(order_data.get("uTime", 0)) if order_data.get("uTime") else None,
            pnl=None,
            order_type=order_data.get("ordType"),
            posSide=order_data.get("posSide")
        )

    async def close(self) -> None:
        """클라이언트 세션 정리"""
        if self.session:
            await self.session.close()
            logger.info("OKX Client session closed")
            self.session = None

    # ==================== 추상 메서드 구현 (TODO) ====================

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> CancelOrdersResponse:
        """모든 주문 취소 - TODO: Implement for OKX"""
        raise NotImplementedError("cancel_all_orders not yet implemented for OKX")

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderResponse]:
        """미체결 주문 목록 조회"""
        return await self.get_orders()

    async def close_position(
        self,
        symbol: str,
        side: Optional[str] = None,
        percent: float = 100.0
    ) -> Dict[str, Any]:
        """포지션 청산 - TODO: Implement for OKX"""
        raise NotImplementedError("close_position not yet implemented for OKX")

    async def get_orderbook(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """오더북 조회 - TODO: Implement for OKX"""
        raise NotImplementedError("get_orderbook not yet implemented for OKX")

    async def set_leverage(self, symbol: str, leverage: float) -> bool:
        """레버리지 설정 - TODO: Implement for OKX"""
        raise NotImplementedError("set_leverage not yet implemented for OKX")
