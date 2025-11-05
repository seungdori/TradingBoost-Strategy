#!/usr/bin/env python3
"""텔레그램 ID 중복 문제 해결 스크립트"""

import asyncio
import sys
from shared.database.session import get_db, init_db
from shared.database.models import User
from sqlalchemy import select, update, delete
from datetime import datetime

async def fix_telegram_duplicate(telegram_id: str = "1709556958"):
    """텔레그램 ID 중복 문제를 해결합니다."""

    print("=" * 80)
    print("🔧 텔레그램 ID 중복 문제 해결")
    print("=" * 80)

    # DB 초기화
    await init_db()

    async for db in get_db():
        try:
            # 1. 현재 telegram_id를 사용 중인 사용자 찾기
            print(f"\n📱 텔레그램 ID: {telegram_id}")
            print("-" * 80)

            # 해당 텔레그램 ID를 가진 모든 사용자 조회
            result = await db.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            existing_users = result.scalars().all()

            if existing_users:
                print(f"\n현재 이 텔레그램 ID를 사용 중인 사용자:")
                for user in existing_users:
                    print(f"   - OKX UID: {user.okx_uid}")
                    print(f"     생성일: {user.created_at}")
                    print(f"     업데이트: {user.updated_at}")
                    print(f"     상태: {'활성' if user.is_active else '비활성'}")
            else:
                print("❌ 해당 텔레그램 ID를 사용하는 사용자가 없습니다.")
                return

            # 2. 메인 계정과 서브 계정 확인
            main_uid = "586156710277369942"  # 메인 계정
            sub_uid = "587662504768345929"   # 서브 계정

            print("\n" + "=" * 80)
            print("📊 계정 상태 확인")
            print("-" * 80)

            # 메인 계정 조회
            main_result = await db.execute(
                select(User).where(User.okx_uid == main_uid)
            )
            main_user = main_result.scalar_one_or_none()

            # 서브 계정 조회
            sub_result = await db.execute(
                select(User).where(User.okx_uid == sub_uid)
            )
            sub_user = sub_result.scalar_one_or_none()

            print(f"\n메인 계정 ({main_uid}):")
            if main_user:
                print(f"   텔레그램 ID: {main_user.telegram_id}")
                print(f"   상태: 등록됨")
            else:
                print(f"   상태: 미등록")

            print(f"\n서브 계정 ({sub_uid}):")
            if sub_user:
                print(f"   텔레그램 ID: {sub_user.telegram_id}")
                print(f"   상태: 등록됨")
            else:
                print(f"   상태: 미등록")

            # 3. 해결 방법 제시
            print("\n" + "=" * 80)
            print("💡 해결 옵션")
            print("=" * 80)

            print("\n1. 서브 계정의 텔레그램 ID를 제거하고 메인 계정에 연결")
            print("2. 메인 계정을 별도의 텔레그램 ID로 연결")
            print("3. 현재 상태 유지 (서브 계정만 사용)")

            choice = input("\n선택하세요 (1/2/3): ")

            if choice == "1":
                # 옵션 1: 서브 계정의 텔레그램 ID를 제거하고 메인 계정에 연결
                if sub_user and sub_user.telegram_id == telegram_id:
                    # 서브 계정의 텔레그램 ID 제거
                    await db.execute(
                        update(User)
                        .where(User.okx_uid == sub_uid)
                        .values(telegram_id=None, updated_at=datetime.now())
                    )
                    print(f"✅ 서브 계정({sub_uid})의 텔레그램 ID 제거됨")

                # 메인 계정이 없으면 생성
                if not main_user:
                    new_user = User(
                        okx_uid=main_uid,
                        telegram_id=telegram_id,
                        is_active=True,
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    db.add(new_user)
                    print(f"✅ 메인 계정({main_uid}) 생성 및 텔레그램 ID 연결됨")
                else:
                    # 메인 계정에 텔레그램 ID 연결
                    await db.execute(
                        update(User)
                        .where(User.okx_uid == main_uid)
                        .values(telegram_id=telegram_id, updated_at=datetime.now())
                    )
                    print(f"✅ 메인 계정({main_uid})에 텔레그램 ID 연결됨")

                await db.commit()
                print("\n✅ 변경사항이 저장되었습니다.")
                print("이제 메인 계정으로 봇을 사용할 수 있습니다.")

            elif choice == "2":
                # 옵션 2: 메인 계정을 다른 텔레그램 ID로 연결
                new_telegram_id = input("메인 계정에 사용할 새 텔레그램 ID 입력: ")

                if not main_user:
                    new_user = User(
                        okx_uid=main_uid,
                        telegram_id=new_telegram_id,
                        is_active=True,
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )
                    db.add(new_user)
                    print(f"✅ 메인 계정({main_uid}) 생성됨")
                else:
                    await db.execute(
                        update(User)
                        .where(User.okx_uid == main_uid)
                        .values(telegram_id=new_telegram_id, updated_at=datetime.now())
                    )
                    print(f"✅ 메인 계정({main_uid})에 새 텔레그램 ID 연결됨")

                await db.commit()
                print("\n✅ 변경사항이 저장되었습니다.")
                print(f"메인 계정은 텔레그램 ID {new_telegram_id}로 사용하세요.")

            elif choice == "3":
                # 옵션 3: 현재 상태 유지
                print("\n현재 상태를 유지합니다.")
                print("서브 계정으로 계속 사용하시면 됩니다.")

                # 서브 계정으로 자금 이체 필요 안내
                print("\n💡 권장사항:")
                print("1. OKX에서 메인 계정 → 서브 계정으로 자금 이체")
                print(f"   From: Main account ({main_uid})")
                print(f"   To: Sub account ({sub_uid})")
                print("   Account: Trading account")
                print("2. 충분한 USDT를 이체 후 봇 사용")

        except Exception as e:
            print(f"\n❌ 오류 발생: {str(e)}")
            await db.rollback()
            import traceback
            traceback.print_exc()
        finally:
            await db.close()

    print("\n" + "=" * 80)
    print("✅ 완료")
    print("=" * 80)

if __name__ == "__main__":
    telegram_id = sys.argv[1] if len(sys.argv) > 1 else "1709556958"
    asyncio.run(fix_telegram_duplicate(telegram_id))