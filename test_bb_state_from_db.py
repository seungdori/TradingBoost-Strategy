"""
DB에 저장된 BB_State를 조회해서 Pine Script CSV와 비교
"""

import asyncio
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import text
from shared.database.session import create_async_engine
from BACKTEST.config import get_shared_settings


async def test_bb_state_from_db():
    """DB에서 BB_State 조회 및 비교"""

    print("=" * 100)
    print("DB BB_State vs Pine Script CSV 비교")
    print("=" * 100)

    # Pine Script CSV 로드
    csv_path = "/Users/seunghyun/Downloads/OKX_BTCUSDT.P, 1_8f411.csv"
    df_pine = pd.read_csv(csv_path)
    df_pine['time'] = pd.to_datetime(df_pine['time'], unit='s', utc=True)

    # TimescaleDB 연결
    settings = get_shared_settings()
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    # CSV 시간 범위 확인
    csv_start = df_pine['time'].min()
    csv_end = df_pine['time'].max()
    print(f"\n📅 CSV 시간 범위: {csv_start} ~ {csv_end}")

    # 5분봉 BB_State 조회 (CSV 시간 범위 내)
    async with engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT time, close, bb_state
                FROM okx_candles_5m
                WHERE symbol = 'BTCUSDT'
                  AND time >= :start_time
                  AND time <= :end_time
                  AND bb_state IS NOT NULL
                ORDER BY time ASC
            """),
            {'start_time': csv_start, 'end_time': csv_end}
        )

        rows = result.fetchall()

    if not rows:
        print("⚠️  DB에 BB_State 데이터 없음")
        return

    print(f"\n📊 DB에서 조회된 5분봉 BB_State: {len(rows)}개")

    # 5분봉 시간대만 필터링 (Pine Script CSV는 1분봉)
    # 5분봉 경계 시간만 추출
    five_min_boundaries = []
    for row in rows:
        ts = row[0]
        # 5분 경계인지 확인 (분이 0, 5로 끝남)
        if ts.minute % 5 == 0:
            five_min_boundaries.append({
                'time': ts,
                'close': float(row[1]),
                'bb_state_db': int(row[2])
            })

    print(f"📊 5분 경계 시간: {len(five_min_boundaries)}개")

    # Pine Script CSV와 비교
    matches = 0
    mismatches = 0
    not_found = 0

    print(f"\n{'Time':<20} {'Close':>10} {'DB_BB':>8} {'Pine_BB':>8} {'Match':>8}")
    print("=" * 60)

    for boundary in five_min_boundaries[:50]:  # 처음 50개만
        ts = boundary['time']
        db_bb = boundary['bb_state_db']
        close = boundary['close']

        # Pine Script CSV에서 해당 시간 찾기
        pine_row = df_pine[df_pine['time'] == ts]

        if pine_row.empty:
            not_found += 1
            pine_bb = 'N/A'
            match = '❓'
        else:
            pine_bb = int(pine_row['BB_state_MTF'].values[0])
            if db_bb == pine_bb:
                matches += 1
                match = '✅'
            else:
                mismatches += 1
                match = '❌'

        print(f"{str(ts)[:19]:<20} {close:>10.2f} {db_bb:>8} {pine_bb:>8} {match:>8}")

    print("\n" + "=" * 60)
    print(f"✅ 일치: {matches}개")
    print(f"❌ 불일치: {mismatches}개")
    print(f"❓ 미발견: {not_found}개")

    if matches + mismatches > 0:
        match_rate = matches / (matches + mismatches) * 100
        print(f"\n📊 일치율: {match_rate:.1f}%")


if __name__ == "__main__":
    asyncio.run(test_bb_state_from_db())
