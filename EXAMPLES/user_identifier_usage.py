"""
User Identifier 시스템 사용 예제

Solution 1 (telegram_id 명시) + Solution 3 (UserIdentifierService) 통합 사용 예제
"""

import asyncio
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from shared.config import get_settings
from shared.database.redis_helper import get_redis_client
from shared.services.user_identifier_service import UserIdentifierService
from shared.notifications.telegram import send_telegram_message, get_telegram_id
from shared.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()


# ============================================================================
# 예제 1: 새로운 사용자 등록 및 메시지 전송
# ============================================================================

async def example_1_new_user_registration(
    db_session: AsyncSession,
    redis_client,
    telegram_id: int,
    okx_uid: Optional[str] = None
):
    """
    새로운 사용자를 등록하고 환영 메시지를 전송합니다.

    Args:
        db_session: Database session
        redis_client: Redis client
        telegram_id: 텔레그램 ID
        okx_uid: OKX UID (선택)
    """
    logger.info("=" * 70)
    logger.info("예제 1: 새로운 사용자 등록")
    logger.info("=" * 70)

    # Step 1: UUID 생성
    user_id = str(uuid.uuid4())
    logger.info(f"생성된 user_id: {user_id}")

    # Step 2: UserIdentifierService로 매핑 생성
    service = UserIdentifierService(db_session, redis_client)

    mapping = await service.create_mapping(
        user_id=user_id,
        telegram_id=telegram_id,
        okx_uid=okx_uid
    )

    logger.info(f"매핑 생성 완료: {mapping}")

    # Step 3: 환영 메시지 전송 (Solution 1 사용)
    success = await send_telegram_message(
        message="🎉 환영합니다! 계정이 성공적으로 생성되었습니다.",
        telegram_id=mapping.telegram_id,
        bot_token=settings.TELEGRAM_BOT_TOKEN,
        user_id=mapping.user_id,
        redis_client=redis_client
    )

    logger.info(f"메시지 전송 결과: {'성공' if success else '실패'}")
    return mapping


# ============================================================================
# 예제 2: 기존 user_id로 telegram_id 조회 (Redis 캐시 활용)
# ============================================================================

async def example_2_lookup_by_user_id(
    db_session: AsyncSession,
    redis_client,
    user_id: str
):
    """
    user_id로 telegram_id를 조회하고 메시지를 전송합니다.

    Args:
        db_session: Database session
        redis_client: Redis client
        user_id: 사용자 ID
    """
    logger.info("=" * 70)
    logger.info("예제 2: user_id로 telegram_id 조회")
    logger.info("=" * 70)

    # Step 1: UserIdentifierService로 조회 (Redis 캐시 활용)
    service = UserIdentifierService(db_session, redis_client)

    telegram_id = await service.get_telegram_id_by_user_id(user_id)

    if not telegram_id:
        logger.warning(f"user_id={user_id}에 대한 telegram_id를 찾을 수 없습니다.")
        return None

    logger.info(f"조회된 telegram_id: {telegram_id}")

    # Step 2: 메시지 전송
    success = await send_telegram_message(
        message="📊 조회 테스트 메시지입니다.",
        telegram_id=telegram_id,
        bot_token=settings.TELEGRAM_BOT_TOKEN,
        user_id=user_id,
        redis_client=redis_client
    )

    logger.info(f"메시지 전송 결과: {'성공' if success else '실패'}")
    return telegram_id


# ============================================================================
# 예제 3: OKX UID로 조회 후 거래 알림 전송
# ============================================================================

