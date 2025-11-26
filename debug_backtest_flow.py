"""
백테스트 흐름 디버깅 - 왜 11월 13일 이후로 시그널이 처리되지 않는지 확인
"""

import asyncio
from datetime import datetime, timezone

import sys
sys.path.insert(0, '/Users/seunghyun/TradingBoost-Strategy')

from BACKTEST.data.timescale_provider import TimescaleProvider
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy


async def simulate_backtest_flow():
    """백테스트 시그널 처리 흐름 시뮬레이션"""

    provider = TimescaleProvider()

    # 사용자의 요청 파라미터와 동일하게 설정
    params = {
        "rsi_period": 14,
        "rsi_oversold": 30,  # rsi_os
        "rsi_overbought": 70,  # rsi_ob
        "direction": "both",
        "use_trend_filter": True,
        "entry_option": "rsi_trend",
        "rsi_entry_option": "돌파",  # ⚠️ 핵심 파라미터
        "leverage": 10,
        "investment": 35,
        "pyramiding_enabled": True,
        "pyramiding_limit": 8,
        # TP/SL 설정
        "tp_option": "atr",
        "use_tp1": True,
        "use_tp2": True,
        "use_tp3": True,
        "tp1_value": 3,
        "tp2_value": 4,
        "tp3_value": 5,
        "tp1_ratio": 30,
        "tp2_ratio": 30,
        "tp3_ratio": 40,
        "stop_loss_enabled": False,
        "trailing_stop_active": True,
        "trailing_start_point": "tp2",
        "trailing_stop_offset_value": 0.5,
    }

    strategy = HyperrsiStrategy(params)

    try:
        start_date = datetime(2025, 11, 4, 0, 0, 0, tzinfo=timezone.utc)
        end_date = datetime(2025, 11, 24, 23, 59, 59, tzinfo=timezone.utc)

        candles = await provider.get_candles(
            symbol="BTC/USDT:USDT",
            timeframe="5m",
            start_date=start_date,
            end_date=end_date
        )

        print(f"\n📊 전체 캔들 수: {len(candles)}")
        print(f"\n⚙️ 전략 파라미터:")
        print(f"   - rsi_entry_option: {strategy.rsi_entry_option}")
        print(f"   - direction: {strategy.direction}")
        print(f"   - use_trend_filter: {strategy.use_trend_filter}")

        # 시그널 생성 시뮬레이션 (포지션 없이)
        signals = []
        split_date = datetime(2025, 11, 13, 0, 0, 0, tzinfo=timezone.utc)

        print(f"\n{'='*70}")
        print("🔍 시그널 생성 시뮬레이션 (포지션 없는 상태 가정)")
        print(f"{'='*70}")

        for i, candle in enumerate(candles):
            signal = await strategy.generate_signal(candle)

            if signal.side:  # 시그널 발생
                signals.append({
                    'timestamp': candle.timestamp,
                    'side': signal.side.value,
                    'reason': signal.reason,
                    'price': candle.close,
                    'rsi': signal.indicators.get('rsi'),
                    'prev_rsi': signal.indicators.get('previous_rsi'),
                    'trend_state': signal.indicators.get('trend_state')
                })

        # 결과 분석
        before_nov13 = [s for s in signals if s['timestamp'] < split_date]
        after_nov13 = [s for s in signals if s['timestamp'] >= split_date]

        print(f"\n[전체 시그널 발생]")
        print(f"   - 총 시그널: {len(signals)}")
        print(f"   - 11월 13일 이전: {len(before_nov13)}")
        print(f"   - 11월 13일 이후: {len(after_nov13)}")

        print(f"\n[11월 13일 이전 시그널 (최대 10개)]")
        for s in before_nov13[:10]:
            trend_label = {-2: "Strong↓", -1: "↓", 0: "—", 1: "↑", 2: "Strong↑"}.get(s['trend_state'], "None")
            prev_rsi_str = f"{s['prev_rsi']:.2f}" if s['prev_rsi'] is not None else "None"
            rsi_str = f"{s['rsi']:.2f}" if s['rsi'] is not None else "None"
            print(f"   {s['timestamp']}: {s['side']} @ ${s['price']:.2f}")
            print(f"      RSI: {prev_rsi_str} → {rsi_str} | trend={trend_label}")
            print(f"      reason: {s['reason']}")

        print(f"\n[11월 13일 이후 시그널 (최대 15개)]")
        for s in after_nov13[:15]:
            trend_label = {-2: "Strong↓", -1: "↓", 0: "—", 1: "↑", 2: "Strong↑"}.get(s['trend_state'], "None")
            prev_rsi_str = f"{s['prev_rsi']:.2f}" if s['prev_rsi'] is not None else "None"
            rsi_str = f"{s['rsi']:.2f}" if s['rsi'] is not None else "None"
            print(f"   {s['timestamp']}: {s['side']} @ ${s['price']:.2f}")
            print(f"      RSI: {prev_rsi_str} → {rsi_str} | trend={trend_label}")
            print(f"      reason: {s['reason']}")

        # 결론
        print(f"\n{'='*70}")
        print("🔍 결론")
        print(f"{'='*70}")

        if len(after_nov13) == 0:
            print("\n⚠️ 11월 13일 이후 시그널이 전혀 발생하지 않음!")
            print("\n📌 가능한 원인:")
            print("   1. '돌파' 로직에서 previous_rsi가 제대로 계산되지 않음")
            print("   2. trend_state가 항상 ±2여서 차단됨")
            print("   3. RSI가 정확히 30/70을 돌파하는 캔들이 없음")
        else:
            print(f"\n✅ 11월 13일 이후에도 시그널이 발생함: {len(after_nov13)}개")
            print("\n📌 백테스트 엔진에서 시그널이 무시되는 원인 조사 필요:")
            print("   1. 포지션이 열려있어서 새 시그널 체크 안함")
            print("   2. 포지션이 종료되지 않아 계속 같은 포지션 유지")

            # 첫 번째 시그널 이후 흐름 분석
            if signals:
                print(f"\n[첫 번째 시그널 이후 분석]")
                first_signal = signals[0]
                print(f"   첫 시그널: {first_signal['timestamp']} - {first_signal['side']}")

                # 첫 시그널 이후 다음 시그널까지 얼마나 걸리는지
                if len(signals) > 1:
                    second_signal = signals[1]
                    gap = (second_signal['timestamp'] - first_signal['timestamp'])
                    print(f"   두번째 시그널: {second_signal['timestamp']} - {second_signal['side']}")
                    print(f"   시그널 간격: {gap}")

    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(simulate_backtest_flow())
