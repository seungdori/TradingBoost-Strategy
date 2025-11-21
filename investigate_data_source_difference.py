"""
DB 5분봉과 Pine Script CSV의 데이터 소스 차이 분석
"""

import asyncio
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import text
from shared.database.session import create_async_engine
from BACKTEST.config import get_shared_settings


async def investigate_data_difference():
    """DB 5분봉 vs Pine Script CSV 데이터 소스 차이 분석"""

    print("=" * 100)
    print("DB 5분봉 vs Pine Script CSV - 데이터 소스 차이 분석")
    print("=" * 100)

    # Pine Script CSV 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 1_8f411.csv"
    df_pine = pd.read_csv(csv_path)
    df_pine['time'] = pd.to_datetime(df_pine['time'], unit='s', utc=True)

    # TimescaleDB 연결
    settings = get_shared_settings()
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    # 분석 기간: 20:40~21:00 (불일치 집중 구간)
    start_time = datetime(2025, 11, 16, 20, 40, 0, tzinfo=timezone.utc)
    end_time = datetime(2025, 11, 16, 21, 0, 0, tzinfo=timezone.utc)

    # 1. DB 5분봉 데이터 조회
    print("\n📊 DB 5분봉 데이터:")
    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT time, open, high, low, close, volume
                FROM okx_candles_5m
                WHERE symbol = 'BTCUSDT'
                  AND time >= :start_time
                  AND time <= :end_time
                ORDER BY time ASC
            """),
            {'start_time': start_time, 'end_time': end_time}
        )
        db_candles = result.fetchall()

    print(f"{'Time':<20} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10}")
    print("-" * 70)
    for row in db_candles:
        time = str(row[0])[:19]
        open_price = float(row[1])
        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
        print(f"{time:<20} {open_price:>10.2f} {high:>10.2f} {low:>10.2f} {close:>10.2f}")

    # 2. Pine Script CSV에서 5분 경계 시간의 1분봉 데이터 조회
    print("\n📊 Pine Script CSV - 5분 경계 시간의 1분봉:")
    print(f"{'Time':<20} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10}")
    print("-" * 70)

    five_min_times = []
    for row in db_candles:
        ts = row[0]
        five_min_times.append(ts)

        pine_row = df_pine[df_pine['time'] == ts]
        if not pine_row.empty:
            open_price = float(pine_row['open'].values[0])
            high = float(pine_row['high'].values[0])
            low = float(pine_row['low'].values[0])
            close = float(pine_row['close'].values[0])
            print(f"{str(ts)[:19]:<20} {open_price:>10.2f} {high:>10.2f} {low:>10.2f} {close:>10.2f}")

    # 3. 1분봉 5개를 집계해서 5분봉으로 만들어보기
    print("\n📊 Pine Script CSV 1분봉 5개 집계 → 5분봉 재구성:")
    print(f"{'Time':<20} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10}")
    print("-" * 70)

    for five_min_time in five_min_times:
        # 5분 구간의 1분봉 5개 찾기 (20:45이면 20:41~20:45)
        end_1m = five_min_time
        start_1m = five_min_time - pd.Timedelta(minutes=5)

        # Pine CSV에서 해당 구간의 1분봉 가져오기 (start_1m 포함)
        mask = (df_pine['time'] >= start_1m) & (df_pine['time'] < end_1m)
        candles_1m = df_pine[mask].sort_values('time')

        # 마지막 1분봉 추가 (경계값)
        boundary_candle = df_pine[df_pine['time'] == end_1m]
        if not boundary_candle.empty:
            candles_1m = pd.concat([candles_1m, boundary_candle])

        if len(candles_1m) == 5:
            # 5분봉으로 집계
            resampled_open = float(candles_1m.iloc[0]['open'])
            resampled_high = float(candles_1m['high'].max())
            resampled_low = float(candles_1m['low'].min())
            resampled_close = float(candles_1m.iloc[-1]['close'])

            print(f"{str(five_min_time)[:19]:<20} {resampled_open:>10.2f} {resampled_high:>10.2f} {resampled_low:>10.2f} {resampled_close:>10.2f}")
        else:
            print(f"{str(five_min_time)[:19]:<20} ⚠️  1분봉 개수: {len(candles_1m)}")

    # 4. 차이 비교
    print("\n📊 차이 비교:")
    print(f"{'Time':<20} {'DB Close':>12} {'Pine 1분':>12} {'Pine 집계':>12} {'DB-Pine1':>10} {'DB-Pine집계':>13}")
    print("-" * 95)

    for i, row in enumerate(db_candles):
        ts = row[0]
        db_close = float(row[4])

        # Pine 1분봉 경계값
        pine_row = df_pine[df_pine['time'] == ts]
        pine_1m_close = float(pine_row['close'].values[0]) if not pine_row.empty else None

        # Pine 1분봉 5개 집계값
        end_1m = ts
        start_1m = ts - pd.Timedelta(minutes=5)
        mask = (df_pine['time'] >= start_1m) & (df_pine['time'] < end_1m)
        candles_1m = df_pine[mask].sort_values('time')
        boundary_candle = df_pine[df_pine['time'] == end_1m]
        if not boundary_candle.empty:
            candles_1m = pd.concat([candles_1m, boundary_candle])

        pine_resampled_close = float(candles_1m.iloc[-1]['close']) if len(candles_1m) == 5 else None

        diff_1m = db_close - pine_1m_close if pine_1m_close else None
        diff_resampled = db_close - pine_resampled_close if pine_resampled_close else None

        pine_1m_str = f"{pine_1m_close:>12.2f}" if pine_1m_close else "N/A".rjust(12)
        pine_resamp_str = f"{pine_resampled_close:>12.2f}" if pine_resampled_close else "N/A".rjust(12)
        diff_1m_str = f"{diff_1m:>10.2f}" if diff_1m else "N/A".rjust(10)
        diff_resamp_str = f"{diff_resampled:>13.2f}" if diff_resampled else "N/A".rjust(13)

        print(f"{str(ts)[:19]:<20} {db_close:>12.2f} {pine_1m_str} {pine_resamp_str} {diff_1m_str} {diff_resamp_str}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(investigate_data_difference())