async def example_3_trade_notification_by_okx_uid(
    db_session: AsyncSession,
    redis_client,
    okx_uid: str,
    symbol: str,
    side: str,
    price: float,
    quantity: float
):
    """
    OKX UID로 조회하여 거래 알림을 전송합니다.

    Args:
        db_session: Database session
        redis_client: Redis client
        okx_uid: OKX UID
        symbol: 거래 심볼
        side: 매수/매도
        price: 거래 가격
        quantity: 거래 수량
    """
    logger.info("=" * 70)
    logger.info("예제 3: OKX UID로 거래 알림 전송")
    logger.info("=" * 70)

    # Step 1: OKX UID로 telegram_id 조회
    service = UserIdentifierService(db_session, redis_client)

    telegram_id = await service.get_telegram_id_by_okx_uid(okx_uid)

    if not telegram_id:
        logger.warning(f"okx_uid={okx_uid}에 대한 telegram_id를 찾을 수 없습니다.")
        return False

    logger.info(f"조회된 telegram_id: {telegram_id}")

    # Step 2: 거래 알림 메시지 작성
    message = (
        f"📈 **거래 체결 알림**\n\n"
        f"심볼: {symbol}\n"
        f"타입: {side}\n"
        f"가격: ${price:,.2f}\n"
        f"수량: {quantity:.4f}\n"
        f"총액: ${price * quantity:,.2f}"
    )

    # Step 3: 메시지 전송
    success = await send_telegram_message(
        message=message,
        telegram_id=telegram_id,
        bot_token=settings.TELEGRAM_BOT_TOKEN,
        user_id=okx_uid,
        redis_client=redis_client
    )

    logger.info(f"거래 알림 전송 결과: {'성공' if success else '실패'}")
    return success


# ============================================================================
# 예제 4: 레거시 방식 vs 새 방식 비교
# ============================================================================

async def example_4_legacy_vs_new(
    db_session: AsyncSession,
    redis_client,
    okx_uid: str
):
    """
    레거시 방식과 새 방식의 성능을 비교합니다.

    Args:
        db_session: Database session
        redis_client: Redis client
        okx_uid: OKX UID
    """
    logger.info("=" * 70)
    logger.info("예제 4: 레거시 vs 새 방식 성능 비교")
    logger.info("=" * 70)

    import time

    # 레거시 방식
    start = time.time()
    telegram_id_legacy = await get_telegram_id(
        identifier=okx_uid,
        redis_client=redis_client,
        order_backend_url=settings.ORDER_BACKEND
    )
    legacy_time = (time.time() - start) * 1000  # ms

    logger.info(f"레거시 방식 시간: {legacy_time:.2f}ms")

    # 새 방식 (UserIdentifierService with Redis cache)
    service = UserIdentifierService(db_session, redis_client)

    start = time.time()
    telegram_id_new = await service.get_telegram_id_by_okx_uid(okx_uid)
    new_time = (time.time() - start) * 1000  # ms

    logger.info(f"새 방식 시간: {new_time:.2f}ms")

    # 성능 개선율 계산
    if legacy_time > 0:
        improvement = ((legacy_time - new_time) / legacy_time) * 100
        logger.info(f"성능 개선: {improvement:.1f}% 향상")

    return telegram_id_new


# ============================================================================
# 메인 실행 함수
# ============================================================================

async def main():
    """메인 실행 함수 - 모든 예제를 순차적으로 실행합니다."""

    # 데이터베이스 설정
    database_url = settings.DATABASE_URL
    if database_url.startswith("sqlite"):
        database_url = database_url.replace("sqlite://", "sqlite+aiosqlite://")

    engine = create_async_engine(database_url, echo=False)
    async_session_factory = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # Redis 클라이언트
    redis_client = await get_redis_client()

    try:
        async with async_session_factory() as session:
            # 예제 1: 새로운 사용자 등록
            mapping = await example_1_new_user_registration(
                session,
                redis_client,
                telegram_id=123456789,
                okx_uid="test-okx-uid-001"
            )

            print("\n" + "=" * 70 + "\n")

            # 예제 2: user_id로 조회
            await example_2_lookup_by_user_id(
                session,
                redis_client,
                user_id=mapping.user_id
            )

            print("\n" + "=" * 70 + "\n")

            # 예제 3: OKX UID로 거래 알림
            await example_3_trade_notification_by_okx_uid(
                session,
                redis_client,
                okx_uid=mapping.okx_uid,
                symbol="BTC-USDT",
                side="BUY",
                price=45000.00,
                quantity=0.01
            )

            print("\n" + "=" * 70 + "\n")

            # 예제 4: 성능 비교
            await example_4_legacy_vs_new(
                session,
                redis_client,
                okx_uid=mapping.okx_uid
            )

    except Exception as e:
        logger.error(f"예제 실행 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()

    finally:
        await engine.dispose()
        await redis_client.close()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("User Identifier 시스템 사용 예제")
    print("=" * 70 + "\n")

    asyncio.run(main())
