"""
DB 1분봉과 Pine Script CSV 1분봉을 직접 비교
"""

import asyncio
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import text
from shared.database.session import create_async_engine
from BACKTEST.config import get_shared_settings


async def compare_1m_candles_directly():
    """DB 1분봉 vs Pine Script CSV 1분봉 직접 비교"""

    print("=" * 100)
    print("DB 1분봉 vs Pine Script CSV 1분봉 - 직접 비교")
    print("=" * 100)

    # Pine Script CSV 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 1_8f411.csv"
    df_pine = pd.read_csv(csv_path)
    df_pine['time'] = pd.to_datetime(df_pine['time'], unit='s', utc=True)

    # TimescaleDB 연결
    settings = get_shared_settings()
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    # DB 1분봉 조회 (20:40~21:00)
    start_time = datetime(2025, 11, 16, 20, 40, 0, tzinfo=timezone.utc)
    end_time = datetime(2025, 11, 16, 21, 0, 0, tzinfo=timezone.utc)

    async with engine.begin() as conn:
        result = await conn.execute(
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
        db_candles = result.fetchall()

    print(f"\n📊 1분봉 비교 (20:40~21:00):")
    print(f"{'Time':<20} {'DB Close':>12} {'Pine Close':>12} {'Diff':>10} {'Match':>8}")
    print("-" * 70)

    exact_matches = 0
    close_matches = 0  # 소수점 1자리 차이
    mismatches = 0

    for row in db_candles:
        ts = row[0]
        db_close = float(row[4])

        # Pine CSV에서 같은 시간 찾기
        pine_row = df_pine[df_pine['time'] == ts]

        if not pine_row.empty:
            pine_close = float(pine_row['close'].values[0])
            diff = db_close - pine_close

            if abs(diff) < 0.01:
                exact_matches += 1
                match = "✅"
            elif abs(diff) < 1.0:
                close_matches += 1
                match = "🟡"
            else:
                mismatches += 1
                match = "❌"

            print(f"{str(ts)[:19]:<20} {db_close:>12.2f} {pine_close:>12.2f} {diff:>10.2f} {match:>8}")
        else:
            print(f"{str(ts)[:19]:<20} {db_close:>12.2f} {'N/A':>12} {'N/A':>10} {'⚠️':>8}")

    print("\n" + "=" * 70)
    print(f"✅ 정확히 일치: {exact_matches}개")
    print(f"🟡 근접 일치 (<1.0): {close_matches}개")
    print(f"❌ 불일치 (>=1.0): {mismatches}개")

    total = exact_matches + close_matches + mismatches
    if total > 0:
        exact_rate = exact_matches / total * 100
        close_rate = (exact_matches + close_matches) / total * 100
        print(f"\n📊 정확 일치율: {exact_rate:.1f}%")
        print(f"📊 근접 일치율: {close_rate:.1f}%")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(compare_1m_candles_directly())
