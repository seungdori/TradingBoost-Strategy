# services/trading_service.py

import asyncio
import contextlib
import json
import logging
import time
import traceback
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import ccxt.async_support as ccxt
import httpx
import pandas as pd
import pytz  # type: ignore[import-untyped]
from fastapi import HTTPException
from numpy import minimum

from HYPERRSI.src.api.dependencies import get_exchange_client as get_okx_client
from HYPERRSI.src.api.dependencies import get_exchange_context

# Redis, OKX client 등 (실제 경로/모듈명은 프로젝트에 맞게 조정)
from shared.cache import TradingCache
from HYPERRSI.src.trading.cancel_trigger_okx import TriggerCancelClient
from HYPERRSI.src.trading.error_message import map_exchange_error
from HYPERRSI.src.trading.models import (
    OrderStatus,
    Position,
    UpdateStopLossRequest,
    order_type_mapping,
)

# Import all module classes
from HYPERRSI.src.trading.modules.market_data_service import MarketDataService
from HYPERRSI.src.trading.modules.okx_position_fetcher import OKXPositionFetcher
from HYPERRSI.src.trading.modules.order_manager import OrderManager
from HYPERRSI.src.trading.modules.position_manager import PositionManager
from HYPERRSI.src.trading.modules.tp_sl_calculator import TPSLCalculator
from HYPERRSI.src.trading.modules.tp_sl_order_creator import TPSLOrderCreator
from HYPERRSI.src.trading.services.get_current_price import get_current_price
from HYPERRSI.src.trading.services.order_utils import InsufficientMarginError
from HYPERRSI.src.trading.services.order_utils import get_order_info as get_order_info_from_module
from HYPERRSI.src.trading.services.order_utils import try_send_order
from HYPERRSI.src.trading.stats import record_trade_history_entry, update_trade_history_exit
from HYPERRSI.telegram_message import send_telegram_message
from shared.logging import get_logger
from shared.utils import (
    convert_bool_to_int,
    convert_bool_to_string,
    convert_symbol_to_okx_instrument,
)
from shared.utils import get_contract_size as get_contract_size_from_module
from shared.utils import (
    get_minimum_qty,
    get_tick_size_from_redis,
    round_to_qty,
    round_to_tick_size,
    safe_float,
)

# Initialize logger before using it
logger = get_logger(__name__)

# Import improved utilities
try:
    from HYPERRSI.src.utils.async_helpers import TaskGroupHelper
    HAS_TASKGROUP = True
except ImportError:
    HAS_TASKGROUP = False
    logger.warning("TaskGroupHelper not available, using sequential execution")

API_BASE_URL = "/api"


#===============================================
# 트레이딩 서비스 (Facade Pattern)
#===============================================

