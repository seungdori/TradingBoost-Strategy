"""Telegram 알림 모듈

통합된 Telegram 메시지 전송 모듈:
- 기본 메시지 전송
- 큐 기반 순차 전송 (속도 제한)
- OKX UID ↔ Telegram ID 변환
- 재시도 및 에러 처리
- 에러 알림 중복 제거
"""
import asyncio
import hashlib
import json
import logging
import os
import time
from enum import Enum
from typing import Any

import aiohttp

from shared.config import OWNER_ID

logger = logging.getLogger(__name__)


def _resolve_debug_chat_id() -> str | None:
    """DEBUG 전송용 텔레그램 ID를 환경 변수 또는 설정에서 조회"""
    env_debug_id = os.getenv("DEBUG_TELEGRAM_ID")
    if env_debug_id and env_debug_id.strip():
        return env_debug_id.strip()

    if OWNER_ID:
        return str(OWNER_ID)

    return None


class MessageType(str, Enum):
    """메시지 타입"""
    INFO = "ℹ️"
    SUCCESS = "✅"
    WARNING = "⚠️"
    ERROR = "❌"
    TRADE = "💰"
    POSITION = "📊"


# ============================================================================
# 에러 알림 중복 제거 (Error Deduplication)
# ============================================================================

async def should_send_error_notification(
    redis_client: Any,
    user_id: str,
    message: str,
    ttl_seconds: int = 300
) -> bool:
    """
    에러 알림을 보낼지 여부를 판단합니다 (중복 제거).

    같은 에러 메시지가 TTL 시간 내에 반복되면 알림을 보내지 않습니다.
    로깅은 별도로 처리되므로, 이 함수는 알림 전송 여부만 판단합니다.

    Args:
        redis_client: Redis 클라이언트 인스턴스
        user_id: 사용자 ID (okx_uid 또는 telegram_id)
        message: 메시지 내용
        ttl_seconds: 중복 제거 시간(초) - 기본 5분(300초)

    Returns:
        bool: True면 알림 전송, False면 중복으로 알림 생략

    Examples:
        >>> if await should_send_error_notification(redis, user_id, error_msg):
        ...     await send_telegram_message(error_msg, user_id)
        ... else:
        ...     logger.info(f"Duplicate error notification suppressed: {error_msg}")
    """
    try:
        # 메시지 해시 생성 (MD5 사용)
        message_hash = hashlib.md5(message.encode('utf-8')).hexdigest()[:16]

        # Redis 키 생성
        dedup_key = f"telegram:error_dedup:{user_id}:{message_hash}"

        # 키가 존재하는지 확인
        exists = await redis_client.exists(dedup_key)

        if exists:
            # 중복된 에러 - 알림 보내지 않음
            logger.debug(f"Duplicate error notification suppressed for user {user_id}: {message[:50]}...")
            return False

        # 중복이 아님 - 키 설정하고 알림 보냄
        await redis_client.set(dedup_key, "1", ex=ttl_seconds)
        return True

    except Exception as e:
        logger.error(f"Error in should_send_error_notification: {e}")
        # 에러 발생 시 안전을 위해 True 반환 (알림 보냄)
        return True


