#!/usr/bin/env python3
"""
사용자 API 키 마이그레이션 스크립트

텔레그램 ID 기반 키 → OKX UID 기반 키로 이동
user:{telegram_id}:* → user:{okx_uid}:*
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger

logger = get_logger(__name__)

# 알려진 텔레그램 ID → OKX UID 매핑 (이미 알고 있는 경우)
KNOWN_MAPPINGS = {
    # "telegram_id": "okx_uid"
    # 예: "1709556985": "518796558012178692"
}


async def get_all_telegram_user_keys():
    """텔레그램 ID 기반 키를 모두 찾기"""
    redis = await get_redis_client()

    # user:*:api:keys 패턴으로 모든 API 키 찾기
    all_keys = []
    cursor = 0

    while True:
        cursor, keys = await redis.scan(cursor, match="user:*:api:keys", count=100)
        all_keys.extend([k.decode() if isinstance(k, bytes) else k for k in keys])

        if cursor == 0:
            break

    return all_keys


async def extract_uid_from_api_keys(api_keys_hash):
    """API 키 해시에서 UID 추출"""
    uid = api_keys_hash.get(b'uid') or api_keys_hash.get('uid')
    if uid:
        return uid.decode() if isinstance(uid, bytes) else uid
    return None


async def migrate_user_data(redis, telegram_id: str, okx_uid: str):
    """사용자 데이터를 텔레그램 ID 기반에서 OKX UID 기반으로 마이그레이션"""

    logger.info(f"Migrating user data: telegram_id={telegram_id} → okx_uid={okx_uid}")

    # 마이그레이션할 키 패턴
    patterns = [
        f"user:{telegram_id}:api:keys",
        f"user:{telegram_id}:preferences",
        f"user:{telegram_id}:settings",
        f"user:{telegram_id}:dual_side",
        f"user:{telegram_id}:trading:status",
        f"user:{telegram_id}:stats",
    ]

    migrated_count = 0

    for old_key in patterns:
        # 키 존재 확인
        key_type = await redis.type(old_key)
        key_type_str = key_type.decode() if isinstance(key_type, bytes) else key_type

        if key_type_str == 'none':
            continue

        # 새 키 생성
        new_key = old_key.replace(f"user:{telegram_id}:", f"user:{okx_uid}:")

        # 키 타입에 따라 복사
        if key_type_str == 'hash':
            data = await redis.hgetall(old_key)
            if data:
                await redis.hmset(new_key, data)
                logger.info(f"  ✓ Copied hash: {old_key} → {new_key}")
                migrated_count += 1

        elif key_type_str == 'string':
            data = await redis.get(old_key)
            if data:
                ttl = await redis.ttl(old_key)
                if ttl > 0:
                    await redis.setex(new_key, ttl, data)
                else:
                    await redis.set(new_key, data)
                logger.info(f"  ✓ Copied string: {old_key} → {new_key}")
                migrated_count += 1

        elif key_type_str == 'list':
            length = await redis.llen(old_key)
            if length > 0:
                data = await redis.lrange(old_key, 0, -1)
                for item in data:
                    await redis.rpush(new_key, item)
                logger.info(f"  ✓ Copied list: {old_key} → {new_key}")
                migrated_count += 1

    # 텔레그램 ID → OKX UID 매핑 저장
    await redis.set(f"user:{telegram_id}:okx_uid", okx_uid)
    logger.info(f"  ✓ Created mapping: user:{telegram_id}:okx_uid → {okx_uid}")

    return migrated_count


async def main():
    """메인 마이그레이션 함수"""
    redis = await get_redis_client()

    logger.info("=" * 60)
    logger.info("Starting user data migration...")
    logger.info("=" * 60)

    # 모든 API 키 찾기
    all_api_keys = await get_all_telegram_user_keys()
    logger.info(f"Found {len(all_api_keys)} API key entries")

    total_migrated = 0

    for key in all_api_keys:
        # user:XXXXX:api:keys에서 user_id 추출
        parts = key.split(':')
        if len(parts) >= 3:
            user_id = parts[1]

            # API 키 데이터 가져오기
            api_keys_data = await redis.hgetall(key)

            if not api_keys_data:
                logger.warning(f"Empty API keys for {key}")
                continue

            # UID 추출
            okx_uid = await extract_uid_from_api_keys(api_keys_data)

            if not okx_uid:
                logger.warning(f"No UID found in {key}")
                continue

            # UID가 숫자로만 구성되어 있고 길이가 18자 이상이면 OKX UID
            if okx_uid.isdigit() and len(okx_uid) >= 18:
                # 이미 OKX UID 기반 키라면 스킵
                if user_id == okx_uid:
                    logger.info(f"Already migrated: {key}")
                    continue

                # 마이그레이션 실행
                count = await migrate_user_data(redis, user_id, okx_uid)
                total_migrated += count
                logger.info(f"Migrated {count} keys for user {user_id}")
            else:
                logger.warning(f"Invalid OKX UID format: {okx_uid} in {key}")

    logger.info("=" * 60)
    logger.info(f"Migration completed! Total keys migrated: {total_migrated}")
    logger.info("=" * 60)

    # 마이그레이션 확인
    logger.info("\nVerifying migration...")
    for key in all_api_keys:
        parts = key.split(':')
        if len(parts) >= 3:
            user_id = parts[1]
            api_keys_data = await redis.hgetall(key)
            okx_uid = await extract_uid_from_api_keys(api_keys_data)

            if okx_uid and user_id != okx_uid:
                new_key = f"user:{okx_uid}:api:keys"
                exists = await redis.exists(new_key)

                if exists:
                    logger.info(f"  ✓ Verified: {new_key} exists")
                else:
                    logger.error(f"  ✗ Missing: {new_key}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nMigration interrupted by user")
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)
