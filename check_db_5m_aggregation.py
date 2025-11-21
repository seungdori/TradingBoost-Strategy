"""
DB의 5분봉이 어떻게 집계되었는지 역추적
DB 1분봉으로부터 5분봉을 재계산해서 비교
"""

import asyncio
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import text
from shared.database.session import create_async_engine
from BACKTEST.config import get_shared_settings


async def check_db_5m_aggregation():
    """DB 5분봉 집계 방식 역추적"""

    print("=" * 100)
    print("DB 5분봉 집계 방식 역추적")
    print("=" * 100)

    # TimescaleDB 연결
    settings = get_shared_settings()
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    # DB 1분봉 조회 (20:35~21:00)
    start_time = datetime(2025, 11, 16, 20, 35, 0, tzinfo=timezone.utc)
    end_time = datetime(2025, 11, 16, 21, 0, 0, tzinfo=timezone.utc)

    async with engine.begin() as conn:
        result_1m = await conn.execute(
            text("""
                SELECT time, open, high, low, close
                FROM okx_candles_1m
                WHERE symbol = 'BTCUSDT'
                  AND time >= :start_time
                  AND time <= :end_time
                ORDER BY time ASC
            """),
            {'start_time': start_time, 'end_time': end_time}
        )
        candles_1m = result_1m.fetchall()

        result_5m = await conn.execute(
            text("""
                SELECT time, open, high, low, close
                FROM okx_candles_5m
                WHERE symbol = 'BTCUSDT'
                  AND time >= :start_time
                  AND time <= :end_time
                ORDER BY time ASC
            """),
            {'start_time': start_time, 'end_time': end_time}
        )
        candles_5m = result_5m.fetchall()

    print(f"\n📊 DB 1분봉 조회: {len(candles_1m)}개")
    print(f"📊 DB 5분봉 조회: {len(candles_5m)}개")

    # 5분봉 경계별로 분석
    boundaries = [
        datetime(2025, 11, 16, 20, 40, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 16, 20, 45, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 16, 20, 50, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 16, 20, 55, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 16, 21, 0, 0, tzinfo=timezone.utc),
    ]

    for boundary in boundaries:
        print(f"\n{'='*100}")
        print(f"5분 경계: {str(boundary)[:19]}")
        print(f"{'='*100}")

        # DB 5분봉 값
        db_5m = [c for c in candles_5m if c[0] == boundary]
        if db_5m:
            db_open = float(db_5m[0][1])
            db_high = float(db_5m[0][2])
            db_low = float(db_5m[0][3])
            db_close = float(db_5m[0][4])

            print(f"\n📊 DB 5분봉:")
            print(f"  Open:  {db_open:>10.2f}")
            print(f"  High:  {db_high:>10.2f}")
            print(f"  Low:   {db_low:>10.2f}")
            print(f"  Close: {db_close:>10.2f}")

        # 여러 집계 방법 시도
        methods = [
            ("방법1: (boundary-4 < time <= boundary)", 4, True, False),
            ("방법2: (boundary-5 < time <= boundary-1) + boundary", 5, False, True),
            ("방법3: (boundary-5 <= time <= boundary)", 5, False, False),
            ("방법4: (boundary-5 < time < boundary)", 5, True, True),
        ]

        for method_name, minutes_before, exclude_start, exclude_boundary in methods:
            if exclude_boundary:
                start = boundary - pd.Timedelta(minutes=minutes_before)
                end = boundary - pd.Timedelta(minutes=1)
                selected = [c for c in candles_1m if (c[0] > start or (not exclude_start and c[0] >= start)) and c[0] <= end]
                # boundary 추가
                boundary_candle = [c for c in candles_1m if c[0] == boundary]
                selected = selected + boundary_candle
            else:
                start = boundary - pd.Timedelta(minutes=minutes_before)
                selected = [c for c in candles_1m if (c[0] > start or (not exclude_start and c[0] >= start)) and c[0] <= boundary]

            if len(selected) > 0:
                agg_open = float(selected[0][1])
                agg_high = max(float(c[2]) for c in selected)
                agg_low = min(float(c[3]) for c in selected)
                agg_close = float(selected[-1][4])

                print(f"\n📊 {method_name} ({len(selected)}개 1분봉):")
                print(f"  Open:  {agg_open:>10.2f} {'✅' if abs(agg_open - db_open) < 0.01 else '❌'}")
                print(f"  High:  {agg_high:>10.2f} {'✅' if abs(agg_high - db_high) < 0.01 else '❌'}")
                print(f"  Low:   {agg_low:>10.2f} {'✅' if abs(agg_low - db_low) < 0.01 else '❌'}")
                print(f"  Close: {agg_close:>10.2f} {'✅' if abs(agg_close - db_close) < 0.01 else '❌'}")

                if abs(agg_close - db_close) < 0.01:
                    print(f"  ➡️ 이 방법이 DB 5분봉과 일치!")
                    print(f"  포함된 1분봉 시간:")
                    for c in selected:
                        print(f"    - {str(c[0])[:19]}: close={float(c[4]):>10.2f}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_db_5m_aggregation())