class TelegramNotifier:
    """Telegram 알림 관리 클래스"""

    def __init__(self, bot_token: str, default_chat_id: str | None = None):
        """
        Args:
            bot_token: Telegram 봇 토큰
            default_chat_id: 기본 채팅 ID (선택)
        """
        self.bot_token = bot_token
        self.default_chat_id = default_chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self._semaphore = asyncio.Semaphore(3)  # Rate limiting

    async def send_message(
        self,
        message: str,
        chat_id: str | None = None,
        message_type: MessageType = MessageType.INFO,
        parse_mode: str = "Markdown",
        disable_notification: bool = False,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> bool:
        """
        텔레그램 메시지 발송

        Args:
            message: 메시지 내용
            chat_id: 수신자 채팅 ID (없으면 기본값 사용)
            message_type: 메시지 타입 (아이콘 자동 추가)
            parse_mode: 파싱 모드 (Markdown, HTML)
            disable_notification: 알림 비활성화 여부
            max_retries: 최대 재시도 횟수
            retry_delay: 재시도 대기 시간

        Returns:
            성공 여부
        """
        target_chat_id = chat_id or self.default_chat_id

        if not target_chat_id:
            logger.error("채팅 ID가 제공되지 않았습니다")
            return False

        # 메시지 타입 아이콘 추가
        formatted_message = f"{message_type.value} {message}"

        async with self._semaphore:
            for attempt in range(max_retries):
                try:
                    async with aiohttp.ClientSession() as session:
                        url = f"{self.base_url}/sendMessage"
                        data = {
                            "chat_id": target_chat_id,
                            "text": formatted_message,
                            "parse_mode": parse_mode,
                            "disable_notification": disable_notification
                        }

                        async with session.post(url, json=data) as response:
                            if response.status == 200:
                                logger.info(f"메시지 전송 성공: {target_chat_id}")
                                return True
                            else:
                                error_text = await response.text()
                                logger.error(f"메시지 전송 실패 ({response.status}): {error_text}")

                except aiohttp.ClientError as e:
                    logger.error(f"네트워크 오류 (시도 {attempt + 1}/{max_retries}): {e}")
                except Exception as e:
                    logger.error(f"예기치 않은 오류 (시도 {attempt + 1}/{max_retries}): {e}")

                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (2 ** attempt))  # Exponential backoff

        logger.error(f"메시지 전송 실패: {max_retries}회 재시도 후 실패")
        return False

    async def send_trade_notification(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        chat_id: str | None = None
    ) -> bool:
        """
        거래 알림 발송

        Args:
            symbol: 거래 심볼
            side: 매수/매도 (long/short, buy/sell)
            quantity: 거래량
            price: 거래 가격
            chat_id: 수신자 채팅 ID

        Returns:
            성공 여부
        """
        message = (
            f"**거래 체결**\n"
            f"심볼: {symbol}\n"
            f"방향: {side.upper()}\n"
            f"수량: {quantity}\n"
            f"가격: {price}"
        )
        return await self.send_message(message, chat_id, MessageType.TRADE)

    async def send_position_notification(
        self,
        symbol: str,
        status: str,
        pnl: float | None = None,
        chat_id: str | None = None
    ) -> bool:
        """
        포지션 상태 알림 발송

        Args:
            symbol: 거래 심볼
            status: 포지션 상태 (opened, closed 등)
            pnl: 손익 (선택)
            chat_id: 수신자 채팅 ID

        Returns:
            성공 여부
        """
        message = f"**포지션 {status}**\n심볼: {symbol}"
        if pnl is not None:
            message += f"\n손익: {pnl:+.2f}"

        message_type = MessageType.SUCCESS if pnl and pnl > 0 else MessageType.POSITION
        return await self.send_message(message, chat_id, message_type)

    async def send_error_notification(
        self,
        error_message: str,
        details: str | None = None,
        chat_id: str | None = None
    ) -> bool:
        """
        에러 알림 발송

        Args:
            error_message: 에러 메시지
            details: 상세 정보 (선택)
            chat_id: 수신자 채팅 ID

        Returns:
            성공 여부
        """
        message = f"**에러 발생**\n{error_message}"
        if details:
            message += f"\n\n상세: {details}"

        return await self.send_message(message, chat_id, MessageType.ERROR)


# 간편 함수들 (기존 코드와의 호환성을 위해)

_default_notifier: TelegramNotifier | None = None


def initialize_telegram(bot_token: str, default_chat_id: str | None = None) -> None:
    """
    전역 Telegram Notifier 초기화

    Args:
        bot_token: Telegram 봇 토큰
        default_chat_id: 기본 채팅 ID
    """
    global _default_notifier
    _default_notifier = TelegramNotifier(bot_token, default_chat_id)
    logger.info("Telegram Notifier 초기화 완료")


async def send_telegram(
    message: str,
    chat_id: str | None = None,
    message_type: MessageType = MessageType.INFO
) -> bool:
    """
    간편 메시지 발송 함수

    Args:
        message: 메시지 내용
        chat_id: 수신자 채팅 ID
        message_type: 메시지 타입

    Returns:
        성공 여부
    """
    if _default_notifier is None:
        logger.error("Telegram Notifier가 초기화되지 않았습니다. initialize_telegram()을 먼저 호출하세요.")
        return False

    return await _default_notifier.send_message(message, chat_id, message_type)


