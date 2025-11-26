#!/usr/bin/env python3
"""
미청산 포지션 버그 재현 및 디버깅
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

from BACKTEST.engine import BacktestEngine
from BACKTEST.data import TimescaleProvider  # TimescaleDB 사용 (프론트엔드와 동일)
from BACKTEST.strategies import HyperrsiStrategy
from shared.logging import get_logger

logger = get_logger(__name__)


async def main():
    print("=" * 80)
    print("🔍 미청산 포지션 버그 디버깅")
    print("=" * 80)
    print()

    # 프론트엔드와 동일한 파라미터
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
        "use_trend_close": False,  # ← 메인 트렌드 청산 비활성화
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

    print("📋 핵심 설정:")
    print(f"  - 메인 트렌드 청산: {strategy_params['use_trend_close']}")
    print(f"  - 헤지 트렌드 청산: {strategy_params['dual_side_trend_close']}")
    print(f"  - 브레이크이븐: {strategy_params['use_break_even']}")
    print(f"  - SL 활성화: {strategy_params['stop_loss_enabled']}")
    print(f"  - Trailing stop: {strategy_params['use_trailing_stop']}")
    print()

    # TimescaleDB로 데이터 가져오기 (프론트엔드와 동일)
    data_provider = TimescaleProvider()

    try:
        # BacktestEngine 생성 (프론트엔드와 동일한 파라미터)
        # Note: 프론트엔드는 maker_fee 0.02%, taker_fee 0.05%를 보내지만
        # BacktestEngine은 단일 fee_rate만 지원하므로 taker_fee 사용
        engine = BacktestEngine(
            data_provider=data_provider,
            initial_balance=10000.0,
            fee_rate=0.0005,  # 0.05% (taker fee)
            slippage_percent=0.05
        )

        # Strategy 생성
        strategy = HyperrsiStrategy(strategy_params)
        strategy.validate_params()

        # 백테스트 실행 (11월 4일부터 11월 24일까지 - 프론트엔드와 동일)
        start_date = datetime(2025, 11, 4, 0, 0, 0, tzinfo=timezone.utc)
        end_date = datetime(2025, 11, 24, 23, 59, 59, tzinfo=timezone.utc)

        print(f"📅 기간: {start_date.date()} ~ {end_date.date()}")
        print(f"🪙  심볼: BTC-USDT-SWAP (5m)")
        print()
        print("🚀 백테스트 실행 중... (TimescaleDB에서 데이터 로드)")
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

        print("=" * 80)
        print("📊 백테스트 결과")
        print("=" * 80)
        print(f"총 거래: {result.total_trades}")
        print(f"수익률: {result.total_return:.2f}%")
        print(f"최종 잔고: ${result.final_balance:.2f}")
        print()

        # 🔍 미청산 포지션 체크
        trades = result.trades
        unclosed_trades = [t for t in trades if t.exit_timestamp is None]

        # 첫 진입 확인
        if trades:
            first_trade = trades[0]
            print("=" * 80)
            print("🎯 첫 진입 정보")
            print("=" * 80)
            print(f"Trade #{first_trade.trade_number}")
            print(f"  진입 시간: {first_trade.entry_timestamp}")
            print(f"  Side: {first_trade.side.value}")
            print(f"  Entry: {first_trade.entry_price:.2f}")
            print(f"  Quantity: {first_trade.quantity:.6f}")
            print(f"  Entry reason: {first_trade.entry_reason}")
            if first_trade.exit_timestamp:
                print(f"  Exit: {first_trade.exit_price:.2f} @ {first_trade.exit_timestamp}")
                print(f"  Exit reason: {first_trade.exit_reason}")
            else:
                print(f"  ⚠️ 미청산!")
            print()

            # 마지막 진입 확인
            last_trade = trades[-1]
            print("=" * 80)
            print("🏁 마지막 진입 정보")
            print("=" * 80)
            print(f"Trade #{last_trade.trade_number}")
            print(f"  진입 시간: {last_trade.entry_timestamp}")
            print(f"  Side: {last_trade.side.value}")
            print(f"  Entry: {last_trade.entry_price:.2f}")
            print(f"  Quantity: {last_trade.quantity:.6f}")
            print(f"  Entry reason: {last_trade.entry_reason}")
            if last_trade.exit_timestamp:
                print(f"  Exit: {last_trade.exit_price:.2f} @ {last_trade.exit_timestamp}")
                print(f"  Exit reason: {last_trade.exit_reason}")
            else:
                print(f"  ⚠️ 미청산!")
            print()

        if unclosed_trades:
            print("=" * 80)
            print("🚨 미청산 포지션 발견!")
            print("=" * 80)
            for trade in unclosed_trades:
                print(f"\nTrade #{trade.trade_number}:")
                print(f"  Side: {trade.side.value}")
                print(f"  Entry: {trade.entry_price:.2f} @ {trade.entry_timestamp}")
                print(f"  Quantity: {trade.quantity:.6f}")
                print(f"  Entry reason: {trade.entry_reason}")
                print(f"  DCA count: {trade.dca_count}")
                print(f"  Is dual-side: {trade.is_dual_side}")
                print(f"  Stop loss: {trade.stop_loss_price}")
                print(f"  Take profit: {trade.take_profit_price}")
                print(f"  Trailing stop: {trade.trailing_stop_price}")
                print(f"  TP1/TP2/TP3: {trade.tp1_price} / {trade.tp2_price} / {trade.tp3_price}")

                # 현재 가격 확인
                last_candle_price = result.equity_curve[-1]['price'] if result.equity_curve else None
                if last_candle_price:
                    print(f"\n  📊 마지막 가격: {last_candle_price:.2f}")

                    # SL 도달 여부
                    if trade.stop_loss_price:
                        if trade.side.value == "long":
                            sl_hit = last_candle_price <= trade.stop_loss_price
                        else:
                            sl_hit = last_candle_price >= trade.stop_loss_price

                        print(f"  ⚠️ SL 도달 여부: {sl_hit}")
                        if sl_hit:
                            print(f"  🚨 버그 확인: SL 도달했는데 청산 안 됨!")

            print()
            print(f"🚨 총 {len(unclosed_trades)}개의 미청산 포지션 발견!")
            print()

        else:
            print("=" * 80)
            print("✅ 모든 포지션 정상 청산됨")
            print("=" * 80)
            print()

        # 마지막 5개 거래 출력
        print("=" * 80)
        print("📋 마지막 5개 거래")
        print("=" * 80)
        for trade in trades[-5:]:
            exit_status = "OPEN" if trade.exit_timestamp is None else "CLOSED"
            print(f"Trade #{trade.trade_number}: {trade.side.value} {exit_status}")
            print(f"  Qty: {trade.quantity:.6f}, Exit: {trade.exit_reason if trade.exit_reason else 'N/A'}")

        # 저장
        import json
        with open('unclosed_debug_result.json', 'w') as f:
            json.dump(result.model_dump(by_alias=True), f, indent=2, ensure_ascii=False, default=str)
        print()
        print("💾 결과 저장: unclosed_debug_result.json")

    except Exception as e:
        logger.error(f"백테스트 실패: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await data_provider.close()


if __name__ == "__main__":
    asyncio.run(main())
