#!/usr/bin/env python3
"""
TimescaleDB 테이블 목록 확인
"""

import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# 직접 연결 정보 사용
DB_URL = "postgresql+asyncpg://tradeuser:SecurePassword123@158.247.218.188:5432/tradedb"


async def list_tables():
    """테이블 목록 확인"""

    engine = create_async_engine(DB_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        print("=" * 80)
        print("📋 tradedb 데이터베이스 테이블 목록")
        print("=" * 80)
        print()

        # 1. 모든 테이블 조회
        query = text("""
            SELECT
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
            FROM pg_tables
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY schemaname, tablename
        """)
        result = await session.execute(query)
        rows = result.fetchall()

        print(f"{'Schema':<20} {'Table':<40} {'Size'}")
        print(f"{'-'*80}")

        for row in rows:
            print(f"{row.schemaname:<20} {row.tablename:<40} {row.size}")

        print()
        print(f"Total: {len(rows)} tables")
        print()

        # 2. BTC 관련 테이블 찾기
        query_btc = text("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
                AND (
                    tablename LIKE '%btc%'
                    OR tablename LIKE '%candle%'
                    OR tablename LIKE '%kline%'
                )
            ORDER BY tablename
        """)
        result = await session.execute(query_btc)
        btc_tables = result.fetchall()

        if btc_tables:
            print("=" * 80)
            print("🔍 BTC/캔들 관련 테이블")
            print("=" * 80)
            for row in btc_tables:
                print(f"   - {row.tablename}")

                # 각 테이블의 컬럼 정보 확인
                query_columns = text(f"""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = :table_name
                    ORDER BY ordinal_position
                """)
                result_cols = await session.execute(query_columns, {'table_name': row.tablename})
                cols = result_cols.fetchall()

                print(f"     Columns: {', '.join([f'{c.column_name} ({c.data_type})' for c in cols[:5]])}...")
                print()

        # 3. 데이터베이스 이름 확인
        query_db = text("SELECT current_database()")
        result = await session.execute(query_db)
        db_name = result.scalar()
        print(f"Current database: {db_name}")
        print()

    await engine.dispose()


async def main():
    try:
        await list_tables()
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