async def send_trade_alert(
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    chat_id: str | None = None
) -> bool:
    """
    간편 거래 알림 함수

    Args:
        symbol: 거래 심볼
        side: 매수/매도
        quantity: 거래량
        price: 거래 가격
        chat_id: 수신자 채팅 ID

    Returns:
        성공 여부
    """
    if _default_notifier is None:
        logger.error("Telegram Notifier가 초기화되지 않았습니다.")
        return False

    return await _default_notifier.send_trade_notification(symbol, side, quantity, price, chat_id)


async def send_error_alert(
    error_message: str,
    details: str | None = None,
    chat_id: str | None = None
) -> bool:
    """
    간편 에러 알림 함수

    Args:
        error_message: 에러 메시지
        details: 상세 정보
        chat_id: 수신자 채팅 ID

    Returns:
        성공 여부
    """
    if _default_notifier is None:
        logger.error("Telegram Notifier가 초기화되지 않았습니다.")
        return False

    return await _default_notifier.send_error_notification(error_message, details, chat_id)


# ============================================================================
# 고급 기능: OKX UID ↔ Telegram ID 변환 및 큐 시스템
# ============================================================================

# Redis 키 형식 상수
MESSAGE_QUEUE_KEY = "telegram:message_queue:{okx_uid}"
MESSAGE_PROCESSING_FLAG = "telegram:processing_flag:{okx_uid}"


async def get_telegram_id(
    identifier: str,
    redis_client: Any,
    order_backend_url: str,
    db_session: Any = None
) -> int | None:
    """
    식별자가 okx_uid인지 telegram_id인지 확인하고 적절한 telegram_id를 반환합니다.

    3단계 조회 전략:
    1. 11자리 이하 숫자: telegram_id로 간주하고 그대로 반환
    2. 12자리 이상 (okx_uid): UserIdentifierService로 조회 (DB + Redis cache)
    3. Fallback: ORDER_BACKEND API 호출 (기존 방식)

    Args:
        identifier: 확인할 식별자 (okx_uid 또는 telegram_id)
        redis_client: Redis 클라이언트 인스턴스
        order_backend_url: ORDER_BACKEND API URL
        db_session: Database session (optional, for UserIdentifierService)

    Returns:
        int: 텔레그램 ID 또는 None
    """
    if not identifier:
        return None

    # 11글자 이하면 telegram_id로 간주
    if len(str(identifier)) <= 11:
        logger.debug(f"식별자를 Telegram ID로 간주: {identifier}")
        return int(identifier)

    # 12글자 이상이면 okx_uid로 간주
    okx_uid = str(identifier)

    # 1차 시도: UserIdentifierService 사용 (DB + Redis cache)
    if db_session:
        try:
            from shared.services.user_identifier_service import UserIdentifierService

            service = UserIdentifierService(db_session, redis_client)
            telegram_id = await service.get_telegram_id_by_okx_uid(okx_uid)

            if telegram_id:
                logger.info(f"UserIdentifierService로 telegram_id 조회 성공: {telegram_id}")
                return telegram_id
            else:
                logger.debug(f"UserIdentifierService에 okx_uid={okx_uid} 매핑이 없습니다.")
        except Exception as e:
            logger.warning(f"UserIdentifierService 조회 실패, ORDER_BACKEND로 fallback: {str(e)}")

    # 2차 시도: ORDER_BACKEND API 호출 (Fallback)
    if not order_backend_url:
        logger.warning(
            "ORDER_BACKEND가 설정되지 않고 DB 조회도 실패하여 OKX UID를 텔레그램 ID로 변환할 수 없습니다: %s",
            identifier,
        )
        return None

    try:
        api_url = f"/api/user/okx/{identifier}/telegram"
        full_url = f"{order_backend_url}{api_url}"
        logger.info(f"ORDER_BACKEND API로 OKX UID {identifier} 조회: {full_url}")

        async with aiohttp.ClientSession() as session:
            async with session.get(full_url) as response:
                if response.status == 200:
                    data = await response.json()

                    # primary_telegram_id 먼저 확인
                    primary_id = data.get("primary_telegram_id")
                    if primary_id:
                        logger.info(f"Primary 텔레그램 ID 조회 성공: {primary_id}")
                        return int(primary_id)

                    # primary가 없으면 all_telegram_ids 배열에서 첫 번째 값 사용
                    all_ids = data.get("all_telegram_ids", [])
                    if all_ids and len(all_ids) > 0:
                        first_id = all_ids[0]
                        logger.info(f"첫 번째 텔레그램 ID 사용: {first_id}")
                        return int(first_id)

                    logger.error(f"텔레그램 ID가 응답에 없습니다: {data}")
                    return None
                else:
                    logger.error(f"텔레그램 ID 조회 실패: HTTP {response.status}")
                    return None
    except Exception as e:
        logger.error(f"텔레그램 ID 조회 중 오류: {str(e)}")
        return None


