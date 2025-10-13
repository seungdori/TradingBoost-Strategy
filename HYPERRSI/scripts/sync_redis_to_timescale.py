#!/usr/bin/env python3
"""
Redis to TimescaleDB 동기화 스크립트

현재 Redis에 저장된 사용자 데이터와 설정을 TimescaleDB로 마이그레이션합니다.

Usage:
    python scripts/sync_redis_to_timescale.py [--dry-run] [--okx-uid OKX_UID]

Options:
    --dry-run       실제 저장하지 않고 미리보기만 수행
    --okx-uid UID   특정 사용자만 동기화 (선택사항)
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger
from shared.utils.uid_validator import UIDValidator, UIDType
from HYPERRSI.src.services.timescale_service import TimescaleUserService

logger = get_logger(__name__)


class RedisToTimescaleSync:
    """Redis 데이터를 TimescaleDB로 동기화"""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.stats = {
            "total_users": 0,
            "synced_users": 0,
            "failed_users": 0,
            "synced_settings": 0,
            "failed_settings": 0,
        }

    async def find_all_users(self) -> List[str]:
        """Redis에서 모든 사용자 OKX UID 찾기"""
        redis = await get_redis_client()

        # user:*:api:keys 패턴으로 모든 사용자 찾기
        keys = []
        cursor = 0
        while True:
            cursor, batch = await redis.scan(
                cursor=cursor, match="user:*:api:keys", count=100
            )
            keys.extend(batch)
            if cursor == 0:
                break

        # OKX UID 추출
        okx_uids = []
        for key in keys:
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            # user:587662504768345929:api:keys -> 587662504768345929
            parts = key.split(":")
            if len(parts) >= 3:
                okx_uids.append(parts[1])

        logger.info(f"Found {len(okx_uids)} users in Redis")
        return okx_uids

    async def get_user_data_from_redis(
        self, okx_uid: str
    ) -> Optional[Dict[str, any]]:
        """Redis에서 사용자 데이터 조회"""
        redis = await get_redis_client()

        try:
            # API 키 정보
            api_keys = await redis.hgetall(f"user:{okx_uid}:api:keys")
            if not api_keys:
                logger.warning(f"No API keys found for {okx_uid}")
                return None

            # 바이트 디코딩
            api_keys_decoded = {}
            for k, v in api_keys.items():
                key_str = k.decode("utf-8") if isinstance(k, bytes) else k
                val_str = v.decode("utf-8") if isinstance(v, bytes) else v
                api_keys_decoded[key_str] = val_str

            # 설정 데이터
            preferences_raw = await redis.hgetall(f"user:{okx_uid}:preferences")
            preferences = {}
            for k, v in preferences_raw.items():
                key_str = k.decode("utf-8") if isinstance(k, bytes) else k
                val_str = v.decode("utf-8") if isinstance(v, bytes) else v
                preferences[key_str] = val_str

            # JSON 설정
            settings_json = await redis.get(f"user:{okx_uid}:settings")
            if settings_json:
                if isinstance(settings_json, bytes):
                    settings_json = settings_json.decode("utf-8")
                params = json.loads(settings_json)
            else:
                params = {}

            # 양방향 매매 설정
            dual_side_raw = await redis.hgetall(f"user:{okx_uid}:dual_side")
            dual_side = {}
            for k, v in dual_side_raw.items():
                key_str = k.decode("utf-8") if isinstance(k, bytes) else k
                val_str = v.decode("utf-8") if isinstance(v, bytes) else v
                dual_side[key_str] = val_str

            # telegram_id 찾기 (역방향 매핑)
            telegram_id = None
            cursor = 0
            while True:
                cursor, batch = await redis.scan(
                    cursor=cursor, match="user:*:okx_uid", count=100
                )
                for key in batch:
                    stored_uid = await redis.get(key)
                    if stored_uid:
                        if isinstance(stored_uid, bytes):
                            stored_uid = stored_uid.decode("utf-8")
                        if stored_uid == okx_uid:
                            # user:1709556958:okx_uid -> 1709556958
                            if isinstance(key, bytes):
                                key = key.decode("utf-8")
                            telegram_id = key.split(":")[1]
                            break
                if cursor == 0 or telegram_id:
                    break

            return {
                "okx_uid": okx_uid,
                "telegram_id": telegram_id,
                "api_keys": api_keys_decoded,
                "preferences": preferences,
                "params": params,
                "dual_side": dual_side,
            }

        except Exception as e:
            logger.error(f"Failed to get user data from Redis for {okx_uid}: {e}")
            return None

    async def sync_user_to_timescale(
        self, user_data: Dict[str, any]
    ) -> bool:
        """사용자 데이터를 TimescaleDB에 동기화"""
        okx_uid = user_data["okx_uid"]
        telegram_id = user_data.get("telegram_id")

        # UID 검증
        try:
            okx_uid = UIDValidator.ensure_okx_uid(okx_uid)
            logger.info(f"✅ OKX UID 검증: {okx_uid} (길이: {len(okx_uid)})")
        except ValueError as e:
            logger.error(f"❌ OKX UID 검증 실패: {e}")
            detected_type = UIDValidator.detect_uid_type(okx_uid)
            if detected_type == UIDType.TELEGRAM_ID:
                logger.error(f"⚠️ Telegram ID가 OKX UID로 전달됨: {okx_uid}")
                logger.error(f"   스킵합니다. 데이터를 확인하세요!")
            self.stats["failed_users"] += 1
            return False

        if telegram_id:
            try:
                telegram_id = UIDValidator.ensure_telegram_id(telegram_id)
                logger.info(f"✅ Telegram ID 검증: {telegram_id} (길이: {len(telegram_id)})")
            except ValueError as e:
                logger.warning(f"⚠️ Telegram ID 검증 실패: {e}, Telegram ID 없이 계속 진행")
                telegram_id = None

        if self.dry_run:
            logger.info(f"[DRY RUN] Would sync user: {okx_uid}")
            logger.info(f"  - Telegram ID: {telegram_id}")
            logger.info(f"  - API Keys: {bool(user_data['api_keys'])}")
            logger.info(f"  - Preferences: {len(user_data['preferences'])} keys")
            logger.info(f"  - Params: {len(user_data['params'])} keys")
            logger.info(f"  - Dual Side: {len(user_data['dual_side'])} keys")
            return True

        try:
            # 1. 사용자 존재 확인 및 생성
            logger.info(f"Ensuring user exists: {okx_uid}")
            await TimescaleUserService.ensure_user_exists(
                okx_uid=okx_uid,
                telegram_id=telegram_id,
                display_name=f"User {okx_uid}",
                telegram_username=None,
            )

            # 2. API 키 저장
            api_keys = user_data["api_keys"]
            if api_keys.get("api_key") and api_keys.get("api_secret"):
                logger.info(f"Saving API credentials for: {okx_uid}")
                await TimescaleUserService.upsert_api_credentials(
                    identifier=okx_uid,
                    api_key=api_keys.get("api_key"),
                    api_secret=api_keys.get("api_secret"),
                    passphrase=api_keys.get("passphrase"),
                )

            # 3. 설정 저장
            settings_saved = 0

            if user_data["preferences"]:
                logger.info(f"Saving preferences for: {okx_uid}")
                success = await TimescaleUserService.save_all_user_settings(
                    identifier=okx_uid,
                    preferences=user_data["preferences"],
                    params=None,
                    dual_side=None,
                )
                if success:
                    settings_saved += 1
                    self.stats["synced_settings"] += 1

            if user_data["params"]:
                logger.info(f"Saving params for: {okx_uid}")
                success = await TimescaleUserService.save_all_user_settings(
                    identifier=okx_uid,
                    preferences=None,
                    params=user_data["params"],
                    dual_side=None,
                )
                if success:
                    settings_saved += 1
                    self.stats["synced_settings"] += 1

            if user_data["dual_side"]:
                logger.info(f"Saving dual_side for: {okx_uid}")
                success = await TimescaleUserService.save_all_user_settings(
                    identifier=okx_uid,
                    preferences=None,
                    params=None,
                    dual_side=user_data["dual_side"],
                )
                if success:
                    settings_saved += 1
                    self.stats["synced_settings"] += 1

            logger.info(
                f"✅ Successfully synced user {okx_uid} ({settings_saved} setting types)"
            )
            return True

        except Exception as e:
            logger.error(f"❌ Failed to sync user {okx_uid}: {e}")
            self.stats["failed_settings"] += 1
            return False

    async def sync_all_users(self, specific_okx_uid: Optional[str] = None):
        """모든 사용자 또는 특정 사용자 동기화"""
        if specific_okx_uid:
            okx_uids = [specific_okx_uid]
            logger.info(f"Syncing specific user: {specific_okx_uid}")
        else:
            okx_uids = await self.find_all_users()
            logger.info(f"Found {len(okx_uids)} users to sync")

        self.stats["total_users"] = len(okx_uids)

        for okx_uid in okx_uids:
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing user: {okx_uid}")
            logger.info(f"{'='*60}")

            user_data = await self.get_user_data_from_redis(okx_uid)
            if not user_data:
                logger.warning(f"Skipping user {okx_uid} - no data found")
                self.stats["failed_users"] += 1
                continue

            success = await self.sync_user_to_timescale(user_data)
            if success:
                self.stats["synced_users"] += 1
            else:
                self.stats["failed_users"] += 1

        # 최종 통계 출력
        logger.info(f"\n{'='*60}")
        logger.info("SYNC COMPLETED")
        logger.info(f"{'='*60}")
        logger.info(f"Total users: {self.stats['total_users']}")
        logger.info(f"✅ Synced users: {self.stats['synced_users']}")
        logger.info(f"❌ Failed users: {self.stats['failed_users']}")
        logger.info(f"✅ Synced settings: {self.stats['synced_settings']}")
        logger.info(f"❌ Failed settings: {self.stats['failed_settings']}")
        logger.info(f"{'='*60}\n")


async def main():
    """메인 함수"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Sync Redis user data to TimescaleDB"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without actually syncing",
    )
    parser.add_argument(
        "--okx-uid", type=str, help="Sync only specific OKX UID"
    )

    args = parser.parse_args()

    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No changes will be made")

    syncer = RedisToTimescaleSync(dry_run=args.dry_run)
    await syncer.sync_all_users(specific_okx_uid=args.okx_uid)


if __name__ == "__main__":
    asyncio.run(main())
