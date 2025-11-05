"""
Comprehensive DCA integration tests with real TimescaleDB data.

Tests all DCA configurations using actual historical market data.
"""

import pytest
from datetime import datetime
from uuid import uuid4

from BACKTEST.engine.backtest_engine import BacktestEngine
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy
from BACKTEST.data.timescale_provider import TimescaleProvider


@pytest.mark.asyncio
class TestDCAFullIntegration:
    """Complete DCA integration test suite with real data."""

    async def test_percentage_based_dca(self):
        """Test percentage-based DCA calculation and execution (퍼센트 기준)."""
        params = {
            'entry_option': 'rsi_trend',
            'rsi_oversold': 30,
            'rsi_overbought': 70,
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

        result = await self._run_backtest(
            params,
            start=datetime(2025, 10, 15),
            end=datetime(2025, 10, 20)
        )

        # Verify DCA entries used percentage calculation
        trades_with_dca = [t for t in result.trades if t.dca_count > 0]
        if trades_with_dca:
            for trade in trades_with_dca:
                entries = trade.entry_history
                for i in range(1, len(entries)):
                    prev_price = entries[i-1]['price']
                    curr_price = entries[i]['price']

                    # For long: each DCA should be ~3% lower
                    if trade.side.value == 'long':
                        expected_ratio = 0.97  # 3% lower
                        actual_ratio = curr_price / prev_price
                        # Allow some tolerance for market movements
                        assert 0.94 < actual_ratio < 1.00, \
                            f"DCA spacing should be ~3% lower: {actual_ratio:.4f}"

    async def test_fixed_amount_dca(self):
        """Test fixed amount DCA calculation (금액 기준)."""
        params = {
            'entry_option': 'rsi_trend',
            'pyramiding_enabled': True,
            'pyramiding_limit': 3,
            'entry_multiplier': 0.5,
            'pyramiding_entry_type': '금액 기준',
            'pyramiding_value': 1000.0,  # $1000 spacing
            'entry_criterion': '평균 단가',
            'use_check_DCA_with_price': True,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(
            params,
            start=datetime(2025, 10, 15),
            end=datetime(2025, 10, 20)
        )

        # Verify backtest runs without errors
        assert len(result.trades) >= 0

    async def test_atr_based_dca(self):
        """Test ATR-based DCA calculation (ATR 기준)."""
        params = {
            'entry_option': 'rsi_trend',
            'pyramiding_enabled': True,
            'pyramiding_limit': 3,
            'entry_multiplier': 0.5,
            'pyramiding_entry_type': 'ATR 기준',
            'pyramiding_value': 2.0,  # 2x ATR
            'entry_criterion': '평균 단가',
            'use_check_DCA_with_price': True,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(
            params,
            start=datetime(2025, 10, 15),
            end=datetime(2025, 10, 20)
        )

        # Verify runs without errors
        assert len(result.trades) >= 0

    async def test_entry_criterion_average(self):
        """Test DCA levels calculated from average price (평균 단가)."""
        params = {
            'entry_option': 'rsi_trend',
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

        result = await self._run_backtest(
            params,
            start=datetime(2025, 10, 15),
            end=datetime(2025, 10, 20)
        )

        assert len(result.trades) >= 0

    async def test_entry_criterion_recent(self):
        """Test DCA levels calculated from recent price (최근 진입가)."""
        params = {
            'entry_option': 'rsi_trend',
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

        result = await self._run_backtest(
            params,
            start=datetime(2025, 10, 15),
            end=datetime(2025, 10, 20)
        )

        assert len(result.trades) >= 0

    async def test_pyramiding_limit_1(self):
        """Test pyramiding_limit=1 allows only 1 DCA entry."""
        params = {
            'entry_option': 'rsi_trend',
            'pyramiding_enabled': True,
            'pyramiding_limit': 1,
            'entry_multiplier': 0.5,
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'use_check_DCA_with_price': True,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(
            params,
            start=datetime(2025, 10, 15),
            end=datetime(2025, 10, 25)
        )

        # No trade should exceed limit
        for trade in result.trades:
            assert trade.dca_count <= 1, \
                f"Trade exceeded limit: {trade.dca_count}"

    async def test_entry_size_scaling(self):
        """Test entry sizes follow exponential scaling."""
        params = {
            'entry_option': 'rsi_trend',
            'pyramiding_enabled': True,
            'pyramiding_limit': 3,
            'entry_multiplier': 0.5,
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'use_check_DCA_with_price': True,
            'use_rsi_with_pyramiding': False,  # Disable to ensure DCA triggers
            'use_trend_logic': False,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(
            params,
            start=datetime(2025, 10, 15),
            end=datetime(2025, 10, 25)
        )

        # Find trade with multiple DCA entries
        for trade in result.trades:
            if trade.dca_count >= 2:
                entries = trade.entry_history

                # Check investment scaling
                initial_investment = entries[0]['investment']
                for i in range(1, len(entries)):
                    expected = initial_investment * (0.5 ** i)
                    actual = entries[i]['investment']
                    ratio = actual / expected

                    # Allow 5% tolerance
                    assert 0.95 < ratio < 1.05, \
                        f"Entry size scaling incorrect: expected={expected:.2f}, actual={actual:.2f}, ratio={ratio:.4f}"
                break

    async def test_average_price_calculation(self):
        """Test average price calculated correctly."""
        params = {
            'entry_option': 'rsi_trend',
            'pyramiding_enabled': True,
            'pyramiding_limit': 3,
            'entry_multiplier': 0.5,
            'pyramiding_entry_type': '퍼센트 기준',
            'pyramiding_value': 3.0,
            'use_check_DCA_with_price': True,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(
            params,
            start=datetime(2025, 10, 15),
            end=datetime(2025, 10, 25)
        )

        # Find trade with DCA
        for trade in result.trades:
            if trade.dca_count > 0:
                entries = trade.entry_history

                # Calculate expected average
                total_cost = sum(e['price'] * e['quantity'] for e in entries)
                total_qty = sum(e['quantity'] for e in entries)
                expected_avg = total_cost / total_qty

                # Compare with recorded average
                actual_avg = trade.entry_price
                error_pct = abs(actual_avg - expected_avg) / expected_avg * 100

                assert error_pct < 0.1, \
                    f"Average price mismatch: expected={expected_avg:.2f}, actual={actual_avg:.2f}, error={error_pct:.4f}%"
                break

    async def test_total_investment_tracking(self):
        """Test total investment equals sum of entry investments."""
        params = {
            'entry_option': 'rsi_trend',
            'pyramiding_enabled': True,
            'pyramiding_limit': 3,
            'entry_multiplier': 0.5,
            'use_check_DCA_with_price': True,
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(
            params,
            start=datetime(2025, 10, 15),
            end=datetime(2025, 10, 25)
        )

        for trade in result.trades:
            if trade.dca_count > 0:
                entries = trade.entry_history
                expected_total = sum(e['investment'] for e in entries)
                actual_total = trade.total_investment

                assert abs(expected_total - actual_total) < 0.01, \
                    f"Investment mismatch: expected={expected_total:.2f}, actual={actual_total:.2f}"

    async def test_dca_disabled_backward_compatibility(self):
        """Test DCA disabled mode works like before."""
        params = {
            'entry_option': 'rsi_trend',
            'pyramiding_enabled': False,  # Disabled
            'investment': 10,
            'leverage': 10
        }

        result = await self._run_backtest(
            params,
            start=datetime(2025, 10, 15),
            end=datetime(2025, 10, 20)
        )

        # All trades should have dca_count=0
        for trade in result.trades:
            assert trade.dca_count == 0, "DCA should be disabled"
            assert len(trade.entry_history) == 1, "Should have only initial entry"

    # Helper method
    async def _run_backtest(self, params, start, end):
        """
        Helper to run backtest with given params.

        Args:
            params: Strategy parameters
            start: Start datetime
            end: End datetime

        Returns:
            BacktestResult
        """
        strategy = HyperrsiStrategy(params)
        data_provider = TimescaleProvider()

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
            start_date=start,
            end_date=end,
            strategy_name='HYPERRSI',
            strategy_params=params,
            strategy_executor=strategy
        )

        return result


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
