#!/usr/bin/env python3
"""
멀티심볼 마이그레이션 스크립트

기존 단일 심볼 방식의 사용자 데이터를 멀티심볼 구조로 마이그레이션합니다.

실행 방법:
    cd /Users/seunghyun/TradingBoost-Strategy
    python -m HYPERRSI.scripts.migrate_to_multi_symbol

옵션:
    --dry-run: 실제 변경 없이 마이그레이션 대상만 확인
    --verbose: 상세 로그 출력
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.database.redis_patterns import redis_context, RedisTimeout
from shared.logging import get_logger

logger = get_logger(__name__)

# 레거시 Redis 키 패턴
LEGACY_STATUS_KEY = "user:{okx_uid}:trading:status"
LEGACY_PREFERENCES_KEY = "user:{okx_uid}:preferences"
LEGACY_TASK_ID_KEY = "user:{okx_uid}:task_id"

# 멀티심볼 Redis 키 패턴
MULTI_ACTIVE_SYMBOLS_KEY = "user:{okx_uid}:active_symbols"
MULTI_SYMBOL_STATUS_KEY = "user:{okx_uid}:symbol:{symbol}:status"
MULTI_SYMBOL_TIMEFRAME_KEY = "user:{okx_uid}:symbol:{symbol}:timeframe"
MULTI_SYMBOL_TASK_ID_KEY = "user:{okx_uid}:symbol:{symbol}:task_id"
MULTI_SYMBOL_STARTED_AT_KEY = "user:{okx_uid}:symbol:{symbol}:started_at"


class MigrationResult:
    """마이그레이션 결과 추적"""
    def __init__(self):
        self.total_users = 0
        self.migrated_users = 0
        self.skipped_users = 0
        self.failed_users = 0
        self.errors: List[Dict[str, Any]] = []

    def add_success(self, okx_uid: str, symbol: str):
        self.migrated_users += 1
        logger.info(f"✅ [{okx_uid}] 마이그레이션 성공: {symbol}")

    def add_skip(self, okx_uid: str, reason: str):
        self.skipped_users += 1
        logger.info(f"⏭️ [{okx_uid}] 건너뜀: {reason}")

    def add_error(self, okx_uid: str, error: str):
        self.failed_users += 1
        self.errors.append({"okx_uid": okx_uid, "error": error})
        logger.error(f"❌ [{okx_uid}] 실패: {error}")

    def summary(self) -> str:
        return f"""
========== 마이그레이션 결과 ==========
총 사용자: {self.total_users}
성공: {self.migrated_users}
건너뜀: {self.skipped_users}
실패: {self.failed_users}

