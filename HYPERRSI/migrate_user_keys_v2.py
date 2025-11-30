#!/usr/bin/env python3
"""
사용자 데이터 마이그레이션 스크립트 V2

telegram_id 기반 키 → okx_uid 기반 키로 완전 통합
- 모든 user:* 패턴의 키를 스캔
- telegram_id (≤11자리) → okx_uid (≥15자리) 변환
- 양방향 매핑 생성 및 검증

실행 전 주의사항:
1. Redis 백업 권장: redis-cli BGSAVE
2. 서비스 중지 권장 (라이브 마이그레이션도 가능하지만 안전을 위해)
3. --dry-run 옵션으로 먼저 테스트

사용법:
    python migrate_user_keys_v2.py --dry-run   # 테스트 실행 (실제 변경 없음)
    python migrate_user_keys_v2.py             # 실제 마이그레이션
"""

import asyncio
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from shared.database.redis_helper import get_redis_client
from shared.helpers.user_id_resolver import (
    TELEGRAM_ID_MAX_LENGTH,
    OKX_UID_MIN_LENGTH,
    is_telegram_id,
    is_okx_uid,
    store_user_id_mapping,
)
from shared.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MigrationStats:
    """마이그레이션 통계"""
    total_keys_scanned: int = 0
    keys_to_migrate: int = 0
    keys_migrated: int = 0
    keys_skipped: int = 0
    keys_failed: int = 0
    mappings_created: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None

    def duration(self) -> str:
        end = self.end_time or datetime.now()
        delta = end - self.start_time
        return str(delta).split('.')[0]

    def summary(self) -> str:
        return f"""
╔══════════════════════════════════════════════════════════════╗
║                   마이그레이션 결과 요약                      ║
╠══════════════════════════════════════════════════════════════╣
║  총 스캔된 키:        {self.total_keys_scanned:>10}                         ║
║  마이그레이션 대상:    {self.keys_to_migrate:>10}                         ║
║  성공:                {self.keys_migrated:>10}                         ║
║  스킵:                {self.keys_skipped:>10}                         ║
║  실패:                {self.keys_failed:>10}                         ║
║  매핑 생성:           {self.mappings_created:>10}                         ║
║  소요 시간:           {self.duration():>10}                         ║
╚══════════════════════════════════════════════════════════════╝
"""


@dataclass
class UserMapping:
    """사용자 ID 매핑"""
    telegram_id: str
    okx_uid: str
    source: str  # 'redis', 'api_keys', 'known'


async def scan_all_user_keys(redis) -> Dict[str, Set[str]]:
    """모든 user:* 키를 스캔하여 사용자별로 그룹화"""
    user_keys: Dict[str, Set[str]] = {}
    cursor = 0

    logger.info("Redis 키 스캔 시작...")

    while True:
        cursor, keys = await redis.scan(cursor, match="user:*", count=500)

        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            parts = key_str.split(':')

            if len(parts) >= 2:
                user_id = parts[1]
                if user_id not in user_keys:
                    user_keys[user_id] = set()
                user_keys[user_id].add(key_str)

        if cursor == 0:
            break

    logger.info(f"총 {len(user_keys)} 사용자의 키 발견")
    return user_keys


async def find_telegram_okx_mappings(redis, user_keys: Dict[str, Set[str]]) -> List[UserMapping]:
    """telegram_id와 okx_uid 간의 매핑 찾기"""
    mappings: List[UserMapping] = []
    found_telegram_ids: Set[str] = set()
    found_okx_uids: Set[str] = set()

    logger.info("ID 매핑 분석 중...")

    for user_id, keys in user_keys.items():
        # 이미 처리된 ID 스킵
        if user_id in found_telegram_ids or user_id in found_okx_uids:
            continue

        # telegram_id인 경우
        if is_telegram_id(user_id):
            # okx_uid 매핑 키 확인
            okx_uid_key = f"user:{user_id}:okx_uid"
            if okx_uid_key in keys:
                okx_uid = await redis.get(okx_uid_key)
                if okx_uid:
                    okx_uid_str = okx_uid.decode() if isinstance(okx_uid, bytes) else str(okx_uid)
                    if is_okx_uid(okx_uid_str):
                        mappings.append(UserMapping(
                            telegram_id=user_id,
                            okx_uid=okx_uid_str,
                            source='redis'
                        ))
                        found_telegram_ids.add(user_id)
                        found_okx_uids.add(okx_uid_str)
                        continue

            # API 키에서 UID 확인
            api_key = f"user:{user_id}:api:keys"
            if api_key in keys:
                api_data = await redis.hgetall(api_key)
                uid = api_data.get(b'uid') or api_data.get('uid')
                if uid:
                    uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
                    if is_okx_uid(uid_str):
                        mappings.append(UserMapping(
                            telegram_id=user_id,
                            okx_uid=uid_str,
                            source='api_keys'
                        ))
                        found_telegram_ids.add(user_id)
                        found_okx_uids.add(uid_str)

    logger.info(f"총 {len(mappings)} 개의 매핑 발견")
    return mappings


