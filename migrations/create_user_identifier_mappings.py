"""
데이터베이스 마이그레이션: user_identifier_mappings 테이블 생성

실행 방법:
    python migrations/create_user_identifier_mappings.py

기능:
    1. user_identifier_mappings 테이블 생성
    2. 기존 hyperrsi_users 테이블에서 데이터 마이그레이션
    3. 인덱스 생성으로 조회 성능 최적화
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from shared.config import get_settings
from shared.database.models import Base, UserIdentifierMapping
from shared.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()


async def create_tables(engine):
    """테이블을 생성합니다."""
    logger.info("user_identifier_mappings 테이블 생성 중...")

    async with engine.begin() as conn:
        # 테이블 생성
        await conn.run_sync(Base.metadata.create_all)

    logger.info("✅ 테이블 생성 완료")


async def migrate_existing_data(session: AsyncSession):
    """
    기존 hyperrsi_users 테이블에서 데이터를 마이그레이션합니다.
    """
    logger.info("기존 데이터 마이그레이션 시작...")

    try:
        # hyperrsi_users 테이블에서 데이터 조회
        query = text("""
            SELECT id, telegram_id, okx_uid
            FROM hyperrsi_users
            WHERE telegram_id IS NOT NULL
        """)

        result = await session.execute(query)
        users = result.fetchall()

        migrated_count = 0
        skipped_count = 0

        for user in users:
            user_id, telegram_id, okx_uid = user

            # 이미 존재하는지 확인
            check_query = text("""
                SELECT COUNT(*) FROM user_identifier_mappings
                WHERE user_id = :user_id
            """)
            exists = await session.execute(check_query, {"user_id": user_id})
            if exists.scalar() > 0:
                logger.debug(f"user_id={user_id} 이미 존재, 건너뜀")
                skipped_count += 1
                continue

            # 새로운 매핑 생성
            mapping = UserIdentifierMapping(
                user_id=user_id,
                telegram_id=telegram_id,
                okx_uid=okx_uid,
                is_active=1
            )

            session.add(mapping)
            migrated_count += 1

        await session.commit()

        logger.info(f"✅ 데이터 마이그레이션 완료: {migrated_count}개 마이그레이션, {skipped_count}개 건너뜀")

    except Exception as e:
        logger.error(f"❌ 데이터 마이그레이션 실패: {str(e)}")
        await session.rollback()
        raise


async def verify_migration(session: AsyncSession):
    """마이그레이션 결과를 검증합니다."""
    logger.info("마이그레이션 검증 중...")

    # 총 레코드 수 확인
    count_query = text("SELECT COUNT(*) FROM user_identifier_mappings")
    result = await session.execute(count_query)
    total_count = result.scalar()

    # 활성 레코드 수 확인
    active_query = text("SELECT COUNT(*) FROM user_identifier_mappings WHERE is_active = 1")
    result = await session.execute(active_query)
    active_count = result.scalar()

    # OKX UID가 있는 레코드 수 확인
    okx_query = text("SELECT COUNT(*) FROM user_identifier_mappings WHERE okx_uid IS NOT NULL")
    result = await session.execute(okx_query)
    okx_count = result.scalar()

    logger.info(f"""
검증 결과:
    - 총 레코드 수: {total_count}
    - 활성 레코드 수: {active_count}
    - OKX UID 보유 레코드 수: {okx_count}
    """)

    # 샘플 데이터 출력
    sample_query = text("""
        SELECT user_id, telegram_id, okx_uid, is_active
        FROM user_identifier_mappings
        LIMIT 5
    """)
    result = await session.execute(sample_query)
    samples = result.fetchall()

    logger.info("샘플 데이터 (최대 5개):")
    for sample in samples:
        user_id, telegram_id, okx_uid, is_active = sample
        logger.info(f"  - user_id={user_id}, telegram_id={telegram_id}, okx_uid={okx_uid}, active={is_active}")


async def main():
    """메인 마이그레이션 함수"""
    logger.info("=" * 70)
    logger.info("User Identifier Mappings 테이블 마이그레이션 시작")
    logger.info("=" * 70)

    # 데이터베이스 URL 구성 (환경 변수 또는 직접 구성)
    database_url = settings.DATABASE_URL

    # DATABASE_URL property가 빈 문자열인 경우, 수동으로 구성
    if not database_url:
        if settings.DB_USER and settings.DB_PASSWORD and settings.DB_HOST and settings.DB_NAME:
            database_url = f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
            logger.info(f"DATABASE_URL 수동 구성: {settings.DB_USER}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
        else:
            logger.error("❌ DATABASE_URL이 설정되지 않았습니다.")
            logger.info("환경 변수 또는 .env 파일에서 DB_USER, DB_PASSWORD, DB_HOST, DB_NAME을 설정하세요.")
            return

    # SQLite 비동기 드라이버 사용
    if database_url.startswith("sqlite"):
        database_url = database_url.replace("sqlite://", "sqlite+aiosqlite://")

    engine = create_async_engine(
        database_url,
        echo=False,  # SQL 로깅 비활성화
        future=True
    )

    # 세션 팩토리 생성
    async_session_factory = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    try:
        # 1. 테이블 생성
        await create_tables(engine)

        # 2. 기존 데이터 마이그레이션
        async with async_session_factory() as session:
            await migrate_existing_data(session)

        # 3. 마이그레이션 검증
        async with async_session_factory() as session:
            await verify_migration(session)

        logger.info("=" * 70)
        logger.info("✅ 마이그레이션 성공적으로 완료!")
        logger.info("=" * 70)

    except Exception as e:
        logger.error(f"❌ 마이그레이션 실패: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
