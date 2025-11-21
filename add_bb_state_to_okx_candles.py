"""
okx_candles 테이블에 bb_state 컬럼 추가 및 계산
"""

import asyncio
from sqlalchemy import text
from shared.database.session import create_async_engine
from BACKTEST.config import get_shared_settings

async def add_bb_state_column():
    """bb_state 컬럼 추가"""

    print("=" * 100)
    print("BB_State 컬럼 추가")
    print("=" * 100)

    settings = get_shared_settings()
    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"
    engine = create_async_engine(db_url)

    # 추가할 테이블들
    tables = [
        'okx_candles_1m',
        'okx_candles_5m',
        'okx_candles_15m',
        'okx_candles_30m',
        'okx_candles_1h',
        'okx_candles_4h',
    ]

    async with engine.begin() as conn:
        for table in tables:
            print(f"\n📊 {table} 처리 중...")

            # bb_state 컬럼 추가
            try:
                await conn.execute(
                    text(f"""
                        ALTER TABLE {table}
                        ADD COLUMN IF NOT EXISTS bb_state INTEGER DEFAULT 0
                    """)
                )
                print(f"   ✅ bb_state 컬럼 추가 완료")
            except Exception as e:
                print(f"   ⚠️  컬럼 추가 실패 (이미 존재할 수 있음): {e}")

            # 인덱스 추가
            try:
                await conn.execute(
                    text(f"""
                        CREATE INDEX IF NOT EXISTS idx_{table}_bb_state
                        ON {table} (symbol, bb_state, time DESC)
                    """)
                )
                print(f"   ✅ 인덱스 추가 완료")
            except Exception as e:
                print(f"   ⚠️  인덱스 추가 실패: {e}")

    print("\n✅ 모든 테이블 처리 완료")


if __name__ == "__main__":
    asyncio.run(add_bb_state_column())
