#!/usr/bin/env python3
"""
특정 시점의 데이터로 SignalGenerator가 제대로 작동하는지 테스트
"""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from BACKTEST.strategies.signal_generator import SignalGenerator

DB_URL = "postgresql+asyncpg://tradeuser:SecurePassword123@158.247.218.188:5432/candlesdb"


async def test_signal_at_specific_time():
    """DB에서 확인한 진입 가능 시점에서 SignalGenerator 테스트"""

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 프론트엔드와 동일한 파라미터로 SignalGenerator 생성
    signal_gen = SignalGenerator(
        rsi_period=14,
        rsi_oversold=30,
        rsi_overbought=70,
        entry_option="돌파",  # RSI 돌파 모드
        use_trend_filter=True
    )

    async with session_factory() as session:
        print("=" * 80)
        print("🔍 SignalGenerator 직접 테스트")
        print("=" * 80)
        print()

        # 테스트할 시점들 (DB에서 확인한 진입 가능 시점)
        test_times = [
            datetime(2025, 11, 13, 13, 25, 0, tzinfo=timezone.utc),  # RSI 41.34 → 29.61, trend=0
            datetime(2025, 11, 14, 4, 30, 0, tzinfo=timezone.utc),   # RSI 43.76 → 23.93, trend=0
            datetime(2025, 11, 23, 7, 0, 0, tzinfo=timezone.utc),    # RSI 31.64 → 27.42, trend=0
        ]

        for test_time in test_times:
            # 해당 시점과 이전 시점의 데이터 조회
            query = text("""
                WITH candle_with_prev AS (
                    SELECT
                        time,
                        close,
                        rsi14,
                        LAG(rsi14) OVER (ORDER BY time) as prev_rsi,
                        trend_state,
                        atr
                    FROM btc_usdt
                    WHERE timeframe = '5m'
                        AND time <= :target_time
                    ORDER BY time DESC
                    LIMIT 2
                )
                SELECT * FROM candle_with_prev
                ORDER BY time
            """)
            result = await session.execute(query, {"target_time": test_time})
            rows = result.fetchall()

            if len(rows) < 2:
                print(f"⚠️ {test_time}: 데이터 부족")
                continue

            prev_candle = rows[0]
            current_candle = rows[1]

            print(f"📅 {test_time}")
            print(f"   이전 캔들: time={prev_candle.time}, RSI={prev_candle.rsi14:.2f}")
            print(f"   현재 캔들: time={current_candle.time}, RSI={current_candle.rsi14:.2f}, trend={current_candle.trend_state}")
            print()

            # SignalGenerator로 LONG 시그널 체크
            has_long, long_reason = signal_gen.check_long_signal(
                rsi=current_candle.rsi14,
                trend_state=current_candle.trend_state,
                previous_rsi=prev_candle.rsi14
            )

            print(f"   ✅ SignalGenerator.check_long_signal() 결과:")
            print(f"      has_signal: {has_long}")
            print(f"      reason: {long_reason}")
            print()

            # 조건별 상세 체크
            print(f"   📋 상세 조건 체크:")

            # RSI 돌파 조건
            rsi_breakthrough = prev_candle.rsi14 > 30 and current_candle.rsi14 <= 30
            print(f"      RSI 돌파 (prev > 30 AND current <= 30): {rsi_breakthrough}")
            print(f"         prev_rsi={prev_candle.rsi14:.2f} > 30: {prev_candle.rsi14 > 30}")
            print(f"         current_rsi={current_candle.rsi14:.2f} <= 30: {current_candle.rsi14 <= 30}")

            # 트렌드 필터
            trend_blocked = current_candle.trend_state == -2
            print(f"      트렌드 차단 (trend == -2): {trend_blocked}")
            print(f"         current trend_state={current_candle.trend_state}")

            print()
            print(f"   🎯 예상 결과: RSI 돌파={rsi_breakthrough}, 트렌드 차단={trend_blocked}")
            print(f"      → 진입 가능 여부: {rsi_breakthrough and not trend_blocked}")
            print()
            print("-" * 80)
            print()

    await engine.dispose()


async def main():
    try:
        await test_signal_at_specific_time()
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
