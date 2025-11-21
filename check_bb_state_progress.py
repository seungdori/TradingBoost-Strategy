"""
BB_State 계산 진행상황 확인
"""

import asyncio
from sqlalchemy import text
from shared.database.session import create_async_engine
from BACKTEST.config import get_shared_settings

async def check_progress():
    """진행상황 확인"""

    print("=" * 100)
    print("BB_State 계산 진행상황")
    print("=" * 100)

    settings = get_shared_settings()
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    tables = ['okx_candles_1m', 'okx_candles_5m', 'okx_candles_15m']

    async with engine.begin() as conn:
        for table in tables:
            print(f"\n{'='*80}")
            print(f"테이블: {table}")
            print(f"{'='*80}")

            # 총 레코드 수
            result = await conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE symbol = 'BTCUSDT'")
            )
            total = result.scalar()

            # bb_state != 0인 레코드 수
            result = await conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE symbol = 'BTCUSDT' AND bb_state != 0")
            )
            calculated = result.scalar()

            percentage = (calculated / total * 100) if total > 0 else 0

            print(f"\n📊 총 레코드: {total:,}개")
            print(f"✅ 계산 완료: {calculated:,}개 ({percentage:.1f}%)")

            # 최근 계산된 데이터 샘플
            result = await conn.execute(
                text(f"""
                    SELECT time, close, bb_state
                    FROM {table}
                    WHERE symbol = 'BTCUSDT' AND bb_state != 0
                    ORDER BY time DESC
                    LIMIT 5
                """)
            )
            rows = result.fetchall()

            if rows:
                print(f"\n최근 계산된 데이터:")
                print(f"{'Time':<20} {'Close':>10} {'BB_State':>10}")
                print("-" * 45)
                for row in rows:
                    time = str(row[0])[:19]
                    close = float(row[1])
                    bb_state = row[2]
                    print(f"{time:<20} {close:>10.2f} {bb_state:>10}")

if __name__ == "__main__":
    asyncio.run(check_progress())
