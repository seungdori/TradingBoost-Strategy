"""
상세 시그널 분석 - 트렌드 필터 적용 후 실제 통과하는 시그널 확인
"""

import asyncio
from datetime import datetime, timezone
from collections import Counter

import sys
sys.path.insert(0, '/Users/seunghyun/TradingBoost-Strategy')

from BACKTEST.data.timescale_provider import TimescaleProvider


async def analyze_passed_signals():
    """트렌드 필터를 통과한 실제 시그널 분석"""

    provider = TimescaleProvider()

    try:
        start_date = datetime(2025, 11, 4, 0, 0, 0, tzinfo=timezone.utc)
        end_date = datetime(2025, 11, 24, 23, 59, 59, tzinfo=timezone.utc)
        split_date = datetime(2025, 11, 13, 0, 0, 0, tzinfo=timezone.utc)

        candles = await provider.get_candles(
            symbol="BTC/USDT:USDT",
            timeframe="5m",
            start_date=start_date,
            end_date=end_date
        )

        print(f"\n📊 전체 캔들 수: {len(candles)}")

        # 파라미터 설정
        RSI_OS = 30
        RSI_OB = 70

        def analyze_dolpa_signals(candle_list, label):
            """'돌파' 모드에서 트렌드 필터 통과 시그널 분석"""
            print(f"\n{'='*70}")
            print(f"📊 {label} - '돌파' 모드 상세 분석")
            print(f"{'='*70}")

            passed_long = []
            passed_short = []
            blocked_long_by_trend = []
            blocked_short_by_trend = []

            prev_rsi = None
            for i, c in enumerate(candle_list):
                if c.rsi is None:
                    prev_rsi = None
                    continue

                current_rsi = c.rsi
                trend_state = c.trend_state

                # Long 돌파: prev_rsi > 30 and current_rsi <= 30
                if prev_rsi is not None and prev_rsi > RSI_OS and current_rsi <= RSI_OS:
                    if trend_state == -2:
                        blocked_long_by_trend.append((c.timestamp, prev_rsi, current_rsi, trend_state, c.close))
                    else:
                        passed_long.append((c.timestamp, prev_rsi, current_rsi, trend_state, c.close))

                # Short 돌파: prev_rsi < 70 and current_rsi >= 70
                if prev_rsi is not None and prev_rsi < RSI_OB and current_rsi >= RSI_OB:
                    if trend_state == 2:
                        blocked_short_by_trend.append((c.timestamp, prev_rsi, current_rsi, trend_state, c.close))
                    else:
                        passed_short.append((c.timestamp, prev_rsi, current_rsi, trend_state, c.close))

                prev_rsi = current_rsi

            print(f"\n[Long 시그널 ('돌파' 모드)]")
            print(f"  ✅ 트렌드 필터 통과: {len(passed_long)}")
            print(f"  ❌ 트렌드 필터 차단 (trend=-2): {len(blocked_long_by_trend)}")

            if passed_long:
                print(f"\n  [통과한 Long 시그널 (최대 15개)]")
                for ts, p_rsi, c_rsi, trend, price in passed_long[:15]:
                    trend_label = {-2: "Strong↓", -1: "↓", 0: "—", 1: "↑", 2: "Strong↑"}.get(trend, "None")
                    print(f"    {ts}: prev={p_rsi:.2f}→curr={c_rsi:.2f} | trend={trend_label} | price=${price:.2f}")

            print(f"\n[Short 시그널 ('돌파' 모드)]")
            print(f"  ✅ 트렌드 필터 통과: {len(passed_short)}")
            print(f"  ❌ 트렌드 필터 차단 (trend=+2): {len(blocked_short_by_trend)}")

            if passed_short:
                print(f"\n  [통과한 Short 시그널 (최대 15개)]")
                for ts, p_rsi, c_rsi, trend, price in passed_short[:15]:
                    trend_label = {-2: "Strong↓", -1: "↓", 0: "—", 1: "↑", 2: "Strong↑"}.get(trend, "None")
                    print(f"    {ts}: prev={p_rsi:.2f}→curr={c_rsi:.2f} | trend={trend_label} | price=${price:.2f}")

            return len(passed_long), len(passed_short), len(blocked_long_by_trend), len(blocked_short_by_trend)

        # 11월 13일 전후 분리
        before_nov13 = [c for c in candles if c.timestamp < split_date]
        after_nov13 = [c for c in candles if c.timestamp >= split_date]

        b_long, b_short, b_blocked_l, b_blocked_s = analyze_dolpa_signals(before_nov13, "11월 13일 이전")
        a_long, a_short, a_blocked_l, a_blocked_s = analyze_dolpa_signals(after_nov13, "11월 13일 이후")

        # 요약
        print(f"\n{'='*70}")
        print("📈 '돌파' 모드 시그널 요약")
        print(f"{'='*70}")

        print(f"\n[11월 13일 이전]")
        print(f"  Long: {b_long} 통과 / {b_blocked_l} 차단 ({b_blocked_l/(b_long+b_blocked_l)*100:.1f}% 차단)" if (b_long+b_blocked_l) > 0 else "  Long: 0")
        print(f"  Short: {b_short} 통과 / {b_blocked_s} 차단 ({b_blocked_s/(b_short+b_blocked_s)*100:.1f}% 차단)" if (b_short+b_blocked_s) > 0 else "  Short: 0")

        print(f"\n[11월 13일 이후]")
        print(f"  Long: {a_long} 통과 / {a_blocked_l} 차단 ({a_blocked_l/(a_long+a_blocked_l)*100:.1f}% 차단)" if (a_long+a_blocked_l) > 0 else "  Long: 0")
        print(f"  Short: {a_short} 통과 / {a_blocked_s} 차단 ({a_blocked_s/(a_short+a_blocked_s)*100:.1f}% 차단)" if (a_short+a_blocked_s) > 0 else "  Short: 0")

        # 결론
        print(f"\n{'='*70}")
        print("🔍 결론")
        print(f"{'='*70}")

        if a_long == 0 and a_short == 0:
            print("\n⚠️ 11월 13일 이후 '돌파' 모드에서 트렌드 필터를 통과한 시그널 없음!")
            print("\n📌 원인:")
            print("   RSI가 30/70을 돌파하는 시점에 항상 극단적 트렌드(±2) 상태임")
            print("   → RSI 돌파 조건과 트렌드 필터가 서로 상충됨")
        elif a_long > 0 or a_short > 0:
            print(f"\n✅ 11월 13일 이후에도 시그널이 통과함!")
            print(f"   Long: {a_long}개, Short: {a_short}개")
            print("\n📌 백테스트 엔진에서 시그널이 발생하지 않는 다른 원인 조사 필요")

    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(analyze_passed_signals())