async def migrate_keys(
    redis,
    telegram_id: str,
    okx_uid: str,
    keys: Set[str],
    dry_run: bool = False
) -> Tuple[int, int, int]:
    """telegram_id 기반 키를 okx_uid 기반으로 마이그레이션

    Returns:
        Tuple[migrated, skipped, failed]
    """
    migrated = 0
    skipped = 0
    failed = 0

    for old_key in keys:
        # okx_uid 매핑 키는 유지
        if old_key == f"user:{telegram_id}:okx_uid":
            skipped += 1
            continue

        # 새 키 이름 생성
        new_key = old_key.replace(f"user:{telegram_id}:", f"user:{okx_uid}:")

        # 이미 존재하는 경우 스킵
        if await redis.exists(new_key):
            logger.debug(f"  이미 존재: {new_key}")
            skipped += 1
            continue

        try:
            # 키 타입 확인
            key_type = await redis.type(old_key)
            key_type_str = key_type.decode() if isinstance(key_type, bytes) else key_type

            if key_type_str == 'none':
                skipped += 1
                continue

            if dry_run:
                logger.info(f"  [DRY-RUN] 복사 예정: {old_key} → {new_key} ({key_type_str})")
                migrated += 1
                continue

            # 타입별 복사
            if key_type_str == 'hash':
                data = await redis.hgetall(old_key)
                if data:
                    await redis.hset(new_key, mapping=data)

            elif key_type_str == 'string':
                data = await redis.get(old_key)
                if data:
                    ttl = await redis.ttl(old_key)
                    if ttl > 0:
                        await redis.setex(new_key, ttl, data)
                    else:
                        await redis.set(new_key, data)

            elif key_type_str == 'list':
                data = await redis.lrange(old_key, 0, -1)
                if data:
                    await redis.rpush(new_key, *data)

            elif key_type_str == 'set':
                data = await redis.smembers(old_key)
                if data:
                    await redis.sadd(new_key, *data)

            elif key_type_str == 'zset':
                data = await redis.zrange(old_key, 0, -1, withscores=True)
                if data:
                    await redis.zadd(new_key, {m: s for m, s in data})

            logger.debug(f"  ✓ 복사됨: {old_key} → {new_key}")
            migrated += 1

        except Exception as e:
            logger.error(f"  ✗ 실패: {old_key} - {str(e)}")
            failed += 1

    return migrated, skipped, failed


async def ensure_bidirectional_mapping(redis, telegram_id: str, okx_uid: str, dry_run: bool = False):
    """양방향 매핑 보장"""

    # telegram_id → okx_uid 매핑
    forward_key = f"user:{telegram_id}:okx_uid"
    forward_exists = await redis.exists(forward_key)

    # okx_uid → telegram_id 매핑
    reverse_key = f"okx_uid_to_telegram:{okx_uid}"
    reverse_exists = await redis.exists(reverse_key)

    if dry_run:
        if not forward_exists:
            logger.info(f"  [DRY-RUN] 생성 예정: {forward_key} → {okx_uid}")
        if not reverse_exists:
            logger.info(f"  [DRY-RUN] 생성 예정: {reverse_key} → {telegram_id}")
        return int(not forward_exists) + int(not reverse_exists)

    created = 0

    if not forward_exists:
        await redis.set(forward_key, okx_uid)
        logger.info(f"  ✓ 매핑 생성: {forward_key} → {okx_uid}")
        created += 1

    if not reverse_exists:
        await redis.set(reverse_key, telegram_id)
        logger.info(f"  ✓ 매핑 생성: {reverse_key} → {telegram_id}")
        created += 1

    return created


