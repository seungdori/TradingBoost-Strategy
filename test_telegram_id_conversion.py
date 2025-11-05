#!/usr/bin/env python3
"""
Telegram ID 변환 테스트 스크립트

OKX UID → Telegram ID 변환이 정상적으로 작동하는지 확인
"""
import asyncio
import sys
import os

# 프로젝트 루트를 Python path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from HYPERRSI.telegram_message import get_telegram_id


async def test_telegram_id_conversion():
    """Telegram ID 변환 테스트"""

    # 테스트 케이스
    test_cases = [
        ("586156710277369942", "OKX UID (18자리)"),
        ("123456789", "Telegram ID (9자리)"),
    ]

    print("=" * 60)
    print("Telegram ID 변환 테스트 시작")
    print("=" * 60)

    for identifier, description in test_cases:
        print(f"\n🔍 테스트: {description}")
        print(f"   입력: {identifier}")

        try:
            result = await get_telegram_id(identifier)
            print(f"   ✅ 결과: {result}")
        except Exception as e:
            print(f"   ❌ 에러: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_telegram_id_conversion())