{f"실패 상세:" if self.errors else ""}
{chr(10).join([f"  - {e['okx_uid']}: {e['error']}" for e in self.errors]) if self.errors else ""}
======================================
"""


async def scan_legacy_users() -> List[str]:
    """
    레거시 방식으로 트레이딩 중인 사용자 목록 스캔
    """
    async with redis_context(timeout=RedisTimeout.SLOW_OPERATION) as redis:
        users = []
        cursor = 0
        pattern = "user:*:trading:status"

        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)

            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode('utf-8')

                # 키 형식: user:{okx_uid}:trading:status
                parts = key.split(':')
                if len(parts) >= 4 and parts[2] == 'trading' and parts[3] == 'status':
                    okx_uid = parts[1]

                    # 상태가 'running'인 경우만 포함
                    status = await redis.get(key)
                    if isinstance(status, bytes):
                        status = status.decode('utf-8')

                    if status == "running":
                        users.append(okx_uid)

            if cursor == 0:
                break

        return users


async def check_already_migrated(okx_uid: str) -> bool:
    """
    이미 멀티심볼 구조로 마이그레이션되었는지 확인
    """
    async with redis_context(timeout=RedisTimeout.FAST_OPERATION) as redis:
        active_symbols_key = MULTI_ACTIVE_SYMBOLS_KEY.format(okx_uid=okx_uid)
        exists = await redis.exists(active_symbols_key)
        return bool(exists)


async def get_legacy_user_data(okx_uid: str) -> Optional[Dict[str, Any]]:
    """
    레거시 방식의 사용자 데이터 조회
    """
    async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
        preferences_key = LEGACY_PREFERENCES_KEY.format(okx_uid=okx_uid)
        task_id_key = LEGACY_TASK_ID_KEY.format(okx_uid=okx_uid)

        preferences = await redis.hgetall(preferences_key)
        task_id = await redis.get(task_id_key)

        if not preferences:
            return None

        # bytes to str 변환
        def decode(val):
            if isinstance(val, bytes):
                return val.decode('utf-8')
            return val

        symbol = decode(preferences.get(b'symbol') or preferences.get('symbol'))
        timeframe = decode(preferences.get(b'timeframe') or preferences.get('timeframe'))

        if not symbol:
            return None

        return {
            "symbol": symbol,
            "timeframe": timeframe or "1m",
            "task_id": decode(task_id) if task_id else None
        }


async def migrate_user(okx_uid: str, dry_run: bool = False, verbose: bool = False) -> bool:
    """
    단일 사용자를 멀티심볼 구조로 마이그레이션

    Args:
        okx_uid: 사용자 OKX UID
        dry_run: True면 실제 변경 없이 대상만 확인
        verbose: 상세 로그 출력

    Returns:
        성공 여부
    """
    # 기존 데이터 조회
    user_data = await get_legacy_user_data(okx_uid)

    if not user_data:
        if verbose:
            logger.debug(f"[{okx_uid}] 레거시 데이터 없음")
        return False

    symbol = user_data["symbol"]
    timeframe = user_data["timeframe"]
    task_id = user_data.get("task_id")

    if verbose:
        logger.info(f"[{okx_uid}] 마이그레이션 대상: symbol={symbol}, timeframe={timeframe}")

    if dry_run:
        logger.info(f"[DRY-RUN] [{okx_uid}] 마이그레이션 예정: {symbol}")
        return True

    # 실제 마이그레이션 수행
    async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
        current_time = str(datetime.now().timestamp())

        # 1. active_symbols SET에 심볼 추가
        active_symbols_key = MULTI_ACTIVE_SYMBOLS_KEY.format(okx_uid=okx_uid)
        await redis.sadd(active_symbols_key, symbol)

        # 2. 심볼별 상태 설정
        symbol_status_key = MULTI_SYMBOL_STATUS_KEY.format(okx_uid=okx_uid, symbol=symbol)
        await redis.set(symbol_status_key, "running")

        # 3. 심볼별 타임프레임 설정
        symbol_timeframe_key = MULTI_SYMBOL_TIMEFRAME_KEY.format(okx_uid=okx_uid, symbol=symbol)
        await redis.set(symbol_timeframe_key, timeframe)

        # 4. 심볼별 시작 시간 설정
        symbol_started_at_key = MULTI_SYMBOL_STARTED_AT_KEY.format(okx_uid=okx_uid, symbol=symbol)
        await redis.set(symbol_started_at_key, current_time)

        # 5. task_id가 있으면 심볼별 task_id 설정
        if task_id:
            symbol_task_id_key = MULTI_SYMBOL_TASK_ID_KEY.format(okx_uid=okx_uid, symbol=symbol)
            await redis.set(symbol_task_id_key, task_id)

        logger.info(f"[{okx_uid}] 멀티심볼 구조 마이그레이션 완료: {symbol}")
        return True


async def run_migration(dry_run: bool = False, verbose: bool = False) -> MigrationResult:
    """
    전체 마이그레이션 실행

    Args:
        dry_run: True면 실제 변경 없이 대상만 확인
        verbose: 상세 로그 출력

    Returns:
        MigrationResult 객체
    """
    result = MigrationResult()

    logger.info("=" * 50)
    logger.info("멀티심볼 마이그레이션 시작")
    logger.info(f"모드: {'DRY-RUN (실제 변경 없음)' if dry_run else '실제 마이그레이션'}")
    logger.info("=" * 50)

    # 1. 레거시 방식 사용자 스캔
    logger.info("레거시 방식 사용자 스캔 중...")
    legacy_users = await scan_legacy_users()
    result.total_users = len(legacy_users)
    logger.info(f"총 {result.total_users}명의 활성 사용자 발견")

    # 2. 각 사용자 마이그레이션
    for okx_uid in legacy_users:
        try:
            # 이미 마이그레이션되었는지 확인
            if await check_already_migrated(okx_uid):
                result.add_skip(okx_uid, "이미 마이그레이션됨")
                continue

            # 마이그레이션 실행
            success = await migrate_user(okx_uid, dry_run=dry_run, verbose=verbose)

            if success:
                result.add_success(okx_uid, await get_legacy_user_data(okx_uid).get("symbol", "unknown") if not dry_run else "pending")
            else:
                result.add_skip(okx_uid, "마이그레이션 대상 아님 (데이터 없음)")

        except Exception as e:
            result.add_error(okx_uid, str(e))

    return result


async def verify_migration(okx_uid: str) -> Dict[str, Any]:
    """
    마이그레이션 결과 검증

    Args:
        okx_uid: 확인할 사용자 OKX UID

    Returns:
        검증 결과 딕셔너리
    """
    async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
        active_symbols_key = MULTI_ACTIVE_SYMBOLS_KEY.format(okx_uid=okx_uid)
        active_symbols = await redis.smembers(active_symbols_key)

        result = {
            "okx_uid": okx_uid,
            "active_symbols": [],
            "symbols_detail": []
        }

        for symbol in active_symbols:
            if isinstance(symbol, bytes):
                symbol = symbol.decode('utf-8')

            result["active_symbols"].append(symbol)

            # 심볼별 상세 정보 조회
            status_key = MULTI_SYMBOL_STATUS_KEY.format(okx_uid=okx_uid, symbol=symbol)
            timeframe_key = MULTI_SYMBOL_TIMEFRAME_KEY.format(okx_uid=okx_uid, symbol=symbol)
            task_id_key = MULTI_SYMBOL_TASK_ID_KEY.format(okx_uid=okx_uid, symbol=symbol)
            started_at_key = MULTI_SYMBOL_STARTED_AT_KEY.format(okx_uid=okx_uid, symbol=symbol)

            status = await redis.get(status_key)
            timeframe = await redis.get(timeframe_key)
            task_id = await redis.get(task_id_key)
            started_at = await redis.get(started_at_key)

            def decode(val):
                if isinstance(val, bytes):
                    return val.decode('utf-8')
                return val

            result["symbols_detail"].append({
                "symbol": symbol,
                "status": decode(status),
                "timeframe": decode(timeframe),
                "task_id": decode(task_id),
                "started_at": decode(started_at)
            })

        return result


def main():
    parser = argparse.ArgumentParser(
        description="멀티심볼 마이그레이션 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
    # 실제 변경 없이 대상만 확인
    python -m HYPERRSI.scripts.migrate_to_multi_symbol --dry-run

    # 실제 마이그레이션 실행
    python -m HYPERRSI.scripts.migrate_to_multi_symbol

    # 상세 로그와 함께 실행
    python -m HYPERRSI.scripts.migrate_to_multi_symbol --verbose
        """
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 변경 없이 마이그레이션 대상만 확인"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="상세 로그 출력"
    )

    parser.add_argument(
        "--verify",
        type=str,
        metavar="OKX_UID",
        help="특정 사용자의 마이그레이션 결과 검증"
    )

    args = parser.parse_args()

    async def async_main():
        if args.verify:
            # 마이그레이션 검증 모드
            result = await verify_migration(args.verify)
            print(f"\n마이그레이션 검증 결과:")
            print(f"  OKX UID: {result['okx_uid']}")
            print(f"  활성 심볼: {result['active_symbols']}")
            for detail in result['symbols_detail']:
                print(f"\n  [{detail['symbol']}]")
                print(f"    - status: {detail['status']}")
                print(f"    - timeframe: {detail['timeframe']}")
                print(f"    - task_id: {detail['task_id']}")
                print(f"    - started_at: {detail['started_at']}")
        else:
            # 마이그레이션 실행
            result = await run_migration(
                dry_run=args.dry_run,
                verbose=args.verbose
            )
            print(result.summary())

    asyncio.run(async_main())


if __name__ == "__main__":
    main()
