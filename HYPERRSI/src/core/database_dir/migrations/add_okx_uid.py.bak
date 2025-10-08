"""
이 스크립트는 사용자 테이블에 OKX UID 필드를 추가하는 마이그레이션을 수행합니다.
"""
from sqlalchemy import create_engine, Column, String, MetaData, Table
from alembic import op
import sqlalchemy as sa
from HYPERRSI.src.config import settings
import redis
import asyncio

# Alembic 마이그레이션을 위한 함수 (Alembic 설정이 있는 경우)
def upgrade():
    op.add_column('users', sa.Column('okx_uid', sa.String(), nullable=True, unique=True))
    op.create_index(op.f('ix_users_okx_uid'), 'users', ['okx_uid'], unique=True)

def downgrade():
    op.drop_index(op.f('ix_users_okx_uid'), table_name='users')
    op.drop_column('users', 'okx_uid')

# Redis 마이그레이션을 위한 함수
async def migrate_redis_keys(redis_client):
    """
    텔레그램 ID 기반의 Redis 키를 OKX UID 기반으로 복제
    
    Args:
        redis_client: Redis 클라이언트
    """
    print("Redis 키 마이그레이션 시작...")
    
    # OKX UID가 있는 모든 사용자 찾기
    user_okx_keys = await redis_client.keys("user:*:okx_uid")
    migration_count = 0
    
    for key in user_okx_keys:
        try:
            # 텔레그램 ID 추출
            telegram_id = key.split(':')[1]
            
            # OKX UID 가져오기
            okx_uid = await redis_client.get(key)
            
            # 이미 OKX UID로 마이그레이션된 키 확인
            existing_keys = await redis_client.keys(f"user:{okx_uid}:*")
            if existing_keys:
                print(f"이미 마이그레이션된 사용자: telegram_id={telegram_id}, okx_uid={okx_uid}")
                continue
                
            # 해당 텔레그램 ID에 대한 모든 키 찾기 (user:* 패턴)
            user_keys = await redis_client.keys(f"user:{telegram_id}:*")
            
            # user: 패턴 키 마이그레이션
            for user_key in user_keys:
                # 키 이름에서 user:{telegram_id}: 부분을 제거하여 접미사 추출
                key_suffix = user_key.replace(f"user:{telegram_id}:", "")
                new_key = f"user:{okx_uid}:{key_suffix}"
                
                # 키 유형 확인
                key_type = await redis_client.type(user_key)
                
                # 키 유형에 따라 다르게 처리
                if key_type == "string":
                    value = await redis_client.get(user_key)
                    await redis_client.set(new_key, value)
                    
                elif key_type == "hash":
                    hash_data = await redis_client.hgetall(user_key)
                    if hash_data:
                        await redis_client.hset(new_key, mapping=hash_data)
                        
                elif key_type == "list":
                    list_data = await redis_client.lrange(user_key, 0, -1)
                    if list_data:
                        await redis_client.rpush(new_key, *list_data)
                        
                elif key_type == "set":
                    set_data = await redis_client.smembers(user_key)
                    if set_data:
                        await redis_client.sadd(new_key, *set_data)
                        
                elif key_type == "zset":
                    zset_data = await redis_client.zrange(user_key, 0, -1, withscores=True)
                    if zset_data:
                        await redis_client.zadd(new_key, dict(zset_data))
            
            # completed: 패턴 키 마이그레이션
            completed_keys = await redis_client.keys(f"completed:user:{telegram_id}:*")
            for completed_key in completed_keys:
                # 키 이름에서 completed:user:{telegram_id}: 부분을 제거하여 접미사 추출
                key_suffix = completed_key.replace(f"completed:user:{telegram_id}:", "")
                new_key = f"completed:user:{okx_uid}:{key_suffix}"
                
                # 키 유형 확인
                key_type = await redis_client.type(completed_key)
                
                # 키 유형에 따라 다르게 처리
                if key_type == "string":
                    value = await redis_client.get(completed_key)
                    await redis_client.set(new_key, value)
                    
                elif key_type == "hash":
                    hash_data = await redis_client.hgetall(completed_key)
                    if hash_data:
                        await redis_client.hset(new_key, mapping=hash_data)
                        
                elif key_type == "list":
                    list_data = await redis_client.lrange(completed_key, 0, -1)
                    if list_data:
                        await redis_client.rpush(new_key, *list_data)
                        
                elif key_type == "set":
                    set_data = await redis_client.smembers(completed_key)
                    if set_data:
                        await redis_client.sadd(new_key, *set_data)
                        
                elif key_type == "zset":
                    zset_data = await redis_client.zrange(completed_key, 0, -1, withscores=True)
                    if zset_data:
                        await redis_client.zadd(new_key, dict(zset_data))
            
            migration_count += 1
            print(f"사용자 마이그레이션 완료: telegram_id={telegram_id}, okx_uid={okx_uid}")
            print(f"  - 복제된 user 키: {len(user_keys)}개")
            print(f"  - 복제된 completed 키: {len(completed_keys)}개")
            
        except Exception as e:
            print(f"마이그레이션 중 오류 발생: key={key}, error={str(e)}")
    
    print(f"총 {migration_count}명의 사용자에 대한 Redis 키 마이그레이션 완료")

# 수동 마이그레이션을 위한 함수 (Alembic 설정이 없는 경우)
def manual_migrate():
    engine = create_engine(settings.DATABASE_URL)
    metadata = MetaData()
    
    # users 테이블에 접근
    users = Table('users', metadata, autoload_with=engine)
    
    # okx_uid 컬럼이 없는지 확인
    if 'okx_uid' not in users.columns:
        # 컬럼 추가
        engine.execute('ALTER TABLE users ADD COLUMN okx_uid VARCHAR UNIQUE')
        engine.execute('CREATE INDEX ix_users_okx_uid ON users (okx_uid)')
        print("Added okx_uid column to users table")
    else:
        print("okx_uid column already exists")
    
    # Redis 마이그레이션 실행
    print("Redis 마이그레이션 시작...")
    try:
        # Redis 클라이언트 생성
        async def run_redis_migration():
            redis_client = redis.asyncio.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD,
                decode_responses=True
            )
            try:
                await migrate_redis_keys(redis_client)
            finally:
                await redis_client.close()
                
        asyncio.run(run_redis_migration())
    except Exception as e:
        print(f"Redis 마이그레이션 중 오류 발생: {str(e)}")

if __name__ == "__main__":
    # Alembic 설정이 없는 경우 수동으로 실행
    manual_migrate() 