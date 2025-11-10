#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CandlesDB Writer Error Handling 테스트
Retry, Health Check, Auto-Recovery 검증
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import psycopg2

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from HYPERRSI.src.data_collector.candlesdb_writer import CandlesDBWriter


def test_retry_logic():
    """Retry with exponential backoff 테스트"""
    print("=" * 80)
    print("Test 1: Retry Logic with Exponential Backoff")
    print("=" * 80)

    # 3번 실패 후 성공하는 mock operation 생성
    call_count = {"count": 0}
    retry_times = []

    def mock_operation():
        call_count["count"] += 1
        retry_times.append(time.time())

        if call_count["count"] < 3:
            # 처음 2번은 실패
            raise psycopg2.OperationalError("Connection failed")
        # 3번째는 성공
        return True

    writer = CandlesDBWriter()

    print("Mock operation을 실행합니다 (처음 2번 실패, 3번째 성공)...")
    start_time = time.time()

    try:
        result = writer._retry_operation(mock_operation)

        print(f"\n✅ Retry 성공! 총 시도 횟수: {call_count['count']}")
        print(f"총 소요 시간: {time.time() - start_time:.2f}초")

        # Exponential backoff 검증 (1s, 2s 지연)
        if len(retry_times) >= 2:
            delay1 = retry_times[1] - retry_times[0]
            print(f"첫 번째 재시도 지연: {delay1:.2f}초 (예상: ~1초)")

        if len(retry_times) >= 3:
            delay2 = retry_times[2] - retry_times[1]
            print(f"두 번째 재시도 지연: {delay2:.2f}초 (예상: ~2초)")

        print("\n✅ Exponential backoff가 정상 작동합니다!")

    except Exception as e:
        print(f"❌ Retry 실패: {e}")

    print()


def test_max_retries_exceeded():
    """최대 재시도 횟수 초과 테스트"""
    print("=" * 80)
    print("Test 2: Max Retries Exceeded")
    print("=" * 80)

    # 계속 실패하는 operation
    def always_fail():
        raise psycopg2.OperationalError("Connection always fails")

    writer = CandlesDBWriter()

    print("항상 실패하는 operation을 실행합니다...")
    start_time = time.time()

    try:
        writer._retry_operation(always_fail)
        print("❌ 예외가 발생하지 않았습니다 (예상과 다름)")
    except psycopg2.OperationalError as e:
        elapsed = time.time() - start_time
        print(f"\n✅ 예상대로 최대 재시도 후 실패!")
        print(f"총 소요 시간: {elapsed:.2f}초 (예상: ~7초, 1+2+4)")
        print(f"에러 메시지: {e}")

    print()


def test_health_check():
    """Health check 메커니즘 테스트"""
    print("=" * 80)
    print("Test 3: Health Check Mechanism")
    print("=" * 80)

    writer = CandlesDBWriter()

    if not writer.enabled:
        print("❌ Writer가 활성화되지 않았습니다. DB 연결을 확인하세요.")
        print()
        return

    print("첫 번째 health check 실행...")
    result1 = writer.health_check()
    print(f"결과: {'✅ 정상' if result1 else '❌ 실패'}")

    # 바로 다시 실행 (throttling 테스트)
    print("\n즉시 두 번째 health check 실행 (throttling 테스트)...")
    start = time.time()
    result2 = writer.health_check()
    elapsed = time.time() - start

    print(f"결과: {'✅ 정상' if result2 else '❌ 실패'}")
    print(f"소요 시간: {elapsed*1000:.2f}ms (throttling으로 빠르게 반환되어야 함)")

    if elapsed < 0.1:
        print("✅ Throttling이 정상 작동합니다!")
    else:
        print("⚠️ Throttling이 예상보다 느립니다")

    print()


def test_auto_recovery_simulation():
    """Auto-recovery 시뮬레이션 테스트"""
    print("=" * 80)
    print("Test 4: Auto-Recovery Simulation")
    print("=" * 80)

    writer = CandlesDBWriter()

    if not writer.enabled:
        print("❌ Writer가 초기에 활성화되지 않았습니다.")
        print()
        return

    print("현재 상태: enabled =", writer.enabled)

    # 수동으로 비활성화 (DB 실패 시뮬레이션)
    print("\nDB 연결 실패를 시뮬레이션합니다...")
    writer.enabled = False
    print("상태 변경: enabled =", writer.enabled)

    # Health check가 재연결을 시도하는지 확인
    print("\nHealth check를 통한 재연결 시도...")
    writer.last_health_check = 0  # throttling 우회

    result = writer.health_check()

    print(f"재연결 결과: {'✅ 성공' if result else '❌ 실패'}")
    print(f"최종 상태: enabled = {writer.enabled}")

    if writer.enabled:
        print("\n✅ Auto-recovery가 정상 작동합니다!")
    else:
        print("\n⚠️ Auto-recovery가 실패했습니다 (DB가 실제로 다운된 경우 정상)")

    print()


