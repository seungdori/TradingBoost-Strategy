"""
Integration tests for backtest engine with DCA.

Tests end-to-end DCA functionality in backtesting engine.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, MagicMock
from uuid import uuid4

from BACKTEST.engine.backtest_engine import BacktestEngine
from BACKTEST.models.candle import Candle
from BACKTEST.models.trade import TradeSide
from BACKTEST.data.data_provider import DataProvider


class MockDataProvider(DataProvider):
    """Mock data provider for testing."""

    async def validate_data_availability(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ):
        """Mock validation."""
        return {
            "available": True,
            "coverage": 1.0,
            "missing_periods": [],
            "data_source": "mock"
        }

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        limit=None
    ):
        """Generate mock candles for testing."""
        candles = []
        current = start_date
        price = 100.0

        while current <= end_date:
            # Simulate price movement with downtrend for DCA
            price = price * 0.97  # 3% drop per candle to trigger DCA

            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=current,
                open=price * 1.01,
                high=price * 1.02,
                low=price * 0.98,
                close=price,
                volume=1000.0,
                # Add indicators for DCA checks
                rsi=25.0,  # Oversold RSI to allow DCA
                atr=price * 0.02,
                sma=price * 1.05,  # Price below SMA (uptrend context)
                ema=price * 1.10
            )

            candles.append(candle)
            current += timedelta(minutes=15)

            if limit and len(candles) >= limit:
                break

        return candles

    async def get_candles_df(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        limit=None
    ):
        """Get candles as DataFrame (not used in tests)."""
        import pandas as pd
        return pd.DataFrame()

    async def get_latest_timestamp(self, symbol: str, timeframe: str):
        """Get latest timestamp (not used in tests)."""
        return datetime.now()


class MockStrategyExecutor:
    """Mock strategy executor for testing."""

    def __init__(self, params):
        self.params = params

    def generate_signal(self, candle):
        """Generate mock signal."""
        signal = Mock()
        # First candle generates LONG signal
        if candle.close > 95:  # Only first candle
            signal.side = TradeSide.LONG
            signal.reason = "test_entry"
            signal.indicators = {
                "rsi": candle.rsi if hasattr(candle, 'rsi') else 30,
                "atr": candle.atr if hasattr(candle, 'atr') else 0.5
            }
        else:
            signal.side = None
        return signal

    def calculate_position_size(self, signal, balance, price):
        """Calculate position size."""
        investment = balance * (self.params.get('investment', 10) / 100)
        leverage = self.params.get('leverage', 10)
        quantity = (investment * leverage) / price
        return quantity, leverage

    def calculate_tp_sl(self, side, entry_price, candle):
        """Calculate TP/SL."""
        if side == TradeSide.LONG:
            tp = entry_price * 1.10  # 10% TP
            sl = entry_price * 0.95  # 5% SL
        else:
            tp = entry_price * 0.90
            sl = entry_price * 1.05
        return tp, sl

    def should_activate_trailing_stop(self, pnl_percent):
        """Check if trailing stop should activate."""
        return False  # Disabled for DCA testing

    def get_trailing_stop_params(self, candle):
        """Get trailing stop parameters."""
        return 2.0, None, None


@pytest.mark.asyncio
class TestBacktestDCAIntegration:
    """Integration tests for DCA in backtest."""

    async def test_backtest_with_dca_enabled(self):
        """Test backtest generates DCA entries."""
        # Setup with DCA enabled
        params = {
            'pyramiding_enabled': True,
            'pyramiding_limit': 3,
            'entry_multiplier': 0.5,
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'entry_criterion': '평균 단가',
            'use_check_DCA_with_price': True,
            'use_rsi_with_pyramiding': True,
            'use_trend_logic': True,
            'investment': 10,  # 10% of balance per entry
            'leverage': 10,
            'rsi_oversold': 30,
            'rsi_overbought': 70,
            'stop_loss_percent': 5.0,
            'take_profit_percent': 10.0
        }

        strategy_executor = MockStrategyExecutor(params)
        data_provider = MockDataProvider()

        engine = BacktestEngine(
            data_provider=data_provider,
            initial_balance=10000.0,
            fee_rate=0.0005,
            slippage_percent=0.05
        )

        # Run backtest
        result = await engine.run(
            user_id=uuid4(),
            symbol='BTCUSDT',
            timeframe='15m',
            start_date=datetime(2025, 10, 1),
            end_date=datetime(2025, 10, 1, 2, 0),  # 2 hours = 8 candles
            strategy_name='test_strategy',
            strategy_params=params,
            strategy_executor=strategy_executor
        )

        # Verify trades exist
        trades = result.trades
        assert len(trades) > 0, "Should have trades"

        # Check if any trade has DCA entries
        has_dca = any(trade.dca_count > 0 for trade in trades)
        assert has_dca, "Should have at least one trade with DCA entries"

        # Verify DCA metadata
        for trade in trades:
            assert hasattr(trade, 'dca_count')
            assert hasattr(trade, 'entry_history')
            assert hasattr(trade, 'total_investment')

            if trade.dca_count > 0:
                # Should have multiple entries
                assert len(trade.entry_history) > 1
                # Total investment should be sum of all entries
                expected_investment = sum(
                    e['investment'] for e in trade.entry_history
                )
                assert trade.total_investment == pytest.approx(
                    expected_investment, rel=1e-6
                )

    async def test_backtest_with_dca_disabled(self):
        """Test backtest with DCA disabled works like before."""
        params = {
            'pyramiding_enabled': False,  # Disabled
            'investment': 10,
            'leverage': 10
        }

        strategy_executor = MockStrategyExecutor(params)
        data_provider = MockDataProvider()

        engine = BacktestEngine(
            data_provider=data_provider,
            initial_balance=10000.0
        )

        result = await engine.run(
            user_id=uuid4(),
            symbol='BTCUSDT',
            timeframe='15m',
            start_date=datetime(2025, 10, 1),
            end_date=datetime(2025, 10, 1, 1, 0),  # 1 hour
            strategy_name='test_strategy',
            strategy_params=params,
            strategy_executor=strategy_executor
        )

        # All trades should have dca_count=0
        for trade in result.trades:
            assert trade.dca_count == 0
            assert len(trade.entry_history) == 1  # Only initial entry

    async def test_dca_limit_enforced(self):
        """Test pyramiding_limit is enforced."""
        params = {
            'pyramiding_enabled': True,
            'pyramiding_limit': 2,  # Max 2 DCA entries
            'entry_multiplier': 0.5,
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'use_check_DCA_with_price': True,
            'use_rsi_with_pyramiding': False,  # Disable to ensure DCA triggers
            'use_trend_logic': False,  # Disable to ensure DCA triggers
            'investment': 10,
            'leverage': 10
        }

        strategy_executor = MockStrategyExecutor(params)
        data_provider = MockDataProvider()

        engine = BacktestEngine(
            data_provider=data_provider,
            initial_balance=10000.0
        )

        result = await engine.run(
            user_id=uuid4(),
            symbol='BTCUSDT',
            timeframe='15m',
            start_date=datetime(2025, 10, 1),
            end_date=datetime(2025, 10, 1, 2, 0),
            strategy_name='test_strategy',
            strategy_params=params,
            strategy_executor=strategy_executor
        )

        # No trade should exceed DCA limit
        for trade in result.trades:
            assert trade.dca_count <= 2, f"DCA count {trade.dca_count} exceeds limit 2"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
