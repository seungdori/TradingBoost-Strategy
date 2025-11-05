"""
BACKTEST Configuration

Backtest service configuration settings.
"""

from shared.config import get_settings as get_shared_settings

# Shared settings
settings = get_shared_settings()


class BacktestConfig:
    """Backtest service configuration"""

    # Service settings
    HOST: str = "0.0.0.0"
    PORT: int = 8013

    # Backtest defaults
    DEFAULT_INITIAL_BALANCE: float = 10000.0
    DEFAULT_FEE_RATE: float = 0.0005  # 0.05%
    DEFAULT_SLIPPAGE_PERCENT: float = 0.05  # 0.05%

    # Data settings
    MAX_CANDLES_PER_REQUEST: int = 100000
    DEFAULT_TIMEFRAME: str = "15m"

    # Strategy settings
    AVAILABLE_STRATEGIES: list[str] = ["hyperrsi"]

    # Performance settings
    MAX_CONCURRENT_BACKTESTS: int = 3


# Create singleton instance
backtest_config = BacktestConfig()
