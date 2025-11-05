#!/usr/bin/env python3
"""
DB에 UserIdentifierMapping 데이터가 있는지 확인
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select
from shared.database.session import DatabaseConfig
from shared.database.models import UserIdentifierMapping


async def check_mapping():
    """매핑 데이터 확인"""
    print("=" * 60)
    print("UserIdentifierMapping 데이터 확인")
    print("=" * 60)

    session_factory = DatabaseConfig.get_session_factory()

    async with session_factory() as db_session:
        # OKX UID로 조회
        okx_uid = "586156710277369942"
        print(f"\n🔍 OKX UID로 조회: {okx_uid}")

        stmt = select(UserIdentifierMapping).where(
            UserIdentifierMapping.okx_uid == okx_uid,
            UserIdentifierMapping.is_active == 1
        )
        result = await db_session.execute(stmt)
        mapping = result.scalar_one_or_none()

        if mapping:
            print(f"✅ 매핑 찾음!")
            print(f"   - user_id: {mapping.user_id}")
            print(f"   - telegram_id: {mapping.telegram_id}")
            print(f"   - okx_uid: {mapping.okx_uid}")
            print(f"   - is_active: {mapping.is_active}")
        else:
            print(f"❌ 매핑을 찾을 수 없습니다.")

            # 전체 데이터 개수 확인
            stmt_count = select(UserIdentifierMapping)
            result_count = await db_session.execute(stmt_count)
            all_mappings = result_count.scalars().all()
            print(f"\n📊 전체 매핑 개수: {len(all_mappings)}")

            if all_mappings:
                print(f"\n샘플 데이터 (최대 5개):")
                for i, m in enumerate(all_mappings[:5], 1):
                    print(f"  {i}. user_id={m.user_id}, telegram_id={m.telegram_id}, okx_uid={m.okx_uid}, is_active={m.is_active}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(check_mapping())
