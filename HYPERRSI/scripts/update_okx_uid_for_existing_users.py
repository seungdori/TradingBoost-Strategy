#!/usr/bin/env python
"""
기존 사용자의 API 키를 사용하여 OKX UID를 가져와 Redis에 저장하는 스크립트
"""
import asyncio
import logging
import redis.asyncio as redis
import os
import sys
import requests

# 프로젝트 루트 경로를 sys.path에 추가하여 프로젝트 모듈을 import 할 수 있도록 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from HYPERRSI.src.config import settings
from HYPERRSI.src.utils.check_invitee import get_uid_from_api_keys, store_okx_uid

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("okx_uid_migration.log")
    ]
)
logger = logging.getLogger("okx_uid_migration")

# Redis 연결
async def get_redis_client():
    return redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        password=settings.REDIS_PASSWORD,
        decode_responses=True
    )

async def update_okx_uid_for_user(user_id: str, redis_client) -> bool:
    """
    단일 사용자의 OKX UID를 업데이트
    
    Args:
        user_id: 텔레그램 ID (문자열)
        redis_client: Redis 클라이언트
        
    Returns:
        bool: 성공 여부
    """
    try:
        # Redis에서 API 키 정보 가져오기
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            logger.warning(f"API 키를 찾을 수 없음: user_id={user_id}")
            return False
            
        # 이미 OKX UID가 있는지 확인
        existing_uid = await redis_client.get(f"user:{user_id}:okx_uid")
        if existing_uid:
            logger.info(f"이미 OKX UID가 있음: user_id={user_id}, okx_uid={existing_uid}")
            # 이미 OKX UID가 있다면 키 마이그레이션을 시도
            await migrate_keys_to_okx_uid(redis_client, user_id, existing_uid)
            await migrate_completed_keys(redis_client, user_id, existing_uid)
            return True
            
        # API 키로 OKX UID 가져오기
        api_key = api_keys.get('api_key')
        api_secret = api_keys.get('api_secret')
        passphrase = api_keys.get('passphrase')
        
        if not all([api_key, api_secret, passphrase]):
            logger.warning(f"필요한 API 키 정보가 누락됨: user_id={user_id}")
            return False
            
        # OKX UID 가져오기
        try:
            is_invitee, okx_uid = get_uid_from_api_keys(api_key, api_secret, passphrase)
            if not okx_uid:
                logger.warning(f"OKX UID를 가져올 수 없음: user_id={user_id}")
                return False
                
            # Redis에 저장 (기존 방식 - 텔레그램 ID 키)
            await store_okx_uid(redis_client, user_id, okx_uid)
            
            # 새로운 방식 - OKX UID를 키로 사용
            await migrate_keys_to_okx_uid(redis_client, user_id, okx_uid)
            await migrate_completed_keys(redis_client, user_id, okx_uid)
            
            logger.info(f"OKX UID 업데이트 성공: user_id={user_id}, okx_uid={okx_uid}, is_invitee={is_invitee}")
            return True
            
        except requests.exceptions.HTTPError as e:
            if '401' in str(e):  # 인증 오류
                logger.error(f"API 키 인증 오류: user_id={user_id}, error={str(e)}")
                return False
            raise
        except Exception as e:
            logger.error(f"OKX UID 조회 중 오류 발생: user_id={user_id}, error={str(e)}")
            return False
            
    except Exception as e:
        logger.error(f"사용자 업데이트 중 오류 발생: user_id={user_id}, error={str(e)}")
        return False

async def migrate_keys_to_okx_uid(redis_client, user_id, okx_uid):
    """
    텔레그램 ID 기반의 Redis 키를 OKX UID 기반으로 복제
    
    Args:
        redis_client: Redis 클라이언트
        user_id: 텔레그램 ID
        okx_uid: OKX UID
    """
    try:
        # user:{user_id}:* 패턴으로 시작하는 모든 키 찾기
        keys = await redis_client.keys(f"user:{user_id}:*")
        
        for key in keys:
            # 키 이름에서 user:{user_id}: 부분을 제거하여 접미사 추출
            key_suffix = key.replace(f"user:{user_id}:", "")
            new_key = f"user:{okx_uid}:{key_suffix}"
            
            # 이미 OKX UID 기반 키가 있는지 확인
            if await redis_client.exists(new_key):
                logger.info(f"키가 이미 존재함: {new_key}")
                continue
                
            # 키 유형 확인
            key_type = await redis_client.type(key)
            
            # 키 유형에 따라 다르게 처리
            if key_type == "string":
                value = await redis_client.get(key)
                await redis_client.set(new_key, value)
                logger.info(f"문자열 키 복제: {key} -> {new_key}")
                
            elif key_type == "hash":
                hash_data = await redis_client.hgetall(key)
                if hash_data:
                    await redis_client.hset(new_key, mapping=hash_data)
                    logger.info(f"해시 키 복제: {key} -> {new_key}")
                    
            elif key_type == "list":
                list_data = await redis_client.lrange(key, 0, -1)
                if list_data:
                    await redis_client.rpush(new_key, *list_data)
                    logger.info(f"리스트 키 복제: {key} -> {new_key}")
                    
            elif key_type == "set":
                set_data = await redis_client.smembers(key)
                if set_data:
                    await redis_client.sadd(new_key, *set_data)
                    logger.info(f"집합 키 복제: {key} -> {new_key}")
                    
            elif key_type == "zset":
                zset_data = await redis_client.zrange(key, 0, -1, withscores=True)
                if zset_data:
                    await redis_client.zadd(new_key, dict(zset_data))
                    logger.info(f"정렬된 집합 키 복제: {key} -> {new_key}")
            
        logger.info(f"총 {len(keys)}개의 키를 OKX UID 기반으로 복제함: user_id={user_id}, okx_uid={okx_uid}")
    except Exception as e:
        logger.error(f"키 마이그레이션 중 오류 발생: user_id={user_id}, okx_uid={okx_uid}, error={str(e)}")        