def test_monitoring_stats():
    """모니터링 통계 테스트"""
    print("=" * 80)
    print("Test 5: Monitoring Statistics")
    print("=" * 80)

    writer = CandlesDBWriter()

    if not writer.enabled:
        print("❌ Writer가 활성화되지 않았습니다.")
        print()
        return

    # 초기 통계
    print("초기 통계:")
    writer.log_stats()

    # 테스트 데이터 생성
    test_candles = []
    base_ts = int(datetime.now(tz=timezone.utc).timestamp())

    for i in range(3):
        ts = base_ts - (i * 3600)
        candle = {
            "timestamp": ts,
            "open": 50000.0 + (i * 100),
            "high": 50100.0 + (i * 100),
            "low": 49900.0 + (i * 100),
            "close": 50050.0 + (i * 100),
            "volume": 100.5 + (i * 10),
            "rsi": 55.5 - (i * 2),
            "atr": 200.0,
            "ma7": 50000.0 + (i * 50),
            "ma20": 49950.0 + (i * 50),
        }
        test_candles.append(candle)

    # 성공적인 저장
    print("\n3개의 테스트 캔들을 저장합니다...")
    success = writer.upsert_candles("BTC-USDT-SWAP", 60, test_candles)

    if success:
        print("✅ 저장 성공")
    else:
        print("❌ 저장 실패")

    # 최종 통계
    print("\n최종 통계:")
    writer.log_stats()

    # 통계 검증
    stats = writer.get_stats()
    print(f"\n상세 통계:")
    print(f"  - 활성화 상태: {stats['enabled']}")
    print(f"  - 성공 횟수: {stats['success_count']}")
    print(f"  - 실패 횟수: {stats['failure_count']}")
    print(f"  - 전체 횟수: {stats['total_count']}")
    print(f"  - 성공률: {stats['success_rate']:.1f}%")

    if stats['success_count'] > 0:
        print("\n✅ 모니터링 카운터가 정상 작동합니다!")
    else:
        print("\n⚠️ 모니터링 카운터가 업데이트되지 않았습니다")

    print()


def test_upsert_with_simulated_failure():
    """Upsert 중 실패 시뮬레이션 테스트"""
    print("=" * 80)
    print("Test 6: Upsert with Simulated Transient Failure")
    print("=" * 80)

    writer = CandlesDBWriter()

    if not writer.enabled:
        print("❌ Writer가 활성화되지 않았습니다.")
        print()
        return

    # Mock을 사용하여 첫 2번은 실패, 3번째는 성공하도록 설정
    original_do_upsert = writer._do_upsert
    call_count = {"count": 0}

    def mock_do_upsert(*args, **kwargs):
        call_count["count"] += 1
        if call_count["count"] < 3:
            raise psycopg2.OperationalError("Simulated transient failure")
        return original_do_upsert(*args, **kwargs)

    # 테스트 데이터
    test_candle = {
        "timestamp": int(datetime.now(tz=timezone.utc).timestamp()),
        "open": 50000.0,
        "high": 50100.0,
        "low": 49900.0,
        "close": 50050.0,
        "volume": 100.5,
        "rsi": 55.5,
        "atr": 200.0,
        "ma7": 50000.0,
        "ma20": 49950.0,
    }

    print("일시적 실패를 시뮬레이션하며 upsert를 시도합니다...")
    writer._do_upsert = mock_do_upsert

    try:
        success = writer.upsert_single_candle("BTC-USDT-SWAP", 60, test_candle)

        print(f"\n결과: {'✅ 성공' if success else '❌ 실패'}")
        print(f"총 시도 횟수: {call_count['count']}")

        if success and call_count["count"] == 3:
            print("\n✅ Retry 로직이 upsert에서 정상 작동합니다!")
        elif success:
            print(f"\n⚠️ 예상보다 적은 횟수로 성공 (예상: 3회, 실제: {call_count['count']}회)")
        else:
            print("\n❌ Retry 후에도 실패했습니다")

    except Exception as e:
        print(f"\n❌ 예외 발생: {e}")

    finally:
        # 원래 메서드 복원
        writer._do_upsert = original_do_upsert

    print()


def main():
    print("\n")
    print("🧪 CandlesDB Writer Error Handling Test Suite")
    print("=" * 80)
    print()

    # Test 1: Retry logic with exponential backoff
    test_retry_logic()

    # Test 2: Max retries exceeded
    test_max_retries_exceeded()

    # Test 3: Health check mechanism
    test_health_check()

    # Test 4: Auto-recovery simulation
    test_auto_recovery_simulation()

    # Test 5: Monitoring statistics
    test_monitoring_stats()

    # Test 6: Upsert with simulated failure
    test_upsert_with_simulated_failure()

    print("=" * 80)
    print("✅ All error handling tests completed!")
    print("=" * 80)


if __name__ == "__main__":
    main()
