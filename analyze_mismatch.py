"""
불일치 구간 상세 분석

2025-10-29 14:15-16:30 구간에서 왜 TV=0, Auto=-2 불일치가 발생하는지 분석
"""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from shared.config import get_settings


async def analyze_mismatch_period():
    """불일치 구간 상세 분석"""

    print("=" * 100)
    print("🔍 불일치 구간 상세 분석: 2025-10-29 14:00-17:00")
    print("=" * 100)
    print()

    # DB 연결
    settings = get_settings()
    db_url = (
        f"postgresql+asyncpg://{settings.CANDLES_USER}:{settings.CANDLES_PASSWORD}"
        f"@{settings.CANDLES_HOST}:{settings.CANDLES_PORT}/{settings.CANDLES_DATABASE}"
    )
    engine = create_async_engine(db_url, pool_size=1, max_overflow=2, pool_pre_ping=True, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        try:
            # 15m 데이터 조회
            query_15m = text("""
                SELECT
                    time,
                    close,
                    trend_state,
                    auto_trend_state
                FROM btc_usdt
                WHERE timeframe = '15m'
                  AND time >= '2025-10-29 13:00:00+00'
                  AND time <= '2025-10-29 18:00:00+00'
                ORDER BY time ASC
            """)
            result_15m = await session.execute(query_15m)
            rows_15m = result_15m.fetchall()

            print(f"✅ 15m 데이터: {len(rows_15m)}개 캔들")
            print()

            # 30m 데이터 조회 (MTF)
            query_30m = text("""
                SELECT
                    time,
                    close
                FROM btc_usdt
                WHERE timeframe = '30m'
                  AND time >= '2025-10-29 12:00:00+00'
                  AND time <= '2025-10-29 18:00:00+00'
                ORDER BY time ASC
            """)
            result_30m = await session.execute(query_30m)
            rows_30m = result_30m.fetchall()

            print(f"✅ 30m 데이터 (MTF): {len(rows_30m)}개 캔들")
            print()

            # 15m 상세 출력
            print("=" * 120)
            print(f"{'시간':<20} | {'Close':>11} | {'TV':>5} | {'Auto':>5} | "
                  f"{'CYCLE_Bull(TV)':>15} | {'CYCLE_Bear(TV)':>15} | {'일치':>5}")
            print("=" * 120)

            for row in rows_15m:
                tv = row.trend_state if row.trend_state is not None else -99
                auto = row.auto_trend_state if row.auto_trend_state is not None else -99

                # trend_state 비트 분해
                # bit 0 (value 1): AUTO_TREND_Bull
                # bit 1 (value 2): CYCLE_Bull
                # bit 2 (value 4): BB_State
                cycle_bull_tv = "True" if (tv & 2) else "False"
                cycle_bear_tv = "True" if (tv & -2) and not (tv & 2) else "False"  # -2는 CYCLE_Bear

                cycle_bull_auto = "True" if (auto & 2) else "False"
                cycle_bear_auto = "True" if auto == -2 else "False"

                match = "✓" if tv == auto else "✗"

                # 불일치만 강조 표시
                if tv != auto:
                    print(f"{row.time} | {float(row.close):>11.2f} | {tv:>5} | {auto:>5} | "
                          f"{cycle_bull_tv:>15} | {cycle_bear_tv:>15} | {match:>5} ⚠️")
                else:
                    print(f"{row.time} | {float(row.close):>11.2f} | {tv:>5} | {auto:>5} | "
                          f"{cycle_bull_tv:>15} | {cycle_bear_tv:>15} | {match:>5}")

            print("=" * 120)
            print()

            # 30m 데이터 확인
            print("=" * 80)
            print("📊 30m MTF 데이터 (CYCLE 계산용)")
            print("=" * 80)
            print(f"{'시간':<20} | {'Close':>11}")
            print("-" * 80)
            for row in rows_30m:
                print(f"{row.time} | {float(row.close):>11.2f}")
            print("=" * 80)
            print()

            # 분석
            print("=" * 80)
            print("💡 분석")
            print("=" * 80)
            print("1. TV=0, Auto=-2 불일치는 CYCLE_Bear 전환 시점 문제")
            print("2. TradingView는 CYCLE_Bear가 False (중립 상태)")
            print("3. Python은 CYCLE_Bear가 True로 인식")
            print("4. 이는 CYCLE_Bear 전환 로직에 여전히 시간 차이가 있음을 의미")
            print()
            print("가능한 원인:")
            print("- CYCLE_Bear도 CYCLE_Bull과 같은 1-offset 문제가 있을 수 있음")
            print("- 또는 다른 계산 차이 (VIDYA, CMO 등)")
            print("- MTF 30m → 15m 매핑에서의 미묘한 차이")
            print()

        except Exception as e:
            print(f"❌ 오류 발생: {e}")
            import traceback
            traceback.print_exc()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(analyze_mismatch_period())
