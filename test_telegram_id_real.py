#!/usr/bin/env python3
"""
실제 DB 데이터로 Telegram ID 변환 테스트
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from HYPERRSI.telegram_message import get_telegram_id


async def test_real_data():
    """실제 DB 데이터로 테스트"""

    test_cases = [
        ("518796558012178692", "DB에 있는 OKX UID"),
        ("586156710277369942", "DB에 없는 OKX UID (ORDER_BACKEND fallback 테스트)"),
        ("1709556958", "Telegram ID (11자리 이하)"),
    ]

    print("=" * 70)
    print("실제 DB 데이터로 Telegram ID 변환 테스트")
    print("=" * 70)

    for identifier, description in test_cases:
        print(f"\n🔍 {description}")
        print(f"   입력: {identifier}")

        try:
            result = await get_telegram_id(identifier)
            if result:
                print(f"   ✅ 결과: {result}")
            else:
                print(f"   ⚠️  결과: None (매핑 없음 또는 ORDER_BACKEND 조회 실패)")
        except Exception as e:
            print(f"   ❌ 에러: {e}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(test_real_data())
