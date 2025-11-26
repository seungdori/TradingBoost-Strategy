#!/usr/bin/env python3
"""
Nov 13 13:25 진입 포지션의 실제 데이터 확인
"""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from BACKTEST.engine import BacktestEngine
from BACKTEST.data import TimescaleProvider
from BACKTEST.strategies import HyperrsiStrategy
from shared.logging import get_logger

logger = get_logger(__name__)


async def main():
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
        engine = BacktestEngine(
            data_provider=data_provider,
            initial_balance=10000.0,
            fee_rate=0.0005,
            slippage_percent=0.05
        )

        strategy = HyperrsiStrategy(strategy_params)
        strategy.validate_params()

        start_date = datetime(2025, 11, 4, 0, 0, 0, tzinfo=timezone.utc)
        end_date = datetime(2025, 11, 25, 23, 59, 59, tzinfo=timezone.utc)

        print("🚀 백테스트 실행 중...")
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
        print("📊 Nov 13 13:25 근처 진입한 Trade 찾기")
        print("=" * 80)

        # Nov 13 13:00 ~ 14:00 사이에 진입한 trade 찾기
        target_start = datetime(2025, 11, 13, 13, 0, 0, tzinfo=timezone.utc)
        target_end = datetime(2025, 11, 13, 14, 0, 0, tzinfo=timezone.utc)

        matching_trades = []
        for trade in result.trades:
            if target_start <= trade.entry_timestamp <= target_end:
                matching_trades.append(trade)

        if not matching_trades:
            print("⚠️ Nov 13 13:00~14:00 사이 진입 trade를 찾을 수 없습니다!")
            print()
            print("실제 진입 시간들:")
            for i, trade in enumerate(result.trades[:10], 1):
                print(f"  Trade #{i}: {trade.entry_timestamp}")
        else:
            for trade in matching_trades:
                print(f"\n🎯 Trade #{trade.trade_number}")
                print(f"   진입 시간: {trade.entry_timestamp}")
                print(f"   Side: {trade.side.value}")
                print(f"   Entry price: {trade.entry_price:.2f}")
                print(f"   Quantity: {trade.quantity:.6f}")
                print(f"   Exit time: {trade.exit_timestamp}")
                print(f"   Exit price: {trade.exit_price:.2f if trade.exit_price else 'N/A'}")
                print(f"   Exit reason: {trade.exit_reason.value if trade.exit_reason else 'N/A'}")
                print(f"   PNL: {trade.pnl:.2f}")
                print(f"   DCA count: {trade.dca_count}")

                # Entry history 확인
                if hasattr(trade, 'entry_history') and trade.entry_history:
                    print(f"\n   📝 Entry History ({len(trade.entry_history)}개):")
                    for i, entry in enumerate(trade.entry_history, 1):
                        print(f"      #{i}: {entry['timestamp']} @ {entry['price']:.2f}, qty={entry['quantity']:.6f}")

                # Partial exit history 확인
                if hasattr(trade, 'partial_exits') and trade.partial_exits:
                    print(f"\n   📤 Partial Exits ({len(trade.partial_exits)}개):")
                    for i, exit_data in enumerate(trade.partial_exits, 1):
                        print(f"      #{i}: {exit_data['timestamp']} @ {exit_data['price']:.2f}, qty={exit_data['quantity']:.6f}, reason={exit_data['reason']}")

        # 마지막 trade (미청산 포지션) 정보
        print()
        print("=" * 80)
        print("🚨 미청산 포지션 (마지막 진입)")
        print("=" * 80)

        if engine.position_manager.has_position():
            position = engine.position_manager.get_position()
            print(f"Entry time: {position.entry_timestamp}")
            print(f"Entry price: {position.entry_price:.2f} (average)")
            print(f"Current qty: {position.quantity:.6f}")
            print(f"DCA count: {position.dca_count}")
            print(f"TP1 price: {position.tp1_price:.2f if position.tp1_price else 'None'}")
            print(f"TP2 price: {position.tp2_price:.2f if position.tp2_price else 'None'}")
            print(f"TP3 price: {position.tp3_price:.2f if position.tp3_price else 'None'}")
            print(f"TP1 filled: {position.tp1_filled}")
            print(f"TP2 filled: {position.tp2_filled}")
            print(f"TP3 filled: {position.tp3_filled}")
            print(f"Stop loss price: {position.stop_loss_price:.2f if position.stop_loss_price else 'None'}")
            print(f"Trailing stop activated: {position.trailing_stop_activated}")
            print(f"Trailing stop price: {position.trailing_stop_price:.2f if position.trailing_stop_price else 'None'}")

            print(f"\n📝 Entry History ({len(position.entry_history)}개):")
            for i, entry in enumerate(position.entry_history, 1):
                print(f"   #{i}: {entry['timestamp']} @ {entry['price']:.2f}, qty={entry['quantity']:.6f}, reason={entry.get('reason', 'initial')}")

            if hasattr(position, 'partial_exits') and position.partial_exits:
                print(f"\n📤 Partial Exits ({len(position.partial_exits)}개):")
                for i, exit_data in enumerate(position.partial_exits, 1):
                    print(f"   #{i}: {exit_data['timestamp']} @ {exit_data['price']:.2f}, qty={exit_data['quantity']:.6f}, reason={exit_data['reason']}")

    except Exception as e:
        logger.error(f"백테스트 실패: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await data_provider.close()


if __name__ == "__main__":
    asyncio.run(main())
