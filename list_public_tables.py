#!/usr/bin/env python3
"""
TimescaleDB public 스키마 테이블만 확인
"""

import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DB_URL = "postgresql+asyncpg://tradeuser:SecurePassword123@158.247.218.188:5432/tradedb"


async def list_public_tables():
    """public 스키마 테이블 확인"""

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        print("=" * 80)
        print("📋 Public 스키마 테이블")
        print("=" * 80)
        print()

        # Public 스키마 테이블만 조회
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

    await engine.dispose()


async def main():
    try:
        await list_public_tables()
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
