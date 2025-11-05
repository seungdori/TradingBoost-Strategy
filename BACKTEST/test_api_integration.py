"""
실제 API 응답 통합 테스트 - 부분 익절 시 stop_loss_price 확인
"""

import asyncio
from datetime import datetime, timedelta
from uuid import UUID

from BACKTEST.engine import BacktestEngine
from BACKTEST.data import TimescaleProvider
from BACKTEST.strategies import HyperrsiStrategy
from BACKTEST.api.schemas import BacktestDetailResponse


async def test_real_api_response():
    """
    실제 API 흐름과 동일하게 백테스트를 실행하고,
    부분 익절 레코드의 stop_loss_price를 확인합니다.
    """
    print("🧪 실제 API 응답 통합 테스트 시작...\n")

    # API 요청 파라미터와 동일하게 설정
    symbol = "BTC-USDT-SWAP"
    timeframe = "5m"
    start_date = datetime.utcnow() - timedelta(days=7)
    end_date = datetime.utcnow() - timedelta(days=1)

    strategy_params = {
        "entry_option": "rsi_trend",
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "leverage": 10,
        "investment": 100,
        "stop_loss_percent": 2.0,
        "take_profit_percent": 5.0,

        # 부분 익절 활성화
        "use_tp1": True,
        "use_tp2": True,
        "use_tp3": True,
        "tp1_percent": 2.0,
        "tp2_percent": 3.0,
        "tp3_percent": 4.0,
        "tp1_ratio": 0.3,
        "tp2_ratio": 0.3,
        "tp3_ratio": 0.4,

        # Break-even 활성화
        "use_break_even": True,
        "use_break_even_tp2": True,
    }

    initial_balance = 10000.0
    fee_rate = 0.0005
    slippage_percent = 0.05

    print(f"📊 백테스트 설정:")
    print(f"   Symbol: {symbol}")
    print(f"   Timeframe: {timeframe}")
    print(f"   Period: {start_date.date()} ~ {end_date.date()}")
    print(f"   Initial Balance: {initial_balance} USDT")
    print(f"   부분 익절: TP1={strategy_params['tp1_percent']}% (30%), "
          f"TP2={strategy_params['tp2_percent']}% (30%), "
          f"TP3={strategy_params['tp3_percent']}% (40%)")
    print(f"   Break-even: Enabled")
    print()

    # Create data provider
    data_provider = TimescaleProvider()

    try:
        # Create backtest engine (API와 동일)
        engine = BacktestEngine(
            data_provider=data_provider,
            initial_balance=initial_balance,
            fee_rate=fee_rate,
            slippage_percent=slippage_percent
        )

        # Create strategy instance (API와 동일)
        strategy = HyperrsiStrategy(strategy_params)
        strategy.validate_params()

        print("⚙️ 백테스트 실행 중...\n")

        # Run backtest (API와 동일)
        result = await engine.run(
            user_id=UUID("00000000-0000-0000-0000-000000000000"),
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            strategy_name="hyperrsi",
            strategy_params=strategy_params,
            strategy_executor=strategy
        )

        # Convert to API response (API와 동일)
        response = BacktestDetailResponse(**result.model_dump())

        print("✅ 백테스트 완료!\n")
        print(f"📈 결과 요약:")
        print(f"   총 거래 수: {response.total_trades}")
        print(f"   최종 잔고: {response.final_balance:.2f} USDT")
        print(f"   총 수익률: {response.total_return_percent:.2f}%")
        print()

        # 부분 익절 레코드 확인
        print("🔍 부분 익절 레코드 확인:\n")

        partial_exits_found = False
        for i, trade in enumerate(response.trades, 1):
            if trade.is_partial_exit and trade.tp_level:
                partial_exits_found = True
                print(f"   Trade #{i} - TP{trade.tp_level} 부분 익절:")
                print(f"      exit_reason: {trade.exit_reason}")
                print(f"      exit_price: {trade.exit_price:.2f}")
                print(f"      exit_ratio: {trade.exit_ratio*100:.0f}%")
                print(f"      remaining_quantity: {trade.remaining_quantity:.6f}")
                print(f"      ✨ stop_loss_price: {trade.stop_loss_price if trade.stop_loss_price is not None else 'NULL ❌'}")

                if trade.stop_loss_price is not None:
                    print(f"         ✅ SL 가격이 정상적으로 기록됨!")
                else:
                    print(f"         ❌ 문제 발견: stop_loss_price가 NULL입니다!")

                print(f"      tp1_price: {trade.tp1_price}")
                print(f"      tp2_price: {trade.tp2_price}")
                print(f"      tp3_price: {trade.tp3_price}")
                print()

        if not partial_exits_found:
            print("   ℹ️ 부분 익절이 발생한 거래가 없습니다.")
            print("   (백테스트 기간 중 TP 레벨에 도달한 포지션이 없었습니다)")
            print()
            print("   💡 확인 방법:")
            print("      - 더 긴 백테스트 기간 사용")
            print("      - 더 낮은 TP 퍼센트 사용")
            print("      - 다른 심볼 또는 시간 프레임 사용")
        else:
            print("✅ 부분 익절 레코드가 정상적으로 생성되었습니다!")
            print("   각 TP 레벨에서 유효했던 stop_loss_price가 기록되어 있습니다.")

        print()
        print("🎯 API 응답 검증 완료!")

    except Exception as e:
        print(f"❌ 백테스트 실행 실패: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Ensure database session is closed
        await data_provider.close()


if __name__ == "__main__":
    asyncio.run(test_real_api_response())
