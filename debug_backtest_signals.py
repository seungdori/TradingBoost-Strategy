"""
백테스트 시그널 생성 디버깅 - 11월 13일 이후 시그널 체크 추적
"""

import asyncio
from datetime import datetime, timezone

import sys
sys.path.insert(0, '/Users/seunghyun/TradingBoost-Strategy')

import logging
# 디버그 로깅 활성화
logging.basicConfig(level=logging.INFO)

from BACKTEST.data.timescale_provider import TimescaleProvider
from BACKTEST.strategies.hyperrsi_strategy import HyperrsiStrategy


async def debug_signals():
    """11월 13일 이후 시그널 생성 디버깅"""

    provider = TimescaleProvider()

    # 사용자의 요청 파라미터와 동일하게 설정
    params = {
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "direction": "both",
        "use_trend_filter": True,
        "entry_option": "rsi_trend",
        "rsi_entry_option": "돌파",
        "leverage": 10,
        "investment": 35,
    }

    strategy = HyperrsiStrategy(params)

    try:
        # 11월 13일 이후만 분석
        start_date = datetime(2025, 11, 13, 9, 0, 0, tzinfo=timezone.utc)  # 마지막 거래 종료 시간
        end_date = datetime(2025, 11, 24, 23, 59, 59, tzinfo=timezone.utc)

        candles = await provider.get_candles(
            symbol="BTC/USDT:USDT",
            timeframe="5m",
            start_date=start_date,
            end_date=end_date
        )

        print(f"\n📊 11월 13일 이후 캔들 수: {len(candles)}")
        print(f"⚙️ rsi_entry_option: {strategy.rsi_entry_option}")
        print(f"⚙️ direction: {strategy.direction}")
        print(f"⚙️ use_trend_filter: {strategy.use_trend_filter}")

        # 시그널 생성 디버깅
        signals_found = []
        dolpa_conditions = []  # 돌파 조건 충족 시점

        print(f"\n{'='*70}")
        print("🔍 RSI 돌파 조건 분석")
        print(f"{'='*70}")

        RSI_OS = 30
        RSI_OB = 70

        for i, candle in enumerate(candles):
            signal = await strategy.generate_signal(candle)

            if signal.side:
                signals_found.append({
                    'timestamp': candle.timestamp,
                    'side': signal.side.value,
                    'reason': signal.reason,
                    'rsi': candle.rsi,
                    'trend_state': candle.trend_state
                })

            # 돌파 조건 체크 (직접 분석)
            if i > 0 and candle.rsi is not None:
                prev_candle = candles[i-1]
                if prev_candle.rsi is not None:
                    prev_rsi = prev_candle.rsi
                    curr_rsi = candle.rsi
                    trend_state = candle.trend_state

                    # Long 돌파: prev > 30 and curr <= 30
                    if prev_rsi > RSI_OS and curr_rsi <= RSI_OS:
                        blocked = " ❌ BLOCKED" if trend_state == -2 else ""
                        dolpa_conditions.append({
                            'timestamp': candle.timestamp,
                            'type': 'LONG',
                            'prev_rsi': prev_rsi,
                            'curr_rsi': curr_rsi,
                            'trend_state': trend_state,
                            'blocked': trend_state == -2
                        })

                    # Short 돌파: prev < 70 and curr >= 70
                    if prev_rsi < RSI_OB and curr_rsi >= RSI_OB:
                        blocked = " ❌ BLOCKED" if trend_state == 2 else ""
                        dolpa_conditions.append({
                            'timestamp': candle.timestamp,
                            'type': 'SHORT',
                            'prev_rsi': prev_rsi,
                            'curr_rsi': curr_rsi,
                            'trend_state': trend_state,
                            'blocked': trend_state == 2
                        })

        # 결과 출력
        print(f"\n[DB RSI 기준 돌파 조건 충족 캔들: {len(dolpa_conditions)}개]")
        for d in dolpa_conditions:
            trend_label = {-2: "Strong↓", -1: "↓", 0: "—", 1: "↑", 2: "Strong↑"}.get(d['trend_state'], "None")
            blocked_str = " ❌ BLOCKED (트렌드 필터)" if d['blocked'] else " ✅ PASS"
            print(f"  {d['timestamp']}: {d['type']} | prev={d['prev_rsi']:.2f} → curr={d['curr_rsi']:.2f} | trend={trend_label}{blocked_str}")

        # 트렌드 필터 통과한 시그널
        passed_signals = [d for d in dolpa_conditions if not d['blocked']]
        print(f"\n[트렌드 필터 통과한 돌파 이벤트: {len(passed_signals)}개]")
        for d in passed_signals:
            trend_label = {-2: "Strong↓", -1: "↓", 0: "—", 1: "↑", 2: "Strong↑"}.get(d['trend_state'], "None")
            print(f"  {d['timestamp']}: {d['type']} | prev={d['prev_rsi']:.2f} → curr={d['curr_rsi']:.2f} | trend={trend_label}")

        # 전략에서 생성된 실제 시그널
        print(f"\n[전략에서 생성된 실제 시그널: {len(signals_found)}개]")
        for s in signals_found:
            print(f"  {s['timestamp']}: {s['side']} | rsi={s['rsi']:.2f} | trend={s['trend_state']}")
            print(f"      reason: {s['reason']}")

        # 결론
        print(f"\n{'='*70}")
        print("🔍 결론")
        print(f"{'='*70}")

        if len(passed_signals) > 0 and len(signals_found) == 0:
            print("\n⚠️ 문제 발견!")
            print("   - 돌파 조건 충족 + 트렌드 필터 통과한 캔들이 있음")
            print("   - 그러나 전략에서 시그널이 생성되지 않음")
            print("\n📌 가능한 원인:")
            print("   1. 전략의 price_history에서 previous_rsi가 다르게 계산됨")
            print("   2. 전략 내부에서 추가 조건이 있음")

            # 첫 번째 passed_signal 상세 분석
            if passed_signals:
                first_pass = passed_signals[0]
                print(f"\n[첫 번째 통과 신호 상세 분석]")
                print(f"   시간: {first_pass['timestamp']}")
                print(f"   유형: {first_pass['type']}")
                print(f"   DB RSI: prev={first_pass['prev_rsi']:.2f} → curr={first_pass['curr_rsi']:.2f}")
                print(f"   트렌드: {first_pass['trend_state']}")

        elif len(passed_signals) == 0:
            print("\n📌 결론: 11월 13일 09:00 이후 트렌드 필터를 통과하는 돌파 이벤트가 없음")
            print("   - 모든 돌파 시점에서 trend_state가 ±2 (극단적 추세)")

    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(debug_signals())