async def migrate_specific_user(redis, telegram_id: str, okx_uid: str, dry_run: bool = False) -> MigrationStats:
    """특정 사용자 마이그레이션"""
    stats = MigrationStats()

    logger.info(f"\n{'='*60}")
    logger.info(f"마이그레이션: telegram_id={telegram_id} → okx_uid={okx_uid}")
    logger.info(f"{'='*60}")

    # telegram_id 기반 키 스캔
    cursor = 0
    telegram_keys: Set[str] = set()

    while True:
        cursor, keys = await redis.scan(cursor, match=f"user:{telegram_id}:*", count=100)
        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            telegram_keys.add(key_str)
        if cursor == 0:
            break

    stats.total_keys_scanned = len(telegram_keys)
    stats.keys_to_migrate = len(telegram_keys) - 1  # okx_uid 키 제외

    logger.info(f"발견된 키: {len(telegram_keys)}")

    # 키 마이그레이션
    migrated, skipped, failed = await migrate_keys(
        redis, telegram_id, okx_uid, telegram_keys, dry_run
    )

    stats.keys_migrated = migrated
    stats.keys_skipped = skipped
    stats.keys_failed = failed

    # 양방향 매핑 보장
    stats.mappings_created = await ensure_bidirectional_mapping(
        redis, telegram_id, okx_uid, dry_run
    )

    stats.end_time = datetime.now()
    return stats


async def main(dry_run: bool = False, user_id: Optional[str] = None):
    """메인 마이그레이션 함수"""
    redis = await get_redis_client()
    total_stats = MigrationStats()

    mode = "[DRY-RUN] " if dry_run else ""
    logger.info(f"\n{'='*60}")
    logger.info(f"{mode}User ID 마이그레이션 시작")
    logger.info(f"{'='*60}\n")

    if user_id:
        # 특정 사용자만 마이그레이션
        if is_telegram_id(user_id):
            okx_uid = await redis.get(f"user:{user_id}:okx_uid")
            if okx_uid:
                okx_uid_str = okx_uid.decode() if isinstance(okx_uid, bytes) else str(okx_uid)
                stats = await migrate_specific_user(redis, user_id, okx_uid_str, dry_run)
                total_stats = stats
            else:
                logger.error(f"telegram_id {user_id}에 대한 okx_uid 매핑을 찾을 수 없습니다.")
                return
        else:
            logger.error(f"제공된 ID {user_id}는 telegram_id 형식이 아닙니다.")
            return
    else:
        # 모든 사용자 마이그레이션
        user_keys = await scan_all_user_keys(redis)
        total_stats.total_keys_scanned = sum(len(keys) for keys in user_keys.values())

        # 매핑 찾기
        mappings = await find_telegram_okx_mappings(redis, user_keys)

        for mapping in mappings:
            telegram_keys = user_keys.get(mapping.telegram_id, set())

            if not telegram_keys:
                continue

            logger.info(f"\n마이그레이션: {mapping.telegram_id} → {mapping.okx_uid} (source: {mapping.source})")

            migrated, skipped, failed = await migrate_keys(
                redis, mapping.telegram_id, mapping.okx_uid, telegram_keys, dry_run
            )

            total_stats.keys_migrated += migrated
            total_stats.keys_skipped += skipped
            total_stats.keys_failed += failed
            total_stats.keys_to_migrate += len(telegram_keys)

            # 양방향 매핑 보장
            total_stats.mappings_created += await ensure_bidirectional_mapping(
                redis, mapping.telegram_id, mapping.okx_uid, dry_run
            )

    total_stats.end_time = datetime.now()

    logger.info(total_stats.summary())

    if dry_run:
        logger.info("\n💡 실제 마이그레이션을 수행하려면 --dry-run 옵션을 제거하고 다시 실행하세요.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="User ID 마이그레이션 스크립트 V2")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 변경 없이 마이그레이션 계획만 출력"
    )
    parser.add_argument(
        "--user-id",
        type=str,
        help="특정 telegram_id만 마이그레이션 (선택 사항)"
    )

    args = parser.parse_args()

    try:
        asyncio.run(main(dry_run=args.dry_run, user_id=args.user_id))
    except KeyboardInterrupt:
        logger.info("\n마이그레이션이 사용자에 의해 중단되었습니다.")
    except Exception as e:
        logger.error(f"마이그레이션 실패: {e}", exc_info=True)
        sys.exit(1)
