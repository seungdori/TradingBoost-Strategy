#!/usr/bin/env python3
"""
Logging 통합 테스트

shared/config/logging.py의 로거 기능 검증
"""

import sys
import os
import tempfile
import logging
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)


def test_shared_logging_import():
    """shared 로깅 모듈 import 테스트"""
    print("\n" + "="*80)
    print("1. shared.config.logging import 테스트")
    print("="*80)

    try:
        from shared.config.logging import (
            setup_logger,
            get_logger,
            configure_root_logger,
            create_file_logger,
            create_console_logger,
            add_file_handler,
            setup_json_logger,
            should_log,
            JSONFormatter
        )

        print("✅ setup_logger 함수")
        print("✅ get_logger 함수")
        print("✅ configure_root_logger 함수")
        print("✅ create_file_logger 함수")
        print("✅ create_console_logger 함수")
        print("✅ add_file_handler 함수")
        print("✅ setup_json_logger 함수")
        print("✅ should_log 함수")
        print("✅ JSONFormatter 클래스")

        assert callable(setup_logger), "setup_logger should be callable"
        assert callable(get_logger), "get_logger should be callable"
        assert callable(configure_root_logger), "configure_root_logger should be callable"

        return True

    except Exception as e:
        print(f"❌ 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_basic_logger_creation():
    """기본 로거 생성 테스트"""
    print("\n" + "="*80)
    print("2. 기본 로거 생성 테스트")
    print("="*80)

    try:
        from shared.config.logging import setup_logger, get_logger

        # setup_logger 테스트
        logger1 = setup_logger('test_logger', log_level='DEBUG')
        assert isinstance(logger1, logging.Logger), "Should return Logger instance"
        assert logger1.name == 'test_logger', f"Expected 'test_logger', got {logger1.name}"
        assert logger1.level == logging.DEBUG, f"Expected DEBUG, got {logger1.level}"
        print(f"✅ setup_logger: {logger1.name} (level={logging.getLevelName(logger1.level)})")

        # get_logger 테스트
        logger2 = get_logger('test_app')
        assert isinstance(logger2, logging.Logger), "Should return Logger instance"
        assert logger2.name == 'test_app', f"Expected 'test_app', got {logger2.name}"
        print(f"✅ get_logger: {logger2.name} (level={logging.getLevelName(logger2.level)})")

        return True

    except Exception as e:
        print(f"❌ 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_console_logger():
    """콘솔 로거 테스트"""
    print("\n" + "="*80)
    print("3. 콘솔 로거 테스트")
    print("="*80)

    try:
        from shared.config.logging import create_console_logger

        logger = create_console_logger('console_test', log_level='INFO')

        assert logger.name == 'console_test'
        assert len(logger.handlers) == 1, f"Expected 1 handler, got {len(logger.handlers)}"

        # 콘솔 핸들러만 있는지 확인
        from logging import StreamHandler
        assert isinstance(logger.handlers[0], StreamHandler), "Should have StreamHandler"

        print(f"✅ 콘솔 로거 생성: {logger.name}")
        print(f"✅ 핸들러 수: {len(logger.handlers)}")

        return True

    except Exception as e:
        print(f"❌ 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_file_logger():
    """파일 로거 테스트"""
    print("\n" + "="*80)
    print("4. 파일 로거 테스트")
    print("="*80)

    try:
        from shared.config.logging import create_file_logger

        # 임시 파일 사용
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, 'test.log')

            logger = create_file_logger('file_test', log_file=log_file, log_level='DEBUG')

            assert logger.name == 'file_test'
            assert len(logger.handlers) == 1, f"Expected 1 handler, got {len(logger.handlers)}"

            # 파일 핸들러가 있는지 확인
            from logging.handlers import RotatingFileHandler
            assert isinstance(logger.handlers[0], RotatingFileHandler), "Should have RotatingFileHandler"

            # 로그 작성
            logger.info("Test message")
            logger.debug("Debug message")

            # 파일 생성 확인
            assert os.path.exists(log_file), f"Log file should exist: {log_file}"

            # 파일 내용 확인
            with open(log_file, 'r') as f:
                content = f.read()
                assert 'Test message' in content, "Should contain 'Test message'"
                assert 'Debug message' in content, "Should contain 'Debug message'"

            print(f"✅ 파일 로거 생성: {logger.name}")
            print(f"✅ 로그 파일 생성: {log_file}")
            print(f"✅ 로그 작성 확인")

        return True

    except Exception as e:
        print(f"❌ 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_json_logger():
    """JSON 로거 테스트"""
    print("\n" + "="*80)
    print("5. JSON 로거 테스트")
    print("="*80)

    try:
        from shared.config.logging import setup_json_logger
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, 'test_json.log')

            logger = setup_json_logger('json_test', log_file=log_file, console_output=False)

            # 로그 작성 (extra_data 포함)
            logger.info("Order placed", extra={'extra_data': {'order_id': '123', 'price': 50000}})
            logger.error("Error occurred", extra={'extra_data': {'error_code': 'E001'}})

            # 파일 내용 확인
            assert os.path.exists(log_file), f"Log file should exist: {log_file}"

            with open(log_file, 'r') as f:
                lines = f.readlines()
                assert len(lines) >= 2, f"Expected at least 2 log lines, got {len(lines)}"

                # 첫 번째 로그 파싱
                log1 = json.loads(lines[0])
                assert 'timestamp' in log1, "Should have timestamp"
                assert 'level' in log1, "Should have level"
                assert 'message' in log1, "Should have message"
                assert log1['order_id'] == '123', f"Expected order_id='123', got {log1.get('order_id')}"
                assert log1['price'] == 50000, f"Expected price=50000, got {log1.get('price')}"

                print(f"✅ JSON 로거 생성: {logger.name}")
                print(f"✅ JSON 포맷 로그 작성")
                print(f"✅ extra_data 포함 확인")

        return True

    except Exception as e:
        print(f"❌ 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_should_log_function():
    """should_log 함수 테스트"""
    print("\n" + "="*80)
    print("6. should_log 함수 테스트 (로그 스팸 방지)")
    print("="*80)

    try:
        from shared.config.logging import should_log
        import time

        # 첫 번째 호출 - 로깅해야 함
        result1 = should_log('test_key', interval_seconds=2)
        assert result1 is True, "First call should return True"
        print("✅ 첫 번째 호출: True (로깅 필요)")

        # 즉시 다시 호출 - 로깅하지 않아야 함
        result2 = should_log('test_key', interval_seconds=2)
        assert result2 is False, "Second immediate call should return False"
        print("✅ 즉시 재호출: False (로깅 불필요)")

        # 2초 대기 후 호출 - 로깅해야 함
        time.sleep(2.1)
        result3 = should_log('test_key', interval_seconds=2)
        assert result3 is True, "Call after interval should return True"
        print("✅ 2초 후 호출: True (로깅 필요)")

        return True

    except Exception as e:
        print(f"❌ 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_add_file_handler():
    """기존 로거에 파일 핸들러 추가 테스트"""
    print("\n" + "="*80)
    print("7. 파일 핸들러 추가 테스트")
    print("="*80)

    try:
        from shared.config.logging import create_console_logger, add_file_handler

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, 'added.log')

            # 콘솔 로거 생성
            logger = create_console_logger('test_add_handler')
            initial_handlers = len(logger.handlers)
            assert initial_handlers == 1, f"Expected 1 handler, got {initial_handlers}"

            # 파일 핸들러 추가
            add_file_handler(logger, log_file)

            assert len(logger.handlers) == 2, f"Expected 2 handlers after adding, got {len(logger.handlers)}"

            # 로그 작성
            logger.info("Test after adding handler")

            # 파일에 기록되었는지 확인
            assert os.path.exists(log_file), f"Log file should exist: {log_file}"
            with open(log_file, 'r') as f:
                content = f.read()
                assert 'Test after adding handler' in content

            print(f"✅ 초기 핸들러 수: {initial_handlers}")
            print(f"✅ 파일 핸들러 추가 후: {len(logger.handlers)}")
            print(f"✅ 로그 파일 생성 및 작성 확인")

        return True

    except Exception as e:
        print(f"❌ 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_logger_levels():
    """로그 레벨 테스트"""
    print("\n" + "="*80)
    print("8. 로그 레벨 테스트")
    print("="*80)

    try:
        from shared.config.logging import setup_logger

        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, 'level_test.log')

            # INFO 레벨 로거
            logger = setup_logger('level_test', log_level='INFO', log_file=log_file, console_output=False)

            logger.debug("Debug message (should not appear)")
            logger.info("Info message")
            logger.warning("Warning message")
            logger.error("Error message")

            with open(log_file, 'r') as f:
                content = f.read()
                assert 'Debug message' not in content, "DEBUG should not appear in INFO level"
                assert 'Info message' in content, "INFO should appear"
                assert 'Warning message' in content, "WARNING should appear"
                assert 'Error message' in content, "ERROR should appear"

            print("✅ DEBUG 메시지 필터링 (INFO 레벨)")
            print("✅ INFO, WARNING, ERROR 메시지 기록")

        return True

    except Exception as e:
        print(f"❌ 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """모든 테스트 실행"""
    print("\n🧪 Logger 통합 테스트")

    results = []

    results.append(("shared.config.logging import", test_shared_logging_import()))
    results.append(("기본 로거 생성", test_basic_logger_creation()))
    results.append(("콘솔 로거", test_console_logger()))
    results.append(("파일 로거", test_file_logger()))
    results.append(("JSON 로거", test_json_logger()))
    results.append(("should_log 함수", test_should_log_function()))
    results.append(("파일 핸들러 추가", test_add_file_handler()))
    results.append(("로그 레벨", test_logger_levels()))

    # 결과 요약
    print("\n" + "="*80)
    print("테스트 결과 요약")
    print("="*80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print("="*80)
    print(f"총 {passed}/{total} 테스트 통과")
    print("="*80)

    if passed == total:
        print("\n✅ 모든 테스트 통과!")
        print("\n📋 Logger 통합 완료 사항:")
        print("   1. shared/config/logging.py - 표준 로거 구현")
        print("   2. setup_logger, get_logger - 기본 로거 생성")
        print("   3. JSON 로거 - 구조화된 로깅")
        print("   4. should_log - 로그 스팸 방지")
        print("   5. 파일 핸들러 - RotatingFileHandler")
        print("   6. 로그 레벨 - DEBUG/INFO/WARNING/ERROR/CRITICAL")
        return 0
    else:
        print(f"\n❌ {total - passed}개 테스트 실패")
        return 1


if __name__ == "__main__":
    sys.exit(main())
