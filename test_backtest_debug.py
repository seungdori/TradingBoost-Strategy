#!/usr/bin/env python3
"""
백테스트 엔진 디버그: 특정 시점에서 시그널 생성 과정 추적
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

from BACKTEST.engine import BacktestEngine
from BACKTEST.data import TimescaleProvider
from BACKTEST.strategies import HyperrsiStrategy
from shared.logging import get_logger

logger = get_logger(__name__)


# 디버그할 시점들
DEBUG_TIMES = [
    datetime(2025, 11, 13, 13, 25, 0, tzinfo=timezone.utc),
    datetime(2025, 11, 14, 4, 30, 0, tzinfo=timezone.utc),
    datetime(2025, 11, 23, 7, 0, 0, tzinfo=timezone.utc),
]


class DebugHyperrsiStrategy(HyperrsiStrategy):
    """디버그 로깅이 추가된 전략"""

    def __init__(self, params: dict):
        super().__init__(params)
        self.signal_call_count = 0
        self.debug_times = DEBUG_TIMES

    async def generate_signal(self, candle):
        """시그널 생성 과정 추적"""
        self.signal_call_count += 1

        # 디버그할 시점인지 확인
        is_debug_time = any(
            abs((candle.timestamp - dt).total_seconds()) < 300  # 5분 이내
            for dt in self.debug_times
        )

        if is_debug_time:
            print(f"\n{'='*80}")
            print(f"🔍 DEBUG: generate_signal() 호출됨")
            print(f"   시간: {candle.timestamp}")
            print(f"   Close: {candle.close}")
            print(f"   RSI: {candle.rsi}")
            print(f"   Trend: {candle.trend_state}")
            print(f"{'='*80}")

        # 원래 로직 실행
        signal = await super().generate_signal(candle)

        if is_debug_time:
            print(f"   ✅ 시그널 결과:")
            print(f"      side: {signal.side}")
            print(f"      reason: {signal.reason}")
            print(f"      indicators: {signal.indicators}")
            print(f"{'='*80}\n")

        return signal


class DebugBacktestEngine(BacktestEngine):
    """디버그 로깅이 추가된 백테스트 엔진"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.debug_times = DEBUG_TIMES

    async def _process_candle(self, candle, strategy_executor):
        """캔들 처리 과정 추적 (_process_candle이 실제 메서드)"""

        # 디버그할 시점인지 확인
        is_debug_time = any(
            abs((candle.timestamp - dt).total_seconds()) < 300  # 5분 이내
            for dt in self.debug_times
        )

        if is_debug_time:
            print(f"\n{'='*80}")
            print(f"🔍 DEBUG: _process_candle() 호출됨")
            print(f"   시간: {candle.timestamp}")
            print(f"   Close: {candle.close}")
            print(f"   has_position: {self.position_manager.has_position()}")
            if self.position_manager.has_position():
                pos = self.position_manager.get_position()
                print(f"   현재 포지션: {pos.side.value}, qty={pos.quantity:.6f}, entry={pos.entry_price:.2f}")
            print(f"{'='*80}")

        # 원래 로직 실행
        result = await super()._process_candle(candle, strategy_executor)

        if is_debug_time:
            print(f"   ✅ _process_candle() 완료")
            print(f"   has_position 이후: {self.position_manager.has_position()}")
            print(f"{'='*80}\n")

        return result


async def main():
    print("=" * 80)
    print("🔍 백테스트 엔진 디버그 모드")
    print("=" * 80)
    print()
    print("디버그할 시점:")
    for dt in DEBUG_TIMES:
        print(f"  - {dt}")
    print()
    print("=" * 80)
    print()

    strategy_params = {
        "rsi_period": 14,
        "rsi_os": 30,
        "rsi_ob": 70,
        "direction": "both",
        "use_trend_filter": True,
        "ema_period": 7,
        "sma_period": 20,
        "entry_option": "rsi_trend",
        "require_trend_confirm": True,
        "use_trend_close": False,
        "use_tp1": True,
        "tp1_percent": 3,
        "tp1_close_percent": 30,
        "use_tp2": True,
        "tp2_percent": 4,
        "tp2_close_percent": 30,
        "use_tp3": True,
        "tp3_percent": 5,
        "tp3_close_percent": 40,
        "use_trailing_stop": True,
        "trailing_stop_percent": 0.5,
        "trailing_activation_percent": 2,
        "use_break_even": True,
        "use_break_even_tp2": True,
        "use_break_even_tp3": True,
        "use_dca": True,
        "dca_max_orders": 8,
        "dca_price_step_percent": 3,
        "dca_size_multiplier": 1,
        "rsi_entry_option": "돌파",
        "leverage": 10,
        "investment": 35,
        "stop_loss_enabled": False,
        "take_profit_enabled": False,
        "take_profit_percent": None,
        "pyramiding_enabled": True,
        "pyramiding_limit": 8,
        "pyramiding_entry_type": "atr",
        "pyramiding_value": 3,
        "use_rsi_with_pyramiding": True,
        "use_trend_logic": True,
        "trend_timeframe": "1H",
        "tp_option": "atr",
        "tp1_value": 3,
        "tp2_value": 4,
        "tp3_value": 5,
        "tp1_ratio": 30,
        "tp2_ratio": 30,
        "tp3_ratio": 40,
        "trailing_stop_active": True,
        "trailing_start_point": "tp2",
        "trailing_stop_offset_value": 0.5,
        "use_trailing_stop_value_with_tp2_tp3_difference": True,
        "use_dual_side_entry": True,
        "dual_side_entry_trigger": 2,
        "dual_side_entry_ratio_type": "percent_of_position",
        "dual_side_entry_ratio_value": 100,
        "dual_side_entry_tp_trigger_type": "existing_position",
        "close_main_on_hedge_tp": True,
        "use_dual_sl": False,
        "dual_side_pyramiding_limit": 2,
        "dual_side_trend_close": True
    }

    data_provider = TimescaleProvider()

    try:
        # 디버그 엔진 생성
        engine = DebugBacktestEngine(
            data_provider=data_provider,
            initial_balance=10000.0,
            fee_rate=0.0005,
            slippage_percent=0.05
        )

        # 디버그 전략 생성
        strategy = DebugHyperrsiStrategy(strategy_params)
        strategy.validate_params()

        # 백테스트 실행 (11/4 ~ 11/25)
        start_date = datetime(2025, 11, 4, 0, 0, 0, tzinfo=timezone.utc)
        end_date = datetime(2025, 11, 25, 23, 59, 59, tzinfo=timezone.utc)

        print(f"📅 기간: {start_date.date()} ~ {end_date.date()}")
        print(f"🪙  심볼: BTC-USDT-SWAP (5m)")
        print()
        print("🚀 백테스트 실행 중...")
        print()

        result = await engine.run(
            user_id=UUID("00000000-0000-0000-0000-000000000000"),
            symbol="BTC-USDT-SWAP",
            timeframe="5m",
            start_date=start_date,
            end_date=end_date,
            strategy_name="hyperrsi",
            strategy_params=strategy_params,
            strategy_executor=strategy
        )

        print()
        print("=" * 80)
        print("📊 백테스트 결과")
        print("=" * 80)
        print(f"총 거래: {result.total_trades}")
        print(f"수익률: {result.total_return:.2f}%")
        print(f"최종 잔고: ${result.final_balance:.2f}")
        print(f"generate_signal() 호출 횟수: {strategy.signal_call_count}")
        print()

    except Exception as e:
        logger.error(f"백테스트 실패: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await data_provider.close()


if __name__ == "__main__":
    asyncio.run(main())