class TradingService:
    """
    Trading Service Facade
    - OKX 주문/청산/포지션 조회 로직을 모듈화된 서비스로 위임
    - Redis 포지션 저장/조회
    - 주문 상태 모니터링 (폴링 기반)
    """
    _instances: Dict[Optional[str], "TradingService"] = {}

    def __new__(cls, user_id: Optional[str] = None) -> "TradingService":
        if user_id not in cls._instances:
            cls._instances[user_id] = super().__new__(cls)
        return cls._instances[user_id]

    def __init__(self, user_id: Optional[str] = None) -> None:
        if hasattr(self, 'initialized'):
            return
        self.user_id = user_id
        self.client = None
        self.initialized = True
        self._locks: Dict[str, asyncio.Lock] = {}  # 락 딕셔너리 초기화 추가

        # Module instances (will be initialized in create_for_user)
        self.market_data: Optional[MarketDataService] = None
        self.tp_sl_calc: Optional[TPSLCalculator] = None
        self.okx_fetcher: Optional[OKXPositionFetcher] = None
        self.order_manager: Optional[OrderManager] = None
        self.tp_sl_creator: Optional[TPSLOrderCreator] = None
        self.position_mgr: Optional[PositionManager] = None

    @classmethod
    async def create_for_user(cls, user_id: str) -> "TradingService":
        """해당 user_id에 대한 TradingService 인스턴스 생성(OKX 클라이언트 연결)"""
        try:
            instance = cls(user_id)

            # 컨텍스트 매니저 사용하여 클라이언트 자동 반환 보장
            async with get_exchange_context(str(user_id)) as client:
                instance.client = client
                if instance.client is None:
                    raise Exception("OKX client initialization failed")

            # Initialize all modules (moved outside of context to avoid unreachable code warning)
            instance.market_data = MarketDataService(instance)  # type: ignore[unreachable]
            instance.tp_sl_calc = TPSLCalculator(instance)
            instance.okx_fetcher = OKXPositionFetcher(instance)
            instance.order_manager = OrderManager(instance)
            instance.tp_sl_creator = TPSLOrderCreator(instance)
            instance.position_mgr = PositionManager(instance)

            return instance
        except Exception as e:
            logger.error(f"Failed to create trading service for user {user_id}: {str(e)}")
            raise Exception(f"트레이딩 서비스 생성 실패: {str(e)}")

    @contextlib.asynccontextmanager
    async def position_lock(self, user_id: str, symbol: str) -> AsyncGenerator[None, None]:
        """asyncio를 이용한 로컬 락"""
        lock_key = f"position:{user_id}:{symbol}"

        if lock_key not in self._locks:
            self._locks[lock_key] = asyncio.Lock()

        lock = self._locks[lock_key]

        try:
            await lock.acquire()
            yield
        finally:
            lock.release()

    #===============================================
    # Delegated Methods - Position Management
    #===============================================

    async def contract_size_to_qty(self, user_id: str, symbol: str, contracts_amount: float) -> float:
        """계약 수를 주문 수량으로 변환"""
        if self.position_mgr is None:
            raise RuntimeError("PositionManager not initialized")
        return await self.position_mgr.contract_size_to_qty(user_id, symbol, contracts_amount)

    async def get_current_position(
        self,
        user_id: str,
        symbol: Optional[str] = None,
        pos_side: Optional[str] = None
    ) -> Optional[Position]:
        """현재 포지션 조회"""
        if self.position_mgr is None:
            raise RuntimeError("PositionManager not initialized")
        return await self.position_mgr.get_current_position(user_id, symbol, pos_side)

    async def get_contract_size(self, user_id: str, symbol: str) -> float:
        """계약 크기 조회"""
        if self.position_mgr is None:
            raise RuntimeError("PositionManager not initialized")
        return await self.position_mgr.get_contract_size(user_id, symbol)

    async def open_position(
        self,
        user_id: str,
        symbol: str,
        direction: str,
        size: float,
        leverage: float = 10.0,
        settings: dict = {},
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        is_DCA: bool = False,
        order_concept: str = 'new_position',
        is_hedge: bool = False,
        hedge_tp_price: Optional[float] = None,
        hedge_sl_price: Optional[float] = None
    ) -> Position:
        """포지션 오픈"""
        if self.position_mgr is None:
            raise RuntimeError("PositionManager not initialized")
        return await self.position_mgr.open_position(
            user_id, symbol, direction, size, leverage, settings,
            stop_loss, take_profit, is_DCA, order_concept,
            is_hedge, hedge_tp_price, hedge_sl_price
        )

    async def close_position(
        self,
        user_id: str,
        symbol: str,
        side: str,
        order_id: Optional[str] = None,
        size: Optional[float] = None,
        reason: str = "manual",
        max_retry: int = 3,
        delay_sec: float = 1.0,
        debug: bool = False
    ) -> bool:
        """포지션 청산"""
        if self.position_mgr is None:
            raise RuntimeError("PositionManager not initialized")
        return await self.position_mgr.close_position(
            user_id, symbol, side, order_id, size, reason,
            max_retry, delay_sec, debug
        )

    #===============================================
    # Delegated Methods - TP/SL Calculator
    #===============================================

    async def update_stop_loss(
        self,
        user_id: str,
        symbol: str,
        side: str,
        new_sl_price: float,
        old_order_id: Optional[str] = None
    ) -> bool:
        """스탑로스 가격 업데이트"""
        if self.tp_sl_calc is None:
            raise RuntimeError("TPSLCalculator not initialized")
        return await self.tp_sl_calc.update_stop_loss(
            user_id, symbol, side, new_sl_price, old_order_id
        )

    async def calculate_tp_prices(
        self,
        user_id: str,
        current_price: float,
        settings: dict,
        side: str,
        atr_value: Optional[float] = None,
        symbol: Optional[str] = None,
        order_concept: Optional[str] = None
    ) -> List[float]:
        """TP 가격들을 계산"""
        if self.tp_sl_calc is None:
            raise RuntimeError("TPSLCalculator not initialized")
        return await self.tp_sl_calc.calculate_tp_prices(
            user_id, current_price, settings, side, atr_value, symbol or "", order_concept or ""
        )

    async def get_position_mode(self, user_id: str, symbol: str) -> Tuple[str, str]:
        """포지션 모드 조회"""
        if self.tp_sl_calc is None:
            raise RuntimeError("TPSLCalculator not initialized")
        return await self.tp_sl_calc.get_position_mode(user_id, symbol)

    async def calculate_sl_price(
        self,
        current_price: float,
        side: str,
        settings: dict,
        symbol: Optional[str] = None,
        atr_value: Optional[float] = None
    ) -> Optional[float]:
        """SL 가격 계산"""
        if self.tp_sl_calc is None:
            raise RuntimeError("TPSLCalculator not initialized")
        return await self.tp_sl_calc.calculate_sl_price(
            current_price, side, settings, symbol, atr_value
        )

    #===============================================
    # Delegated Methods - OKX Position Fetcher
    #===============================================

    async def get_user_api_keys(self, user_id: str) -> Dict[str, str]:
        """사용자 API 키 조회"""
        if self.okx_fetcher is None:
            raise RuntimeError("OKXPositionFetcher not initialized")
        return await self.okx_fetcher.get_user_api_keys(user_id)

    async def fetch_with_retry(self, exchange: Any, symbol: str, max_retries: int = 3) -> Optional[list]:
        """재시도 로직이 있는 fetch"""
        if self.okx_fetcher is None:
            raise RuntimeError("OKXPositionFetcher not initialized")
        return await self.okx_fetcher.fetch_with_retry(exchange, symbol, max_retries)

    @staticmethod
    def get_redis_keys(user_id: str, symbol: str, side: str) -> dict:
        """Redis 키 생성"""
        return OKXPositionFetcher.get_redis_keys(user_id, symbol, side)

    async def fetch_okx_position(
        self,
        user_id: str,
        symbol: str,
        side: Optional[str] = None,
        user_settings: Optional[dict] = None,
        debug_entry_number: int = 9
    ) -> dict:
        """OKX 포지션 조회"""
        if self.okx_fetcher is None:
            raise RuntimeError("OKXPositionFetcher not initialized")
        return await self.okx_fetcher.fetch_okx_position(
            user_id, symbol, side or "", user_settings or {}, debug_entry_number
        )

    async def get_position_avg_price(self, user_id: str, symbol: str, side: str) -> float:
        """포지션 평균가 조회"""
        if self.okx_fetcher is None:
            raise RuntimeError("OKXPositionFetcher not initialized")
        return await self.okx_fetcher.get_position_avg_price(user_id, symbol, side)

    #===============================================
    # Delegated Methods - Market Data Service
    #===============================================

    async def get_atr_value(self, symbol: str, timeframe: str = "1m", current_price: Optional[float] = None) -> float:
        """ATR 값 조회"""
        if self.market_data is None:
            raise RuntimeError("MarketDataService not initialized")
        return await self.market_data.get_atr_value(symbol, timeframe, current_price or 0.0)

    async def get_historical_prices(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """과거 가격 데이터 조회"""
        if self.market_data is None:
            raise RuntimeError("MarketDataService not initialized")
        return await self.market_data.get_historical_prices(symbol, timeframe, limit)

    async def check_rsi_signals(self, rsi_values: list, rsi_settings: dict) -> dict:
        """RSI 시그널 체크"""
        if self.market_data is None:
            raise RuntimeError("MarketDataService not initialized")
        return await self.market_data.check_rsi_signals(rsi_values, rsi_settings)

    async def get_contract_info(
        self,
        symbol: str,
        user_id: Optional[str] = None,
        size_usdt: Optional[float] = None,
        leverage: Optional[float] = None,
        current_price: Optional[float] = None
    ) -> dict:
        """계약 정보 조회"""
        if self.market_data is None:
            raise RuntimeError("MarketDataService not initialized")
        return await self.market_data.get_contract_info(symbol, user_id or "", size_usdt or 0.0, leverage or 0.0, current_price)

    async def get_current_price(self, symbol: str, timeframe: str = "1m") -> float:
        """현재 가격 조회"""
        if self.market_data is None:
            raise RuntimeError("MarketDataService not initialized")
        return await self.market_data.get_current_price(symbol, timeframe)

    # Alias for backward compatibility
    async def _get_current_price(self, symbol: str, timeframe: str = "1m") -> float:
        """현재 가격 조회 (별칭)"""
        if self.market_data is None:
            raise RuntimeError("MarketDataService not initialized")
        return await self.market_data.get_current_price(symbol, timeframe)

    #===============================================
    # Delegated Methods - Order Manager
    #===============================================

    async def cleanup(self) -> None:
        """리소스 정리"""
        if self.order_manager is None:
            logger.debug("OrderManager not initialized, skipping cleanup")
            return
        await self.order_manager.cleanup()

    async def _cancel_order(
        self,
        user_id: str,
        symbol: str,
        order_id: Optional[str] = None,
        order_type: str = "conditional",
        algo_id: Optional[str] = None
    ) -> Any:
        """주문 취소"""
        if self.order_manager is None:
            raise RuntimeError("OrderManager not initialized")
        return await self.order_manager._cancel_order(user_id, symbol, order_id or "", order_type, algo_id or "")

    async def cancel_all_open_orders(self, exchange: Any, symbol: str, user_id: str, side: Optional[str] = None) -> Any:
        """모든 미체결 주문 취소"""
        if self.order_manager is None:
            raise RuntimeError("OrderManager not initialized")
        return await self.order_manager.cancel_all_open_orders(exchange, symbol, user_id, side or "")

    async def _try_send_order(
        self,
        user_id: str,
        symbol: str,
        side: str,
        size: float,
        order_type: str = "market",
        price: Optional[float] = None,
        pos_side: Optional[str] = None,
        params: Optional[dict] = None,
        max_retry: int = 3,
        leverage: Optional[float] = None,
        is_DCA: bool = False
    ) -> OrderStatus:
        """주문 전송 시도"""
        if self.order_manager is None:
            raise RuntimeError("OrderManager not initialized")
        # OrderManager._try_send_order expects: user_id, symbol, side, size, leverage, order_type, price, trigger_price, direction
        return await self.order_manager._try_send_order(
            user_id=user_id,
            symbol=symbol,
            side=side,
            size=size,
            leverage=leverage or 10.0,
            order_type=order_type,
            price=price or 0.0,
            trigger_price=0.0,
            direction=pos_side
        )

    async def _store_order_in_redis(self, user_id: str, order_state: OrderStatus) -> None:
        """주문 정보 Redis 저장"""
        if self.order_manager is None:
            raise RuntimeError("OrderManager not initialized")
        await self.order_manager._store_order_in_redis(user_id, order_state)

    async def monitor_orders(self, user_id: str) -> Any:
        """주문 모니터링"""
        if self.order_manager is None:
            raise RuntimeError("OrderManager not initialized")
        return await self.order_manager.monitor_orders(user_id)

    async def close(self) -> None:
        """서비스 종료"""
        if self.order_manager is None:
            raise RuntimeError("OrderManager not initialized")
        await self.order_manager.close()

    async def get_order_status(self, *, user_id: str, order_id: str, symbol: str) -> dict:
        """주문 상태 조회"""
        if self.order_manager is None:
            raise RuntimeError("OrderManager not initialized")
        return await self.order_manager.get_order_status(user_id=user_id, order_id=order_id, symbol=symbol)

    async def get_order_info(
        self,
        user_id: str,
        symbol: str,
        order_id: str,
        is_algo: bool = False,
        exchange: Optional[ccxt.Exchange] = None
    ) -> dict:
        """주문 정보 조회"""
        if self.order_manager is None:
            raise RuntimeError("OrderManager not initialized")
        return await self.order_manager.get_order_info(user_id, symbol, order_id, is_algo, exchange)

    #===============================================
    # Delegated Methods - TP/SL Order Creator
    #===============================================

    async def _create_tp_sl_orders(
        self,
        user_id: str,
        symbol: str,
        position: Position,
        contracts_amount: float,
        side: str,
        is_DCA: bool = False,
        atr_value: Optional[float] = None,
        current_price: Optional[float] = None,
        is_hedge: bool = False,
        hedge_tp_price: Optional[float] = None,
        hedge_sl_price: Optional[float] = None,
    ) -> None:
        """TP/SL 주문 생성"""
        if self.tp_sl_creator is None:
            raise RuntimeError("TPSLOrderCreator not initialized")
        await self.tp_sl_creator._create_tp_sl_orders(
            user_id, symbol, position, contracts_amount, side,
            is_DCA, atr_value or 0.0, current_price or 0.0, is_hedge,
            hedge_tp_price, hedge_sl_price
        )

    #===============================================
    # Enhanced Methods - Parallel Execution
    #===============================================

    async def get_complete_trading_state(
        self,
        user_id: str,
        symbol: str,
        timeout: float = 10.0
    ) -> Dict[str, Any]:
        """
        모든 거래 상태를 병렬로 조회 (개선된 버전)

        TaskGroup을 사용하여 포지션, 주문, 가격을 동시에 가져옵니다.
        순차 실행 대비 약 3배 빠릅니다.

        Args:
            user_id: 사용자 ID
            symbol: 심볼
            timeout: 타임아웃 (초)

        Returns:
            {
                'position': Position | None,
                'open_orders': List[dict],
                'current_price': float,
                'balance': dict,
                'execution_time_ms': float
            }
        """
        start_time = time.time()

        if HAS_TASKGROUP:
            # 병렬 실행 (Python 3.11+)
            try:
                results = await TaskGroupHelper.gather_with_timeout({
                    'position': lambda: self.get_current_position(user_id, symbol),
                    'current_price': lambda: self.get_current_price(symbol),
                    'contract_info': lambda: self.get_contract_info(symbol, user_id)
                }, timeout=timeout, return_exceptions=True)

                # 에러 처리
                if '_errors' in results:
                    logger.warning(f"Some tasks failed: {results['_errors']}")

                execution_time = (time.time() - start_time) * 1000
                results['execution_time_ms'] = execution_time

                logger.info(
                    f"Parallel state fetch completed in {execution_time:.2f}ms",
                    extra={
                        "user_id": user_id,
                        "symbol": symbol,
                        "execution_time_ms": execution_time
                    }
                )

                return results

            except Exception as e:
                logger.error(f"Parallel execution failed: {e}")
                # Fallback to sequential
                logger.info("Falling back to sequential execution")

        # 순차 실행 (fallback or Python < 3.11)
        position = await self.get_current_position(user_id, symbol)
        current_price = await self.get_current_price(symbol)
        contract_info = await self.get_contract_info(symbol, user_id)

        execution_time = (time.time() - start_time) * 1000

        return {
            'position': position,
            'current_price': current_price,
            'contract_info': contract_info,
            'execution_time_ms': execution_time,
            'method': 'sequential'
        }

    async def batch_fetch_positions(
        self,
        user_id: str,
        symbols: List[str],
        max_concurrency: int = 10
    ) -> Dict[str, Optional[Position]]:
        """
        여러 심볼의 포지션을 병렬로 조회 (개선된 버전)

        Args:
            user_id: 사용자 ID
            symbols: 심볼 리스트
            max_concurrency: 최대 동시 실행 수

        Returns:
            {symbol: Position | None}
        """
        if HAS_TASKGROUP:
            try:
                position_list = await TaskGroupHelper.map_concurrent(
                    symbols,
                    lambda sym: self.get_current_position(user_id, sym),
                    max_concurrency=max_concurrency
                )
                return dict(zip(symbols, position_list))
            except Exception as e:
                logger.error(f"Batch position fetch failed: {e}")
                # Fallback to sequential

        # Sequential fallback
        result: Dict[str, Optional[Position]] = {}
        for symbol in symbols:
            try:
                result[symbol] = await self.get_current_position(user_id, symbol)
            except Exception as e:
                logger.error(f"Failed to fetch position for {symbol}: {e}")
                result[symbol] = None

        return result