async def enqueue_telegram_message(
    message: str,
    okx_uid: str,
    redis_client: Any,
    debug: bool = False
) -> bool:
    """
    텔레그램 메시지를 Redis 큐에 추가합니다.

    Args:
        message: 전송할 메시지
        okx_uid: OKX UID 또는 Telegram ID
        redis_client: Redis 클라이언트 인스턴스
        debug: 디버그 모드 (기본 사용자로 전송)

    Returns:
        bool: 성공 여부
    """
    try:
        queue_key = MESSAGE_QUEUE_KEY.format(okx_uid=okx_uid)

        # 메시지 데이터 구성 (타임스탬프 포함)
        message_data = {
            "message": message,
            "timestamp": time.time(),
            "okx_uid": okx_uid,
            "debug": debug
        }

        # Redis 큐에 메시지 추가 (JSON 문자열로 변환)
        await redis_client.rpush(queue_key, json.dumps(message_data))

        # 메시지 처리 플래그 확인 및 설정
        processing_flag = MESSAGE_PROCESSING_FLAG.format(okx_uid=okx_uid)
        is_processing = await redis_client.get(processing_flag)

        # 처리 중이 아니면 메시지 처리 시작
        if not is_processing:
            await redis_client.set(processing_flag, "1", ex=300)  # 5분 타임아웃
            # Note: process_telegram_messages는 외부에서 호출되어야 함
            logger.info(f"메시지 큐 처리 플래그 설정: {okx_uid}")

        return True
    except Exception as e:
        logger.error(f"메시지 큐 추가 실패: {str(e)}")
        return False


async def process_telegram_messages(
    okx_uid: str,
    redis_client: Any,
    bot_token: str,
    order_backend_url: str,
    debug: bool = False,
    db_session: Any = None
) -> None:
    """
    Redis 큐에서 메시지를 가져와 순차적으로 텔레그램으로 전송합니다 (레거시 함수 - OKX UID 변환).

    Args:
        okx_uid: OKX UID 또는 Telegram ID
        redis_client: Redis 클라이언트 인스턴스
        bot_token: Telegram 봇 토큰
        order_backend_url: ORDER_BACKEND API URL
        debug: 디버그 모드
        db_session: Database session (optional, for UserIdentifierService)
    """
    # Telegram ID 조회
    telegram_id = await get_telegram_id(okx_uid, redis_client, order_backend_url, db_session)
    if not telegram_id and not debug:
        logger.error(f"텔레그램 ID를 찾을 수 없습니다: {okx_uid}")
        return

    # 새로운 함수로 위임
    await process_telegram_messages_direct(telegram_id, redis_client, bot_token, debug)


async def process_telegram_messages_direct(
    telegram_id: int,
    redis_client: Any,
    bot_token: str,
    debug: bool = False
) -> None:
    """
    Redis 큐에서 메시지를 가져와 순차적으로 텔레그램으로 전송합니다 (개선 버전 - telegram_id 직접).

    Args:
        telegram_id: Telegram ID (정수)
        redis_client: Redis 클라이언트 인스턴스
        bot_token: Telegram 봇 토큰
        debug: 디버그 모드
    """
    queue_key = MESSAGE_QUEUE_KEY.format(okx_uid=str(telegram_id))
    processing_flag = MESSAGE_PROCESSING_FLAG.format(okx_uid=str(telegram_id))

    # TelegramNotifier 생성
    notifier = TelegramNotifier(bot_token, str(telegram_id))

    try:
        while True:
            # 큐에서 메시지 가져오기 (블로킹 방식, 1초 타임아웃)
            message_data = await redis_client.blpop(queue_key, 1)

            # 큐가 비어있으면 처리 종료
            if not message_data:
                await redis_client.delete(processing_flag)
                break

            # 메시지 데이터 파싱
            _, message_json = message_data
            message_obj = json.loads(message_json)

            # 텔레그램으로 메시지 전송
            await notifier.send_message(
                message_obj["message"],
                chat_id=str(telegram_id),
                message_type=MessageType.INFO
            )

            # 속도 제한을 위한 짧은 대기
            await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"메시지 처리 중 오류 발생: {str(e)}")
        await redis_client.delete(processing_flag)


