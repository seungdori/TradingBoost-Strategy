#!/usr/bin/env python3
"""
trend_state를 확인하는 스크립트

TimescaleDB에서 캔들 데이터를 가져와 trend_state를 계산합니다.
"""
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from BACKTEST.data import TimescaleProvider
from BACKTEST.strategies.signal_generator import SignalGenerator


async def check_trend_state(
    symbol: str = "BTC/USDT:USDT",
    timeframe: str = "15m",
    start_date: str = "2025-09-25",
    end_date: str = "2025-10-05"
):
    """특정 기간의 trend_state를 확인합니다."""

    provider = TimescaleProvider()
    signal_gen = SignalGenerator({})

    # 날짜 파싱
    start = datetime.fromisoformat(start_date + "T00:00:00+00:00")
    end = datetime.fromisoformat(end_date + "T23:59:59+00:00")

    print("=" * 80)
    print(f"trend_state 확인: {symbol} {timeframe}")
    print(f"기간: {start} ~ {end}")
    print("=" * 80)

    # 캔들 데이터 가져오기
    candles = await provider.get_candles(
        symbol=symbol,
        timeframe=timeframe,
        start_date=start,
        end_date=end,
        limit=1000
    )

    if not candles:
        print("❌ 캔들 데이터가 없습니다.")
        await provider.close()
        return

    print(f"\n총 {len(candles)}개 캔들 로드됨\n")

    # DataFrame 생성
    df = pd.DataFrame([{
        'timestamp': c.timestamp,
        'open': c.open,
        'high': c.high,
        'low': c.low,
        'close': c.close,
        'volume': c.volume
    } for c in candles])

    # trend_state 분포 계산
    trend_states = []

    for i in range(60, len(df)):  # 최소 60개 캔들 필요 (MA60 계산)
        closes = df['close'].iloc[:i+1]

        try:
            trend_state = signal_gen.calculate_trend_state(
                closes=closes,
                ma20_period=20,
                ma60_period=60,
                bb_period=15,
                bb_std=1.5,
                momentum_period=20
            )
            trend_states.append({
                'timestamp': df['timestamp'].iloc[i],
                'close': df['close'].iloc[i],
                'trend_state': trend_state
            })
        except Exception as e:
            print(f"⚠️  {df['timestamp'].iloc[i]}: 계산 실패 - {e}")
            continue

    # 결과 출력
    ts_df = pd.DataFrame(trend_states)

    print("\n" + "=" * 80)
    print("trend_state 분포:")
    print("=" * 80)

    state_counts = ts_df['trend_state'].value_counts().sort_index()
    total = len(ts_df)

    # PineScript 3-level system
    state_labels = {
        -2: "극단 하락추세 (Extreme Downtrend)",
        0: "중립 (Neutral)",
        2: "극단 상승추세 (Extreme Uptrend)"
    }

    for state in [-2, 0, 2]:
        count = state_counts.get(state, 0)
        pct = (count / total * 100) if total > 0 else 0
        label = state_labels[state]
        print(f"  {state:2d} ({label:30s}): {count:4d} ({pct:5.2f}%)")

    # 9월 30일 전후 상세 정보
    print("\n" + "=" * 80)
    print("9월 30일 전후 trend_state 상세:")
    print("=" * 80)

    sept_30 = datetime(2025, 9, 30, tzinfo=start.tzinfo)

    # 9월 28일 ~ 10월 2일 필터링
    sept_filter = ts_df[
        (ts_df['timestamp'] >= sept_30 - timedelta(days=2)) &
        (ts_df['timestamp'] <= sept_30 + timedelta(days=2))
    ]

    if not sept_filter.empty:
        print(f"\n{'Timestamp':<25} {'Close':>12} {'trend_state':>12} {'Label':<30}")
        print("-" * 85)

        for _, row in sept_filter.iterrows():
            ts = row['timestamp']
            close = row['close']
            state = row['trend_state']
            label = state_labels[state]

            # 9월 30일 하이라이트
            marker = ">>> " if ts.date() == sept_30.date() else "    "

            print(f"{marker}{ts} {close:12.2f} {state:12d} {label}")
    else:
        print("⚠️  9월 30일 전후 데이터가 없습니다.")

    # trend_state=2 발생 시점 찾기
    strong_up = ts_df[ts_df['trend_state'] == 2]

    print("\n" + "=" * 80)
    print(f"trend_state=2 (강한 상승추세) 발생 시점: {len(strong_up)}건")
    print("=" * 80)

    if not strong_up.empty:
        print(f"\n{'Timestamp':<25} {'Close':>12}")
        print("-" * 40)
        for _, row in strong_up.head(20).iterrows():
            print(f"{row['timestamp']} {row['close']:12.2f}")
    else:
        print("\n⚠️  전체 기간 동안 trend_state=2가 발생하지 않았습니다.")

    await provider.close()


async def main():
    """
    사용 예시:
    1. 9월 말 확인 (기본)
    2. 전체 1년 확인
    """

    # 9월 말 확인
    print("\n\n")
    print("█" * 80)
    print("1. 9월 말 기간 trend_state 확인")
    print("█" * 80)
    await check_trend_state(
        symbol="BTC/USDT:USDT",
        timeframe="15m",
        start_date="2025-09-25",
        end_date="2025-10-05"
    )

    # 전체 1년 확인
    print("\n\n")
    print("█" * 80)
    print("2. 전체 1년 기간 trend_state 확인")
    print("█" * 80)
    await check_trend_state(
        symbol="BTC/USDT:USDT",
        timeframe="15m",
        start_date="2025-01-01",
        end_date="2025-11-07"
    )


if __name__ == "__main__":
    asyncio.run(main())
