#!/usr/bin/env python3
"""텔레그램 ID 중복 문제를 SQL로 직접 해결하는 스크립트"""

import asyncio
import sys
import asyncpg
from datetime import datetime
from shared.config import get_settings

async def fix_telegram_duplicate_sql():
    """SQL을 직접 사용하여 텔레그램 ID 중복 문제를 해결합니다."""

    print("=" * 80)
    print("🔧 텔레그램 ID 중복 문제 해결 (SQL)")
    print("=" * 80)

    settings = get_settings()

    # DATABASE_URL에서 연결 정보 추출
    database_url = settings.DATABASE_URL
    if not database_url:
        print("❌ DATABASE_URL이 설정되지 않았습니다.")
        print("Redis 기반 해결 방법을 사용하겠습니다.")
        return await fix_with_redis()

    # PostgreSQL 연결
    try:
        conn = await asyncpg.connect(database_url)

        telegram_id = "1709556958"
        main_uid = "586156710277369942"  # 메인 계정
        sub_uid = "587662504768345929"   # 서브 계정

        print(f"\n📱 텔레그램 ID: {telegram_id}")
        print(f"👤 메인 계정 UID: {main_uid}")
        print(f"👤 서브 계정 UID: {sub_uid}")
        print("-" * 80)

        # 1. 현재 상태 확인
        print("\n1️⃣ 현재 데이터베이스 상태 확인...")

        # app_users 테이블의 현재 상태 확인
        query = """
            SELECT okx_uid, telegram_id, created_at, updated_at
            FROM app_users
            WHERE telegram_id = $1 OR okx_uid IN ($2, $3)
        """
        rows = await conn.fetch(query, telegram_id, main_uid, sub_uid)

        if rows:
            print("\n현재 등록된 사용자:")
            for row in rows:
                print(f"   OKX UID: {row['okx_uid']}")
                print(f"   Telegram ID: {row['telegram_id']}")
                print(f"   생성일: {row['created_at']}")
                print(f"   수정일: {row['updated_at']}")
                print()

        # 2. 해결 옵션 제시
        print("\n" + "=" * 80)
        print("💡 해결 방법")
        print("=" * 80)

        print("\n옵션을 선택하세요:")
        print("1. 서브 계정의 텔레그램 ID를 NULL로 변경하고, 메인 계정에 연결")
        print("2. 서브 계정 유지 (현재 상태 유지)")
        print("3. 테이블 구조 확인만 하기")

        choice = input("\n선택 (1/2/3): ")

        if choice == "1":
            print("\n✅ 옵션 1 실행: 메인 계정으로 텔레그램 ID 이전")

            # 트랜잭션 시작
            async with conn.transaction():
                # 1. 서브 계정의 텔레그램 ID를 NULL로 변경
                update_sub = """
                    UPDATE app_users
                    SET telegram_id = NULL, updated_at = NOW()
                    WHERE okx_uid = $1
                """
                await conn.execute(update_sub, sub_uid)
                print(f"   ✅ 서브 계정({sub_uid})의 텔레그램 ID 제거됨")

                # 2. 메인 계정이 있는지 확인
                check_main = """
                    SELECT COUNT(*) as count FROM app_users WHERE okx_uid = $1
                """
                result = await conn.fetchrow(check_main, main_uid)

                if result['count'] == 0:
                    # 메인 계정이 없으면 생성
                    insert_main = """
                        INSERT INTO app_users (okx_uid, telegram_id, created_at, updated_at)
                        VALUES ($1, $2, NOW(), NOW())
                    """
                    await conn.execute(insert_main, main_uid, telegram_id)
                    print(f"   ✅ 메인 계정({main_uid}) 생성 및 텔레그램 ID 연결됨")
                else:
                    # 메인 계정이 있으면 업데이트
                    update_main = """
                        UPDATE app_users
                        SET telegram_id = $1, updated_at = NOW()
                        WHERE okx_uid = $2
                    """
                    await conn.execute(update_main, telegram_id, main_uid)
                    print(f"   ✅ 메인 계정({main_uid})에 텔레그램 ID 연결됨")

            print("\n✅ 변경사항이 저장되었습니다.")
            print("이제 메인 계정으로 봇을 사용할 수 있습니다.")

        elif choice == "2":
            print("\n현재 상태를 유지합니다.")
            print("서브 계정으로 계속 사용하세요.")

        elif choice == "3":
            print("\n📊 테이블 구조 확인:")

            # 테이블 구조 확인
            table_info = """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'app_users'
                ORDER BY ordinal_position
            """
            columns = await conn.fetch(table_info)

            print("\napp_users 테이블 컬럼:")
            for col in columns:
                nullable = "NULL 가능" if col['is_nullable'] == 'YES' else "NOT NULL"
                print(f"   {col['column_name']}: {col['data_type']} ({nullable})")

            # 인덱스 확인
            index_info = """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'app_users'
            """
            indexes = await conn.fetch(index_info)

            print("\n인덱스:")
            for idx in indexes:
                print(f"   {idx['indexname']}")
                if 'telegram_id' in idx['indexdef']:
                    print(f"      -> {idx['indexdef']}")

        await conn.close()

    except Exception as e:
        print(f"\n❌ PostgreSQL 연결 실패: {str(e)}")
        print("Redis 기반 해결 방법을 시도합니다...")
        await fix_with_redis()


async def fix_with_redis():
    """Redis를 사용한 간단한 해결 방법"""
    from shared.database.redis_helper import get_redis_client

    print("\n" + "=" * 80)
    print("🔧 Redis 기반 해결 방법")
    print("=" * 80)

    redis = await get_redis_client()

    main_uid = "586156710277369942"
    sub_uid = "587662504768345929"
    telegram_id = "1709556958"

    print("\n현재 상황:")
    print(f"- 메인 계정 ({main_uid})을 사용하고 싶음")
    print(f"- 텔레그램 ID ({telegram_id})가 서브 계정에 연결됨")

    print("\n해결 방법:")
    print("1. Redis에서 메인 계정 정보를 설정")
    print("2. 서브 계정에서 메인 계정으로 전환")

    choice = input("\n진행하시겠습니까? (y/n): ")

    if choice.lower() == 'y':
        # Redis에 메인 계정 정보 설정
        await redis.set(f"user:{main_uid}:telegram_id", telegram_id)
        await redis.set(f"telegram:{telegram_id}:okx_uid", main_uid)

        # API 키 정보 복사 (있다면)
        api_keys = await redis.get(f"user:{sub_uid}:api_keys")
        if api_keys:
            await redis.set(f"user:{main_uid}:api_keys", api_keys)
            print("✅ API 키 정보가 메인 계정으로 복사되었습니다.")

        print(f"\n✅ Redis에 메인 계정 정보가 설정되었습니다.")
        print(f"이제 메인 계정 ({main_uid})으로 사용할 수 있습니다.")

        print("\n⚠️  주의사항:")
        print("1. OKX에서 메인 계정으로 자금이 있는지 확인하세요.")
        print("2. 봇 설정에서 UID를 메인 계정으로 변경하세요.")
    else:
        print("\n취소되었습니다.")


if __name__ == "__main__":
    asyncio.run(fix_telegram_duplicate_sql())