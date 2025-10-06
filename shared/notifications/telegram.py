"""Telegram 알림 모듈

통합된 Telegram 메시지 전송 모듈:
- 기본 메시지 전송
- 큐 기반 순차 전송 (속도 제한)
- OKX UID ↔ Telegram ID 변환
- 재시도 및 에러 처리
"""
import asyncio
import logging
import json
import time
from typing import Any
from enum import Enum
import aiohttp

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """메시지 타입"""
    INFO = "ℹ️"
    SUCCESS = "✅"
    WARNING = "⚠️"
    ERROR = "❌"
    TRADE = "💰"
    POSITION = "📊"


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
    order_backend_url: str
) -> int | None:
    """
    식별자가 okx_uid인지 telegram_id인지 확인하고 적절한 telegram_id를 반환합니다.

    Args:
        identifier: 확인할 식별자 (okx_uid 또는 telegram_id)
        redis_client: Redis 클라이언트 인스턴스
        order_backend_url: ORDER_BACKEND API URL

    Returns:
        int: 텔레그램 ID 또는 None
    """
    if not identifier:
        return None

    # 11글자 이하면 telegram_id로 간주
    if len(str(identifier)) <= 11:
        logger.debug(f"식별자를 Telegram ID로 간주: {identifier}")
        return int(identifier)

    # 12글자 이상이면 okx_uid로 간주하고 텔레그램 ID 조회
    try:
        api_url = f"/api/user/okx/{identifier}/telegram"
        full_url = f"{order_backend_url}{api_url}"
        logger.info(f"OKX UID {identifier}에 대한 텔레그램 ID 조회: {full_url}")

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
    debug: bool = False
) -> None:
    """
    Redis 큐에서 메시지를 가져와 순차적으로 텔레그램으로 전송합니다.

    Args:
        okx_uid: OKX UID 또는 Telegram ID
        redis_client: Redis 클라이언트 인스턴스
        bot_token: Telegram 봇 토큰
        order_backend_url: ORDER_BACKEND API URL
        debug: 디버그 모드
    """
    queue_key = MESSAGE_QUEUE_KEY.format(okx_uid=okx_uid)
    processing_flag = MESSAGE_PROCESSING_FLAG.format(okx_uid=okx_uid)

    # Telegram ID 조회
    telegram_id = await get_telegram_id(okx_uid, redis_client, order_backend_url)
    if not telegram_id and not debug:
        logger.error(f"텔레그램 ID를 찾을 수 없습니다: {okx_uid}")
        await redis_client.delete(processing_flag)
        return

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

async def send_telegram_message(
    message: str,
    okx_uid: str,
    redis_client: Any,
    bot_token: str,
    order_backend_url: str,
    debug: bool = False,
    use_queue: bool = True
) -> bool:
    """
    텔레그램 메시지를 전송합니다 (HYPERRSI 호환성 함수).

    Args:
        message: 전송할 메시지
        okx_uid: OKX UID 또는 Telegram ID
        redis_client: Redis 클라이언트 인스턴스
        bot_token: Telegram 봇 토큰
        order_backend_url: ORDER_BACKEND API URL
        debug: 디버그 모드
        use_queue: 큐 시스템 사용 여부 (기본: True)

    Returns:
        bool: 성공 여부
    """
    if use_queue:
        # 큐에 메시지 추가
        success = await enqueue_telegram_message(message, okx_uid, redis_client, debug)
        if success:
            # 큐 처리 시작 (백그라운드 태스크)
            asyncio.create_task(
                process_telegram_messages(okx_uid, redis_client, bot_token, order_backend_url, debug)
            )
        return success
    else:
        # 직접 전송
        telegram_id = await get_telegram_id(okx_uid, redis_client, order_backend_url)
        if not telegram_id and not debug:
            logger.error(f"텔레그램 ID를 찾을 수 없습니다: {okx_uid}")
            return False

        notifier = TelegramNotifier(bot_token, str(telegram_id))
        return await notifier.send_message(message, chat_id=str(telegram_id))
