"""
TimescaleDB 테이블 구조 확인
"""

import asyncio
from sqlalchemy import text
from shared.database.session import create_async_engine
from BACKTEST.config import get_shared_settings

async def check_timescale_structure():
    """TimescaleDB 테이블 구조 확인"""

    print("=" * 100)
    print("TimescaleDB 테이블 구조 확인")
    print("=" * 100)

    settings = get_shared_settings()

    db_url = f"postgresql+asyncpg://{settings.TIMESCALE_USER}:{settings.TIMESCALE_PASSWORD}@{settings.TIMESCALE_HOST}:{settings.TIMESCALE_PORT}/{settings.TIMESCALE_DATABASE}"

    print(f"\n📊 연결 정보:")
    print(f"   Host: {settings.TIMESCALE_HOST}")
    print(f"   Port: {settings.TIMESCALE_PORT}")
    print(f"   Database: {settings.TIMESCALE_DATABASE}")

    engine = create_async_engine(db_url)

    async with engine.begin() as conn:
        # 모든 테이블 조회
        result = await conn.execute(
            text("""
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
            """)
        )

        tables = [row[0] for row in result]

        print(f"\n📋 전체 테이블 목록 ({len(tables)}개):")
        for table in tables:
            print(f"   - {table}")

        # okx_candles 관련 테이블 필터링
        okx_candles_tables = [t for t in tables if 'okx_candles' in t or 'candle' in t]

        print(f"\n🎯 캔들 관련 테이블 ({len(okx_candles_tables)}개):")
        for table in okx_candles_tables:
            print(f"   - {table}")

        # 각 캔들 테이블의 구조 확인
        for table in okx_candles_tables[:5]:  # 처음 5개만
            print(f"\n" + "=" * 100)
            print(f"테이블: {table}")
            print("=" * 100)

            # 컬럼 정보
            result = await conn.execute(
                text("""
                    SELECT column_name, data_type, character_maximum_length, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = :table_name
                    ORDER BY ordinal_position
                """),
                {'table_name': table}
            )

            columns = result.fetchall()

            print(f"\n컬럼 ({len(columns)}개):")
            for col in columns:
                print(f"   - {col[0]:<20} {col[1]:<20} nullable={col[3]}")

            # 데이터 샘플 (최근 5개) - time 컬럼 사용
            result = await conn.execute(
                text(f"""
                    SELECT * FROM {table}
                    ORDER BY time DESC
                    LIMIT 5
                """)
            )

            rows = result.fetchall()

            if rows:
                print(f"\n샘플 데이터 ({len(rows)}개):")
                cols = result.keys()
                print(f"   컬럼: {', '.join(cols[:8])}")  # 처음 8개 컬럼만
                for row in rows:
                    values = [str(v)[:15] for v in row[:8]]  # 처음 8개 값만
                    print(f"   {', '.join(values)}")

if __name__ == "__main__":
    asyncio.run(check_timescale_structure())