async def migrate_completed_keys(redis_client, user_id, okx_uid):
    """
    completed:user:{user_id}:* 패턴의 키를 completed:user:{okx_uid}:* 형태로 복제
    
    Args:
        redis_client: Redis 클라이언트
        user_id: 텔레그램 ID
        okx_uid: OKX UID
    """
    try:
        # completed:user:{user_id}:* 패턴으로 시작하는 모든 키 찾기
        keys = await redis_client.keys(f"completed:user:{user_id}:*")
        
        for key in keys:
            # 키 이름에서 completed:user:{user_id}: 부분을 제거하여 접미사 추출
            key_suffix = key.replace(f"completed:user:{user_id}:", "")
            new_key = f"completed:user:{okx_uid}:{key_suffix}"
            
            # 이미 OKX UID 기반 키가 있는지 확인
            if await redis_client.exists(new_key):
                logger.info(f"completed 키가 이미 존재함: {new_key}")
                continue
                
            # 키 유형 확인
            key_type = await redis_client.type(key)
            
            # 키 유형에 따라 다르게 처리
            if key_type == "string":
                value = await redis_client.get(key)
                await redis_client.set(new_key, value)
                logger.info(f"completed 문자열 키 복제: {key} -> {new_key}")
                
            elif key_type == "hash":
                hash_data = await redis_client.hgetall(key)
                if hash_data:
                    await redis_client.hset(new_key, mapping=hash_data)
                    logger.info(f"completed 해시 키 복제: {key} -> {new_key}")
                    
            elif key_type == "list":
                list_data = await redis_client.lrange(key, 0, -1)
                if list_data:
                    await redis_client.rpush(new_key, *list_data)
                    logger.info(f"completed 리스트 키 복제: {key} -> {new_key}")
                    
            elif key_type == "set":
                set_data = await redis_client.smembers(key)
                if set_data:
                    await redis_client.sadd(new_key, *set_data)
                    logger.info(f"completed 집합 키 복제: {key} -> {new_key}")
                    
            elif key_type == "zset":
                zset_data = await redis_client.zrange(key, 0, -1, withscores=True)
                if zset_data:
                    await redis_client.zadd(new_key, dict(zset_data))
                    logger.info(f"completed 정렬된 집합 키 복제: {key} -> {new_key}")
            
        logger.info(f"총 {len(keys)}개의 completed 키를 OKX UID 기반으로 복제함: user_id={user_id}, okx_uid={okx_uid}")
    except Exception as e:
        logger.error(f"completed 키 마이그레이션 중 오류 발생: user_id={user_id}, okx_uid={okx_uid}, error={str(e)}")

async def main():
    """
    모든 사용자에 대해 OKX UID 업데이트 작업 수행
    """
    try:
        redis_client = await get_redis_client()
        
        # 모든 사용자 조회 (user:*:api:keys 패턴으로 찾음)
        user_keys = await redis_client.keys("user:*:api:keys")
        user_ids = [key.split(':')[1] for key in user_keys]
        
        logger.info(f"총 {len(user_ids)}명의 사용자에 대해 OKX UID 업데이트를 시작합니다.")
        
        success_count = 0
        fail_count = 0
        
        # 각 사용자에 대해 OKX UID 업데이트
        for user_id in user_ids:
            if await update_okx_uid_for_user(user_id, redis_client):
                success_count += 1
            else:
                fail_count += 1
                
            # 과도한 API 요청 방지를 위한 대기
            await asyncio.sleep(1)
            
        logger.info(f"OKX UID 업데이트 완료: 성공={success_count}, 실패={fail_count}")
        
        await redis_client.close()
        
    except Exception as e:
        logger.error(f"마이그레이션 중 오류 발생: {str(e)}")
        

if __name__ == "__main__":
    logger.info("OKX UID 마이그레이션을 시작합니다...")
    asyncio.run(main())
    logger.info("OKX UID 마이그레이션이 완료되었습니다.") 