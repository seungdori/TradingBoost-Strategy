"""
okx_candles 테이블의 실제 데이터 확인
"""

import asyncio
from sqlalchemy import text
from shared.database.session import create_async_engine
from BACKTEST.config import get_shared_settings

async def check_data():
    """데이터 확인"""

    print("=" * 100)
    print("okx_candles 테이블 데이터 확인")
    print("=" * 100)

    settings = get_shared_settings()
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    tables = ['okx_candles_1m', 'okx_candles_5m', 'okx_candles_15m']

    async with engine.begin() as conn:
        for table in tables:
            print(f"\n{'='*100}")
            print(f"테이블: {table}")
            print(f"{'='*100}")

            # 총 레코드 수
            result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            print(f"\n📊 총 레코드: {count:,}개")

            # 고유 심볼 조회
            result = await conn.execute(
                text(f"""
                    SELECT DISTINCT symbol
                    FROM {table}
                    ORDER BY symbol
                    LIMIT 10
                """)
            )
            symbols = [row[0] for row in result.fetchall()]
            print(f"\n🎯 심볼 ({len(symbols)}개):")
            for sym in symbols:
                print(f"   - {sym}")

            # 샘플 데이터 (최근 5개)
            if count > 0:
                result = await conn.execute(
                    text(f"""
                        SELECT time, symbol, open, high, low, close, volume, bb_state
                        FROM {table}
                        ORDER BY time DESC
                        LIMIT 5
                    """)
                )
                rows = result.fetchall()

                print(f"\n📋 최근 데이터 (5개):")
                print(f"{'Time':<20} {'Symbol':<15} {'Close':>10} {'BB_State':>10}")
                print("-" * 70)
                for row in rows:
                    time = str(row[0])[:19]
                    symbol = row[1]
                    close = float(row[5])
                    bb_state = row[7] if row[7] is not None else 0
                    print(f"{time:<20} {symbol:<15} {close:>10.2f} {bb_state:>10}")


if __name__ == "__main__":
    asyncio.run(check_data())
