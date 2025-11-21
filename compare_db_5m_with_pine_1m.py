"""
DB 5분봉과 Pine Script CSV 1분봉을 정확히 비교
Pine Script 5분봉 = (boundary-5 < time <= boundary-1) + boundary 의 5개 1분봉 집계
"""

import asyncio
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import text
from shared.database.session import create_async_engine
from BACKTEST.config import get_shared_settings


async def compare_db_5m_with_pine_resamp():
    """DB 5분봉 vs Pine Script 1분봉 재집계 비교"""

    print("=" * 100)
    print("DB 5분봉 vs Pine Script 1분봉 재집계 - 정확한 비교")
    print("=" * 100)

    # Pine Script CSV 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 1_8f411.csv"
    df_pine = pd.read_csv(csv_path)
    df_pine['time'] = pd.to_datetime(df_pine['time'], unit='s', utc=True)

    # TimescaleDB 연결
    settings = get_shared_settings()
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    # DB 5분봉 조회 (20:40~21:00)
    start_time = datetime(2025, 11, 16, 20, 40, 0, tzinfo=timezone.utc)
    end_time = datetime(2025, 11, 16, 21, 0, 0, tzinfo=timezone.utc)

    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT time, open, high, low, close, bb_state
                FROM okx_candles_5m
                WHERE symbol = 'BTCUSDT'
                  AND time >= :start_time
                  AND time <= :end_time
                ORDER BY time ASC
            """),
            {'start_time': start_time, 'end_time': end_time}
        )
        db_candles = result.fetchall()

    print(f"\n📊 비교 결과:")
    print(f"{'Time':<20} {'DB Close':>12} {'DB BB':>8} {'Pine Close':>12} {'Pine BB':>8} {'Close Δ':>10} {'BB Match':>10}")
    print("-" * 100)

    matches = 0
    mismatches = 0

    for row in db_candles:
        ts = row[0]
        db_close = float(row[4])
        db_bb = int(row[5]) if row[5] is not None else 0

        # Pine Script: (boundary-5 < time <= boundary-1) + boundary 방식으로 재집계
        start_1m = ts - pd.Timedelta(minutes=5)
        end_1m_before = ts - pd.Timedelta(minutes=1)

        # 1단계: boundary-5 < time <= boundary-1
        mask1 = (df_pine['time'] > start_1m) & (df_pine['time'] <= end_1m_before)
        candles_before = df_pine[mask1].sort_values('time')

        # 2단계: boundary 시간 추가
        boundary_candle = df_pine[df_pine['time'] == ts]

        # 결합
        if not boundary_candle.empty:
            all_candles = pd.concat([candles_before, boundary_candle])
        else:
            all_candles = candles_before

        if len(all_candles) == 5:
            # 5분봉 집계
            pine_open = float(all_candles.iloc[0]['open'])
            pine_high = float(all_candles['high'].max())
            pine_low = float(all_candles['low'].min())
            pine_close = float(all_candles.iloc[-1]['close'])
            pine_bb = int(all_candles.iloc[-1]['BB_state_MTF'])  # 마지막 1분봉의 BB_state_MTF

            close_diff = db_close - pine_close
            bb_match = "✅" if db_bb == pine_bb else "❌"

            if db_bb == pine_bb:
                matches += 1
            else:
                mismatches += 1

            print(f"{str(ts)[:19]:<20} {db_close:>12.2f} {db_bb:>8} {pine_close:>12.2f} {pine_bb:>8} {close_diff:>10.2f} {bb_match:>10}")
        else:
            print(f"{str(ts)[:19]:<20} {db_close:>12.2f} {db_bb:>8} {'N/A':>12} {'N/A':>8} {'N/A':>10} {'⚠️':>10} (Pine 1분봉 개수: {len(all_candles)})")

    print("\n" + "=" * 100)
    print(f"✅ BB_State 일치: {matches}개")
    print(f"❌ BB_State 불일치: {mismatches}개")

    if matches + mismatches > 0:
        match_rate = matches / (matches + mismatches) * 100
        print(f"\n📊 일치율: {match_rate:.1f}%")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(compare_db_5m_with_pine_resamp())
