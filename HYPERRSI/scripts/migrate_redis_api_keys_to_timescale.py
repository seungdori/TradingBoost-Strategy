#!/usr/bin/env python3
"""
Redis API 키를 TimescaleDB로 마이그레이션하는 스크립트

사용법:
    # 미리보기 (실제 저장 안 함)
    python scripts/migrate_redis_api_keys_to_timescale.py --dry-run

    # 모든 사용자 마이그레이션
    python scripts/migrate_redis_api_keys_to_timescale.py

    # 특정 사용자만 마이그레이션
    python scripts/migrate_redis_api_keys_to_timescale.py --okx-uid 587662504768345929
"""

import asyncio
import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.database.redis import get_redis_binary
from shared.logging import get_logger
from HYPERRSI.src.services.timescale_service import TimescaleUserService

logger = get_logger(__name__)


async def get_all_api_key_users() -> list[str]:
    """Redis에서 API 키가 저장된 모든 사용자 OKX UID 조회"""
    redis_client = await get_redis_binary()

    # user:*:api:keys 패턴으로 모든 API 키 검색
    cursor = 0
    user_ids = set()

    while True:
        cursor, keys = await redis_client.scan(cursor, match="user:*:api:keys", count=100)
        for key in keys:
            # b'user:587662504768345929:api:keys' -> '587662504768345929'
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            user_id = key_str.split(':')[1]
            user_ids.add(user_id)

        if cursor == 0:
            break

    return sorted(user_ids)


async def migrate_user_api_keys(user_id: str, dry_run: bool = False) -> bool:
    """특정 사용자의 API 키를 Redis → TimescaleDB로 마이그레이션"""
    try:
        redis_client = await get_redis_binary()

        # 1. Redis에서 API 키 조회
        redis_key = f"user:{user_id}:api:keys"
        api_keys_raw = await redis_client.hgetall(redis_key)

        if not api_keys_raw:
            logger.warning(f"⚠️  Redis에 API 키 없음: {user_id}")
            return False

        # 2. 디코딩
        api_keys = {}
        for k, v in api_keys_raw.items():
            key_str = k.decode('utf-8') if isinstance(k, bytes) else k
            val_str = v.decode('utf-8') if isinstance(v, bytes) else v
            api_keys[key_str] = val_str

        # 3. 필수 키 확인
        required_keys = ['api_key', 'api_secret', 'passphrase']
        if not all(k in api_keys for k in required_keys):
            logger.error(f"❌ API 키 불완전: {user_id}, keys: {list(api_keys.keys())}")
            return False

        logger.info(f"📦 Redis API 키 발견: {user_id}")

        # 4. TimescaleDB에 이미 존재하는지 확인
        existing_keys = await TimescaleUserService.get_api_keys(user_id)
        if existing_keys:
            logger.info(f"✅ TimescaleDB에 이미 존재: {user_id} (스킵)")
            return True

        if dry_run:
            logger.info(f"🔍 [DRY-RUN] 마이그레이션 예정: {user_id}")
            return True

        # 5. TimescaleDB에 저장
        result = await TimescaleUserService.upsert_api_credentials(
            identifier=user_id,
            api_key=api_keys['api_key'],
            api_secret=api_keys['api_secret'],
            passphrase=api_keys['passphrase']
        )

        if result:
            logger.info(f"✅ 마이그레이션 성공: {user_id}")
            return True
        else:
            logger.error(f"❌ 마이그레이션 실패: {user_id}")
            return False

    except Exception as e:
        logger.error(f"❌ 마이그레이션 오류 ({user_id}): {e}", exc_info=True)
        return False


async def main():
    parser = argparse.ArgumentParser(description='Redis API 키를 TimescaleDB로 마이그레이션')
    parser.add_argument('--dry-run', action='store_true', help='미리보기 모드 (실제 저장 안 함)')
    parser.add_argument('--okx-uid', type=str, help='특정 OKX UID만 마이그레이션')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("🚀 Redis API 키 → TimescaleDB 마이그레이션 시작")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("🔍 DRY-RUN 모드: 실제 저장하지 않습니다")

    try:
        # 마이그레이션 대상 사용자 목록
        if args.okx_uid:
            user_ids = [args.okx_uid]
            logger.info(f"📌 특정 사용자 마이그레이션: {args.okx_uid}")
        else:
            user_ids = await get_all_api_key_users()
            logger.info(f"📊 총 {len(user_ids)}명의 사용자 발견")

        # 마이그레이션 실행
        success_count = 0
        fail_count = 0
        skip_count = 0

        for i, user_id in enumerate(user_ids, 1):
            logger.info(f"\n[{i}/{len(user_ids)}] 처리 중: {user_id}")

            result = await migrate_user_api_keys(user_id, dry_run=args.dry_run)

            if result:
                # TimescaleDB에 이미 있거나 성공
                existing = await TimescaleUserService.get_api_keys(user_id)
                if existing and not args.dry_run:
                    success_count += 1
                else:
                    skip_count += 1
            else:
                fail_count += 1

        # 결과 요약
        logger.info("\n" + "=" * 60)
        logger.info("✨ 마이그레이션 완료")
        logger.info("=" * 60)
        logger.info(f"✅ 성공: {success_count}명")
        logger.info(f"⏭️  스킵: {skip_count}명 (이미 존재)")
        logger.info(f"❌ 실패: {fail_count}명")
        logger.info(f"📊 전체: {len(user_ids)}명")

        if args.dry_run:
            logger.info("\n💡 실제 마이그레이션을 실행하려면 --dry-run 없이 실행하세요")

    except Exception as e:
        logger.error(f"❌ 마이그레이션 실패: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
