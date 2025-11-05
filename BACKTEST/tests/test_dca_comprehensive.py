"""
Comprehensive DCA integration tests using mock data.

Tests all DCA configurations and conditions without requiring TimescaleDB.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

from BACKTEST.engine.backtest_engine import BacktestEngine
from BACKTEST.models.candle import Candle
from BACKTEST.models.trade import TradeSide
from BACKTEST.data.data_provider import DataProvider


class MockDataProvider(DataProvider):
    """Mock data provider with configurable price movement."""

    def __init__(self, drop_percent=3.0, num_candles=20):
        """
        Initialize mock provider.

        Args:
            drop_percent: Percent price drops per candle (for DCA triggering)
            num_candles: Total number of candles to generate
        """
        self.drop_percent = drop_percent
        self.num_candles = num_candles

    async def validate_data_availability(self, symbol, timeframe, start_date, end_date):
        return {
            "available": True,
            "coverage": 1.0,
            "missing_periods": [],
            "data_source": "mock"
        }

    async def get_candles(self, symbol, timeframe, start_date, end_date, limit=None):
        """Generate mock candles with controlled price movement."""
        candles = []
        current = start_date
        price = 100.0
        count = 0

        num_to_generate = min(self.num_candles, limit) if limit else self.num_candles

        while count < num_to_generate:
            # Price drops for first 10 candles, then stabilizes
            if count < 10:
                price = price * (1 - self.drop_percent / 100)
            else:
                price = price * 1.001  # Slight recovery

            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=current,
                open=price * 1.01,
                high=price * 1.02,
                low=price * 0.98,
                close=price,
                volume=1000.0,
                rsi=25.0 if count < 10 else 35.0,
                atr=price * 0.02,
                sma=price * 1.05,
                ema=price * 1.10
            )

            candles.append(candle)
            current += timedelta(minutes=15)
            count += 1

        return candles

    async def get_candles_df(self, symbol, timeframe, start_date, end_date, limit=None):
        import pandas as pd
        return pd.DataFrame()

    async def get_latest_timestamp(self, symbol, timeframe):
        return datetime.now()


class MockStrategyExecutor:
    """Mock strategy executor for testing."""

    def __init__(self, params):
        self.params = params
        self.entry_generated = False

    def generate_signal(self, candle):
        """Generate entry signal on first candle only."""
        signal = Mock()
        if not self.entry_generated and candle.close > 95:
            signal.side = TradeSide.LONG
            signal.reason = "test_entry"
            signal.indicators = {
                "rsi": getattr(candle, 'rsi', 30),
                "atr": getattr(candle, 'atr', 2.0)
            }
            self.entry_generated = True
        else:
            signal.side = None
        return signal

    def calculate_position_size(self, signal, balance, price):
        investment_pct = self.params.get('investment', 10)
        leverage = self.params.get('leverage', 10)
        investment = balance * (investment_pct / 100)
        quantity = (investment * leverage) / price
        return quantity, leverage

    def calculate_tp_sl(self, side, entry_price, candle):
        tp_pct = self.params.get('take_profit_percent', 10.0)
        sl_pct = self.params.get('stop_loss_percent', 5.0)
        if side == TradeSide.LONG:
            tp = entry_price * (1 + tp_pct / 100)
            sl = entry_price * (1 - sl_pct / 100)
        else:
            tp = entry_price * (1 - tp_pct / 100)
            sl = entry_price * (1 + sl_pct / 100)
        return tp, sl

    def should_activate_trailing_stop(self, pnl_percent):
        return False

    def get_trailing_stop_params(self, candle):
        return 2.0, None, None


@pytest.mark.asyncio
class TestDCAComprehensive:
    """Comprehensive DCA test suite."""

    async def test_percentage_based_dca_long(self):
        """Test percentage-based DCA calculation (퍼센트 기준)."""
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
            'investment': 10,
            'leverage': 10,
            'stop_loss_percent': 5.0,
            'take_profit_percent': 10.0
        }

        result = await self._run_backtest(params)

        # Verify DCA entries exist
        trades_with_dca = [t for t in result.trades if t.dca_count > 0]
        assert len(trades_with_dca) > 0, "Should have trades with DCA"

    async def test_entry_criterion_average(self):
        """Test DCA levels from average price (평균 단가)."""
        params = {
            'pyramiding_enabled': True,
            'pyramiding_limit': 3,
            'entry_multiplier': 0.5,
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'entry_criterion': '평균 단가',
            'use_check_DCA_with_price': True,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(params)
        assert len(result.trades) > 0

    async def test_entry_criterion_recent(self):
        """Test DCA levels from recent price (최근 진입가)."""
        params = {
            'pyramiding_enabled': True,
            'pyramiding_limit': 3,
            'entry_multiplier': 0.5,
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'entry_criterion': '최근 진입가',
            'use_check_DCA_with_price': True,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(params)
        assert len(result.trades) > 0

    async def test_pyramiding_limit_respected(self):
        """Test pyramiding limit is enforced."""
        params = {
            'pyramiding_enabled': True,
            'pyramiding_limit': 2,
            'entry_multiplier': 0.5,
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'use_check_DCA_with_price': True,
            'use_rsi_with_pyramiding': False,
            'use_trend_logic': False,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(params, drop_percent=3.0, num_candles=30)

        # No trade should exceed limit
        for trade in result.trades:
            assert trade.dca_count <= 2, \
                f"Trade exceeded limit: {trade.dca_count}"

    async def test_entry_size_scaling(self):
        """Test entry sizes follow exponential scaling."""
        params = {
            'pyramiding_enabled': True,
            'pyramiding_limit': 3,
            'entry_multiplier': 0.5,
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'use_check_DCA_with_price': True,
            'use_rsi_with_pyramiding': False,
            'use_trend_logic': False,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(params)

        # Find trade with DCA
        for trade in result.trades:
            if trade.dca_count >= 2:
                entries = trade.entry_history

                # Check investment scaling
                initial_investment = entries[0]['investment']
                for i in range(1, len(entries)):
                    expected = initial_investment * (0.5 ** i)
                    actual = entries[i]['investment']
                    ratio = actual / expected

                    assert 0.95 < ratio < 1.05, \
                        f"Scaling error: expected={expected:.2f}, actual={actual:.2f}"
                break

    async def test_rsi_condition_blocks_dca(self):
        """Test RSI condition blocks DCA when not oversold."""
        # With RSI check (should have fewer DCA)
        params_with_rsi = {
            'pyramiding_enabled': True,
            'pyramiding_limit': 5,
            'use_rsi_with_pyramiding': True,
            'rsi_oversold': 30,
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'use_check_DCA_with_price': True,
            'investment': 10,
            'leverage': 10
        }

        # Without RSI check (should have more DCA)
        params_without_rsi = params_with_rsi.copy()
        params_without_rsi['use_rsi_with_pyramiding'] = False

        result_with = await self._run_backtest(params_with_rsi)
        result_without = await self._run_backtest(params_without_rsi)

        total_dca_with = sum(t.dca_count for t in result_with.trades)
        total_dca_without = sum(t.dca_count for t in result_without.trades)

        # Without RSI should have same or more DCA
        assert total_dca_without >= total_dca_with, \
            f"RSI should limit DCA: with={total_dca_with}, without={total_dca_without}"

    async def test_trend_condition_blocks_dca(self):
        """Test trend condition blocks DCA in strong downtrend."""
        params_with_trend = {
            'pyramiding_enabled': True,
            'pyramiding_limit': 5,
            'use_trend_logic': True,
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'use_check_DCA_with_price': True,
            'investment': 10,
            'leverage': 10
        }

        params_without_trend = params_with_trend.copy()
        params_without_trend['use_trend_logic'] = False

        result_with = await self._run_backtest(params_with_trend)
        result_without = await self._run_backtest(params_without_trend)

        total_dca_with = sum(t.dca_count for t in result_with.trades)
        total_dca_without = sum(t.dca_count for t in result_without.trades)

        assert total_dca_without >= total_dca_with, \
            f"Trend should limit DCA: with={total_dca_with}, without={total_dca_without}"

    async def test_average_price_accuracy(self):
        """Test average price calculated correctly."""
        params = {
            'pyramiding_enabled': True,
            'pyramiding_limit': 3,
            'entry_multiplier': 0.5,
            'use_check_DCA_with_price': True,
            'use_rsi_with_pyramiding': False,
            'use_trend_logic': False,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(params)

        # Find trade with DCA
        for trade in result.trades:
            if trade.dca_count > 0:
                entries = trade.entry_history

                # Calculate expected average
                total_cost = sum(e['price'] * e['quantity'] for e in entries)
                total_qty = sum(e['quantity'] for e in entries)
                expected_avg = total_cost / total_qty

                # Compare with actual
                actual_avg = trade.entry_price
                error_pct = abs(actual_avg - expected_avg) / expected_avg * 100

                assert error_pct < 0.1, \
                    f"Average price error: expected={expected_avg:.2f}, actual={actual_avg:.2f}, error={error_pct:.3f}%"
                break

    async def test_total_investment_tracking(self):
        """Test total investment equals sum of entries."""
        params = {
            'pyramiding_enabled': True,
            'pyramiding_limit': 3,
            'entry_multiplier': 0.5,
            'use_check_DCA_with_price': True,
            'use_rsi_with_pyramiding': False,
            'use_trend_logic': False,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(params)

        for trade in result.trades:
            if trade.dca_count > 0:
                entries = trade.entry_history
                expected_total = sum(e['investment'] for e in entries)
                actual_total = trade.total_investment

                assert abs(expected_total - actual_total) < 0.01, \
                    f"Investment mismatch: expected={expected_total}, actual={actual_total}"

    async def test_dca_disabled_works(self):
        """Test DCA disabled mode works correctly."""
        params = {
            'pyramiding_enabled': False,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(params)

        # All trades should have dca_count=0
        for trade in result.trades:
            assert trade.dca_count == 0, "DCA should be disabled"
            assert len(trade.entry_history) == 1, "Should have only initial entry"

    # Helper method
    async def _run_backtest(self, params, drop_percent=3.0, num_candles=20):
        """Run backtest with given parameters."""
        strategy_executor = MockStrategyExecutor(params)
        data_provider = MockDataProvider(drop_percent=drop_percent, num_candles=num_candles)

        engine = BacktestEngine(
            data_provider=data_provider,
            initial_balance=10000.0,
            fee_rate=0.0005,
            slippage_percent=0.05
        )

        result = await engine.run(
            user_id=uuid4(),
            symbol='BTCUSDT',
            timeframe='15m',
            start_date=datetime(2025, 10, 1),
            end_date=datetime(2025, 10, 2),
            strategy_name='test_strategy',
            strategy_params=params,
            strategy_executor=strategy_executor
        )

        return result


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
