#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Redis Health Check 테스트
"""

import os
import sys
import time
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.config import settings
from shared.database.redis import RedisConnectionManager


def test_redis_connection():
    """Redis 연결 테스트"""
    print("=" * 80)
    print("Test 1: Redis Connection")
    print("=" * 80)

    redis_manager = RedisConnectionManager(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=0,
        password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None
    )

    print(f"Redis 서버: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
    print(f"Database: 0")
    print()

    return redis_manager


def test_ping_sync(redis_manager):
    """동기 ping 테스트"""
    print("=" * 80)
    print("Test 2: Synchronous Ping")
    print("=" * 80)

    try:
        start_time = time.time()
        result = redis_manager.ping_sync()
        elapsed = (time.time() - start_time) * 1000

        if result:
            print(f"✅ Redis ping 성공!")
            print(f"응답 시간: {elapsed:.2f}ms")
        else:
            print(f"❌ Redis ping 실패: 응답이 False")

    except Exception as e:
        print(f"❌ Redis ping 예외 발생: {e}")

    print()


def test_health_check_throttling(redis_manager):
    """Health check throttling 테스트 (동기 버전)"""
    print("=" * 80)
    print("Test 3: Health Check Throttling Simulation")
    print("=" * 80)

    success_count = 0
    failure_count = 0

    print("5번의 health check를 빠르게 실행합니다...")

    for i in range(5):
        try:
            start = time.time()
            result = redis_manager.ping_sync()
            elapsed = (time.time() - start) * 1000

            if result:
                success_count += 1
                print(f"  {i+1}. ✅ 성공 ({elapsed:.2f}ms)")
            else:
                failure_count += 1
                print(f"  {i+1}. ❌ 실패 (ping=False)")

        except Exception as e:
            failure_count += 1
            print(f"  {i+1}. ❌ 예외: {e}")

        # 짧은 대기
        time.sleep(0.1)

    print(f"\n결과: 성공={success_count}, 실패={failure_count}")

    if success_count == 5:
        print("✅ 모든 health check 성공!")
    else:
        print(f"⚠️ {failure_count}개의 health check 실패")

    print()


def test_reconnection_simulation(redis_manager):
    """재연결 시뮬레이션"""
    print("=" * 80)
    print("Test 4: Reconnection Simulation")
    print("=" * 80)

    print("1. 초기 연결 테스트...")
    initial_ping = redis_manager.ping_sync()
    print(f"   초기 연결: {'✅ 성공' if initial_ping else '❌ 실패'}")

    print("\n2. 새로운 연결 생성 시뮬레이션...")
    try:
        # 새로운 연결 생성
        redis_client = redis_manager.get_connection()
        print("   ✅ 새 연결 생성 성공")

        # Ping 테스트
        if redis_client.ping():
            print("   ✅ 새 연결 ping 성공")
        else:
            print("   ❌ 새 연결 ping 실패")

    except Exception as e:
        print(f"   ❌ 재연결 실패: {e}")

    print()


def test_set_get_operations(redis_manager):
    """기본 작업 테스트"""
    print("=" * 80)
    print("Test 5: Basic Redis Operations")
    print("=" * 80)

    try:
        redis_client = redis_manager.get_connection()

        # Set 작업
        test_key = "health_check_test"
        test_value = f"test_{int(time.time())}"

        print(f"SET 작업: {test_key} = {test_value}")
        redis_client.set(test_key, test_value)
        print("✅ SET 성공")

        # Get 작업
        retrieved = redis_client.get(test_key)
        if retrieved:
            # bytes를 문자열로 디코드
            retrieved_str = retrieved.decode('utf-8') if isinstance(retrieved, bytes) else retrieved
            print(f"GET 작업: {test_key} = {retrieved_str}")

            if retrieved_str == test_value:
                print("✅ GET 성공 - 값이 일치합니다!")
            else:
                print(f"⚠️ 값 불일치: 예상={test_value}, 실제={retrieved_str}")
        else:
            print("❌ GET 실패: 값이 없습니다")

        # Cleanup
        redis_client.delete(test_key)
        print(f"✅ 테스트 키 삭제 완료")

    except Exception as e:
        print(f"❌ Redis 작업 중 오류: {e}")

    print()


def test_monitoring_stats():
    """모니터링 통계 시뮬레이션"""
    print("=" * 80)
    print("Test 6: Monitoring Statistics Simulation")
    print("=" * 80)

    redis_manager = RedisConnectionManager(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=0
    )

    success_count = 0
    failure_count = 0

    print("10번의 health check를 실행하여 통계를 시뮬레이션합니다...")

    for i in range(10):
        try:
            if redis_manager.ping_sync():
                success_count += 1
            else:
                failure_count += 1
        except Exception:
            failure_count += 1

        time.sleep(0.05)  # 50ms 간격

    total_checks = success_count + failure_count
    success_rate = (success_count / total_checks * 100) if total_checks > 0 else 0.0

    print(f"\n📊 Redis Stats:")
    print(f"  - 성공: {success_count}")
    print(f"  - 실패: {failure_count}")
    print(f"  - 전체: {total_checks}")
    print(f"  - 성공률: {success_rate:.1f}%")

    if success_rate >= 90:
        print("\n✅ Redis 연결이 안정적입니다!")
    elif success_rate >= 70:
        print("\n⚠️ Redis 연결이 불안정합니다")
    else:
        print("\n❌ Redis 연결에 심각한 문제가 있습니다")

    print()


def main():
    print("\n")
    print("🧪 Redis Health Check Test Suite")
    print("=" * 80)
    print()

    # Test 1: Connection
    redis_manager = test_redis_connection()

    # Test 2: Synchronous ping
    test_ping_sync(redis_manager)

    # Test 3: Health check throttling
    test_health_check_throttling(redis_manager)

    # Test 4: Reconnection
    test_reconnection_simulation(redis_manager)

    # Test 5: Basic operations
    test_set_get_operations(redis_manager)

    # Test 6: Monitoring stats
    test_monitoring_stats()

    # Cleanup
    redis_manager.close_sync()

    print("=" * 80)
    print("✅ All Redis health check tests completed!")
    print("=" * 80)


if __name__ == "__main__":
    main()
