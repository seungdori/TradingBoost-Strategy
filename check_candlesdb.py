#!/usr/bin/env python3
"""
candlesdb 데이터베이스 확인
"""

import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# candlesdb 연결
DB_URL = "postgresql+asyncpg://tradeuser:SecurePassword123@158.247.218.188:5432/candlesdb"


async def check_candlesdb():
    """candlesdb 확인"""

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        print("=" * 80)
        print("📋 candlesdb 데이터베이스 테이블")
        print("=" * 80)
        print()

        # Public 테이블 조회
        query = text("""
            SELECT
                tablename,
                pg_size_pretty(pg_total_relation_size('public.' || tablename)) AS size
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)
        result = await session.execute(query)
        rows = result.fetchall()

        print(f"{'Table':<40} {'Size'}")
        print(f"{'-'*60}")

        for row in rows:
            print(f"{row.tablename:<40} {row.size}")

        print()
        print(f"Total: {len(rows)} tables")
        print()

        # btc_usdt 테이블이 있는지 확인
        if any(row.tablename == 'btc_usdt' for row in rows):
            print("=" * 80)
            print("✅ btc_usdt 테이블 발견! 컬럼 구조 확인")
            print("=" * 80)
            print()

            # 컬럼 정보 확인
            query_columns = text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                    AND table_name = 'btc_usdt'
                ORDER BY ordinal_position
            """)
            result = await session.execute(query_columns)
            cols = result.fetchall()

            print(f"{'Column':<30} {'Type'}")
            print(f"{'-'*60}")
            for col in cols:
                print(f"{col.column_name:<30} {col.data_type}")

            print()

    await engine.dispose()


async def main():
    try:
        await check_candlesdb()
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
