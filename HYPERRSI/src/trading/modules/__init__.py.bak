# HYPERRSI/src/trading/modules/__init__.py
"""
Trading Service Modules

Modularized trading service components:
- trading_utils: Standalone utility functions
- market_data_service: Market data and indicators
- tp_sl_calculator: TP/SL price calculation
- okx_position_fetcher: OKX position management
- order_manager: Order lifecycle management
- tp_sl_order_creator: TP/SL order creation
- position_manager: Position open/close operations
"""

# Standalone utility functions
from HYPERRSI.src.trading.modules.trading_utils import (
    get_decimal_places,
    init_user_position_data
)

# Service classes
from HYPERRSI.src.trading.modules.market_data_service import MarketDataService
from HYPERRSI.src.trading.modules.tp_sl_calculator import TPSLCalculator
from HYPERRSI.src.trading.modules.okx_position_fetcher import OKXPositionFetcher
from HYPERRSI.src.trading.modules.order_manager import OrderManager
from HYPERRSI.src.trading.modules.tp_sl_order_creator import TPSLOrderCreator
from HYPERRSI.src.trading.modules.position_manager import PositionManager

__all__ = [
    # Utility functions
    'get_decimal_places',
    'init_user_position_data',
    # Service classes
    'MarketDataService',
    'TPSLCalculator',
    'OKXPositionFetcher',
    'OrderManager',
    'TPSLOrderCreator',
    'PositionManager',
]