# ============================================================================
# HYPERRSI 호환성 함수
# ============================================================================

async def send_telegram_message_legacy(
    message: str,
    okx_uid: str,
    redis_client: Any,
    bot_token: str,
    order_backend_url: str,
    debug: bool = False,
    use_queue: bool = True,
    db_session: Any = None
) -> bool:
    """
    텔레그램 메시지를 전송합니다 (레거시 함수 - OKX UID 자동 변환).

    이 함수는 하위 호환성을 위해 유지되며, 새로운 코드에서는 send_telegram_message()를 사용하세요.

    Args:
        message: 전송할 메시지
        okx_uid: OKX UID 또는 Telegram ID
        redis_client: Redis 클라이언트 인스턴스
        bot_token: Telegram 봇 토큰
        order_backend_url: ORDER_BACKEND API URL
        debug: 디버그 모드
        use_queue: 큐 시스템 사용 여부 (기본: True)
        db_session: Database session (optional, for UserIdentifierService)

    Returns:
        bool: 성공 여부
    """
    # Telegram ID 조회
    telegram_id = await get_telegram_id(okx_uid, redis_client, order_backend_url, db_session)
    if not telegram_id and not debug:
        logger.error(f"텔레그램 ID를 찾을 수 없습니다: {okx_uid}")
        return False

    # 새로운 함수로 위임
    return await send_telegram_message(
        message=message,
        telegram_id=telegram_id,
        bot_token=bot_token,
        user_id=okx_uid,
        debug=debug,
        use_queue=use_queue,
        redis_client=redis_client
    )


async def send_telegram_message(
    message: str,
    telegram_id: int,
    bot_token: str,
    user_id: str | None = None,
    debug: bool = False,
    use_queue: bool = True,
    redis_client: Any = None
) -> bool:
    """
    텔레그램 메시지를 전송합니다 (개선된 버전: telegram_id 명시).

    Args:
        message: 전송할 메시지
        telegram_id: 텔레그램 ID (정수)
        bot_token: Telegram 봇 토큰
        user_id: 사용자 식별자 (로깅/디버깅용, 선택적)
        debug: 디버그 모드
        use_queue: 큐 시스템 사용 여부 (기본: True)
        redis_client: Redis 클라이언트 인스턴스 (큐 사용 시 필수)

    Returns:
        bool: 성공 여부
    """
    target_telegram_id = telegram_id
    message_to_send = message

    if debug:
        debug_chat_id = _resolve_debug_chat_id()
        if not debug_chat_id:
            logger.error("디버그 텔레그램 ID가 설정되지 않아 메시지를 전송할 수 없습니다.")
            return False

        target_telegram_id = debug_chat_id

        if user_id:
            message_to_send = f"[debug::{user_id}] {message}"

    if use_queue:
        if not redis_client:
            logger.error("큐 시스템 사용 시 redis_client가 필요합니다.")
            return False

        # 큐에 메시지 추가
        success = await enqueue_telegram_message(
            message_to_send,
            str(target_telegram_id),
            redis_client,
            debug
        )
        if success:
            # 큐 처리 시작 (백그라운드 태스크)
            asyncio.create_task(
                process_telegram_messages_direct(
                    target_telegram_id,
                    redis_client,
                    bot_token,
                    debug
                )
            )
        return success
    else:
        # 직접 전송
        notifier = TelegramNotifier(bot_token, str(target_telegram_id))
        return await notifier.send_message(message_to_send, chat_id=str(target_telegram_id))
