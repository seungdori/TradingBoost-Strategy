"""
11월 13일 이후 시그널이 발생하지 않는 원인 분석 스크립트
"""

import asyncio
from datetime import datetime, timezone
from collections import Counter

# Set up path
import sys
sys.path.insert(0, '/Users/seunghyun/TradingBoost-Strategy')

from BACKTEST.data.timescale_provider import TimescaleProvider


async def analyze_signal_conditions():
    """11월 13일 전후 시그널 조건 분석"""

    provider = TimescaleProvider()

    try:
        # 전체 기간 데이터 로드 (UTC timezone)
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

        if not candles:
            print("❌ 데이터가 없습니다!")
            return

        # 11월 13일 전후 분리
        before_nov13 = [c for c in candles if c.timestamp < split_date]
        after_nov13 = [c for c in candles if c.timestamp >= split_date]

        print(f"\n📅 11월 13일 이전: {len(before_nov13)} 캔들")
        print(f"📅 11월 13일 이후: {len(after_nov13)} 캔들")

        # 파라미터 설정 (사용자 요청과 동일)
        RSI_OS = 30
        RSI_OB = 70
        RSI_ENTRY_OPTION = "돌파"  # 사용자가 사용한 옵션

        def count_signal_conditions(candle_list, label):
            """시그널 조건 카운트"""
            print(f"\n{'='*60}")
            print(f"📊 {label} 분석")
            print(f"{'='*60}")

            # RSI 상태 분포
            rsi_values = [c.rsi for c in candle_list if c.rsi is not None]
            rsi_none = sum(1 for c in candle_list if c.rsi is None)

            print(f"\n[RSI 분포]")
            print(f"  - RSI None: {rsi_none}")
            if rsi_values:
                print(f"  - RSI 최소: {min(rsi_values):.2f}")
                print(f"  - RSI 최대: {max(rsi_values):.2f}")
                print(f"  - RSI 평균: {sum(rsi_values)/len(rsi_values):.2f}")
                print(f"  - RSI < {RSI_OS} (Oversold): {sum(1 for r in rsi_values if r < RSI_OS)}")
                print(f"  - RSI > {RSI_OB} (Overbought): {sum(1 for r in rsi_values if r > RSI_OB)}")

            # trend_state 분포
            trend_states = [c.trend_state for c in candle_list if c.trend_state is not None]
            trend_none = sum(1 for c in candle_list if c.trend_state is None)

            print(f"\n[Trend State 분포]")
            print(f"  - trend_state None: {trend_none}")
            if trend_states:
                trend_counter = Counter(trend_states)
                for state, count in sorted(trend_counter.items()):
                    label_str = {-2: "Strong Down", -1: "Down", 0: "Neutral", 1: "Up", 2: "Strong Up"}.get(state, str(state))
                    print(f"  - {state} ({label_str}): {count}")

            # '돌파' 조건 체크 (RSI가 oversold/overbought 선을 돌파)
            long_crossunder = 0  # RSI가 oversold를 아래로 돌파 (Long)
            short_crossover = 0  # RSI가 overbought를 위로 돌파 (Short)

            # '초과' 조건 체크 (단순 RSI 비교)
            oversold_count = 0
            overbought_count = 0

            # 트렌드 필터 적용 후 실제 시그널
            long_signals_with_trend = 0
            short_signals_with_trend = 0

            prev_rsi = None
            for i, c in enumerate(candle_list):
                if c.rsi is None:
                    prev_rsi = None
                    continue

                current_rsi = c.rsi
                trend_state = c.trend_state

                # '초과' 조건
                if current_rsi < RSI_OS:
                    oversold_count += 1
                    # 트렌드 필터: -2가 아니면 Long 허용
                    if trend_state is not None and trend_state != -2:
                        long_signals_with_trend += 1

                if current_rsi > RSI_OB:
                    overbought_count += 1
                    # 트렌드 필터: +2가 아니면 Short 허용
                    if trend_state is not None and trend_state != 2:
                        short_signals_with_trend += 1

                # '돌파' 조건 (crossover/crossunder)
                if prev_rsi is not None:
                    # Long: prev_rsi > RSI_OS and current_rsi <= RSI_OS
                    if prev_rsi > RSI_OS and current_rsi <= RSI_OS:
                        long_crossunder += 1

                    # Short: prev_rsi < RSI_OB and current_rsi >= RSI_OB
                    if prev_rsi < RSI_OB and current_rsi >= RSI_OB:
                        short_crossover += 1

                prev_rsi = current_rsi

            print(f"\n[시그널 조건 - '초과' 모드]")
            print(f"  - RSI < {RSI_OS} (Oversold): {oversold_count} 캔들")
            print(f"  - RSI > {RSI_OB} (Overbought): {overbought_count} 캔들")
            print(f"  - Long 시그널 (트렌드 필터 적용): {long_signals_with_trend}")
            print(f"  - Short 시그널 (트렌드 필터 적용): {short_signals_with_trend}")

            print(f"\n[시그널 조건 - '돌파' 모드] ⚠️ 현재 사용 중")
            print(f"  - Long 돌파 (RSI가 {RSI_OS}을 아래로 돌파): {long_crossunder}")
            print(f"  - Short 돌파 (RSI가 {RSI_OB}를 위로 돌파): {short_crossover}")

            # 돌파 이벤트 상세 출력 (최근 5개)
            print(f"\n[최근 돌파 이벤트 (최대 10개)]")
            prev_rsi = None
            crossings = []
            for c in candle_list:
                if c.rsi is None:
                    prev_rsi = None
                    continue

                if prev_rsi is not None:
                    if prev_rsi > RSI_OS and c.rsi <= RSI_OS:
                        crossings.append((c.timestamp, "LONG (RSI 돌파↓)", prev_rsi, c.rsi, c.trend_state))
                    if prev_rsi < RSI_OB and c.rsi >= RSI_OB:
                        crossings.append((c.timestamp, "SHORT (RSI 돌파↑)", prev_rsi, c.rsi, c.trend_state))

                prev_rsi = c.rsi

            for ts, sig_type, p_rsi, c_rsi, trend in crossings[-10:]:
                trend_label = {-2: "Strong↓", -1: "↓", 0: "—", 1: "↑", 2: "Strong↑"}.get(trend, "None")
                blocked = ""
                if "LONG" in sig_type and trend == -2:
                    blocked = " ❌ BLOCKED (Strong Downtrend)"
                if "SHORT" in sig_type and trend == 2:
                    blocked = " ❌ BLOCKED (Strong Uptrend)"
                print(f"  {ts}: {sig_type} | prev={p_rsi:.2f} → curr={c_rsi:.2f} | trend={trend_label}{blocked}")

            return {
                'long_crossunder': long_crossunder,
                'short_crossover': short_crossover,
                'oversold': oversold_count,
                'overbought': overbought_count,
                'long_with_trend': long_signals_with_trend,
                'short_with_trend': short_signals_with_trend
            }

        # 분석 실행
        before_stats = count_signal_conditions(before_nov13, "11월 13일 이전")
        after_stats = count_signal_conditions(after_nov13, "11월 13일 이후")

        # 비교 요약
        print(f"\n{'='*60}")
        print("📈 비교 요약")
        print(f"{'='*60}")

        print(f"\n[돌파 모드 시그널 비교]")
        print(f"  11월 13일 이전:")
        print(f"    - Long 돌파: {before_stats['long_crossunder']}")
        print(f"    - Short 돌파: {before_stats['short_crossover']}")
        print(f"  11월 13일 이후:")
        print(f"    - Long 돌파: {after_stats['long_crossunder']}")
        print(f"    - Short 돌파: {after_stats['short_crossover']}")

        print(f"\n[초과 모드 시그널 비교 (참고용)]")
        print(f"  11월 13일 이전:")
        print(f"    - Long (트렌드 필터 적용): {before_stats['long_with_trend']}")
        print(f"    - Short (트렌드 필터 적용): {before_stats['short_with_trend']}")
        print(f"  11월 13일 이후:")
        print(f"    - Long (트렌드 필터 적용): {after_stats['long_with_trend']}")
        print(f"    - Short (트렌드 필터 적용): {after_stats['short_with_trend']}")

        # 원인 분석
        print(f"\n{'='*60}")
        print("🔍 원인 분석")
        print(f"{'='*60}")

        if after_stats['long_crossunder'] == 0 and after_stats['short_crossover'] == 0:
            print("\n⚠️ '돌파' 모드에서 11월 13일 이후 시그널이 발생하지 않음!")
            print("\n가능한 원인:")
            print("  1. RSI가 30/70 라인을 '돌파'하지 않음 (범위 내에서만 움직임)")
            print("  2. RSI 값이 급격하게 변하지 않아 돌파 조건 미충족")
            print("\n해결 방안:")
            print("  1. rsi_entry_option을 '초과'로 변경 → RSI < 30 또는 RSI > 70이면 시그널")
            print("  2. rsi_os/rsi_ob 값 조정 (예: 35/65로 완화)")

        if after_stats['oversold'] > 0 or after_stats['overbought'] > 0:
            print(f"\n💡 '초과' 모드 사용 시 시그널이 발생할 수 있음:")
            print(f"   - Oversold (RSI < 30): {after_stats['oversold']} 캔들")
            print(f"   - Overbought (RSI > 70): {after_stats['overbought']} 캔들")

    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(analyze_signal_conditions())
