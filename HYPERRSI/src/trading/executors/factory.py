"""
Executor Factory - Strategy Pattern Factory

각 Trading Instance별 execution_mode에 따라 적절한 주문 실행 전략을 선택

Flow:
1. User settings에서 execution_mode 확인
2. API Direct 또는 Signal Bot Executor 반환

중요: execution_mode는 유저별이 아니라 "실행별"로 구분됨
  - User A: BTC 거래는 Signal Bot, ETH 거래는 API Direct 가능
"""

from typing import Dict, Optional

from HYPERRSI.src.api.dependencies import get_user_api_keys
from HYPERRSI.src.trading.executors.api_direct_executor import APIDirectExecutor
from HYPERRSI.src.trading.executors.base_executor import BaseExecutor
from HYPERRSI.src.trading.executors.signal_bot_executor import SignalBotExecutor
from shared.logging import get_logger

logger = get_logger(__name__)


class ExecutorFactory:
    """
    주문 실행 전략 팩토리

    각 Trading Instance별 execution_mode에 따라 적절한 Executor 선택:
    - api_direct → APIDirectExecutor (CCXT 기반)
    - signal_bot → SignalBotExecutor (OKX Webhook)

    주의: execution_mode는 실행별로 다를 수 있음!
    """

    @staticmethod
    async def get_executor(
        user_id: str,
        symbol: str,
        settings: Optional[Dict] = None
    ) -> BaseExecutor:
        """
        Trading Instance 설정에 따른 Executor 반환

        Args:
            user_id: 사용자 ID
            symbol: 거래 심볼 (예: 'BTC-USDT-SWAP')
            settings: Trading 설정 (execution_mode, signal_bot_token 등 포함)
                     None이면 Redis에서 조회

        Returns:
            BaseExecutor: API Direct 또는 Signal Bot Executor

        Raises:
            ValueError: 설정이 없거나 필수 파라미터 누락 시

        Example:
            # BTC는 Signal Bot으로, ETH는 API Direct로 거래
            executor1 = await ExecutorFactory.get_executor(
                user_id="123",
                symbol="BTC-USDT-SWAP",
                settings={
                    "execution_mode": "api_direct",  # 글로벌 기본값
                    "symbol_execution_modes": {
                        "BTC-USDT-SWAP": "signal_bot"  # BTC만 override
                    },
                    "signal_bot_token": "abc123",
                    "signal_bot_webhook_url": "https://..."
                }
            )
        """
        # 1. Settings 조회 (없으면 Redis에서 가져오기)
        if settings is None:
            from HYPERRSI.src.services.redis_service import redis_service
            settings = await redis_service.get_user_settings(user_id)

            if not settings:
                raise ValueError(
                    f"User {user_id} has no settings. "
                    f"Please configure trading settings first."
                )

        # 2. Execution mode 확인: 심볼별 override → 글로벌 기본값 순서로 체크
        symbol_execution_modes = settings.get("symbol_execution_modes", {})
        execution_mode = symbol_execution_modes.get(
            symbol,
            settings.get("execution_mode", "api_direct")  # 기본값: api_direct
        )

        logger.info(
            f"[ExecutorFactory] Creating executor for user {user_id}, symbol {symbol}: "
            f"mode={execution_mode} "
            f"(symbol_override={symbol in symbol_execution_modes})"
        )

        # 3. Signal Bot 모드
        if execution_mode == "signal_bot":
            signal_bot_token = settings.get("signal_bot_token")
            signal_bot_webhook_url = settings.get("signal_bot_webhook_url")

            if not signal_bot_token:
                raise ValueError(
                    f"User {user_id} is set to signal_bot mode but has no token in settings. "
                    f"Please configure Signal Bot token first."
                )

            if not signal_bot_webhook_url:
                raise ValueError(
                    f"User {user_id} is set to signal_bot mode but has no webhook URL. "
                    f"Please configure Signal Bot webhook URL first."
                )

            logger.info(
                f"[ExecutorFactory] Using SignalBotExecutor for user {user_id}"
            )

            return SignalBotExecutor(
                user_id=user_id,
                signal_token=signal_bot_token,
                webhook_url=signal_bot_webhook_url,
            )

        # 4. API Direct 모드 (기본값)
        else:
            # API 키 가져오기
            api_keys = await get_user_api_keys(user_id)

            if not api_keys or not api_keys.get('api_key'):
                raise ValueError(
                    f"User {user_id} has no API keys configured. "
                    f"Please configure OKX API keys first."
                )

            logger.info(
                f"[ExecutorFactory] Using APIDirectExecutor for user {user_id}"
            )

            return APIDirectExecutor(
                user_id=user_id,
                api_keys=api_keys
            )

    @staticmethod
    async def update_execution_settings(
        user_id: str,
        mode: str,
        signal_bot_token: Optional[str] = None,
        signal_bot_webhook_url: Optional[str] = None,
    ) -> Dict:
        """
        Trading Instance의 실행 모드 설정 업데이트

        주의: 이 설정은 유저 전체가 아니라 특정 trading instance에 적용됨

        Args:
            user_id: 사용자 ID
            mode: 'api_direct' | 'signal_bot'
            signal_bot_token: Signal Bot 토큰 (signal_bot 모드 시 필수)
            signal_bot_webhook_url: Signal Bot webhook URL (signal_bot 모드 시 필수)

        Returns:
            Dict: 업데이트된 설정

        Raises:
            ValueError: 잘못된 모드 또는 필수 파라미터 누락

        Example:
            # BTC 거래를 Signal Bot으로 설정
            await ExecutorFactory.update_execution_settings(
                user_id="123",
                mode="signal_bot",
                signal_bot_token="abc123",
                signal_bot_webhook_url="https://..."
            )

            # 나중에 ETH 거래를 API Direct로 설정 (다른 설정 객체 사용)
            # settings를 별도로 관리하면 됨
        """
        if mode not in ('api_direct', 'signal_bot'):
            raise ValueError(
                f"Invalid execution mode: {mode}. "
                f"Must be 'api_direct' or 'signal_bot'"
            )

        if mode == 'signal_bot' and (not signal_bot_token or not signal_bot_webhook_url):
            raise ValueError(
                "Signal Bot mode requires both signal_bot_token and "
                "signal_bot_webhook_url"
            )

        # Redis에서 기존 설정 가져오기
        from HYPERRSI.src.services.redis_service import redis_service

        settings = await redis_service.get_user_settings(user_id)

        if not settings:
            from shared.constants.default_settings import DEFAULT_PARAMS_SETTINGS
            settings = DEFAULT_PARAMS_SETTINGS.copy()

        # 실행 모드 업데이트
        settings["execution_mode"] = mode

        if mode == 'signal_bot':
            settings["signal_bot_token"] = signal_bot_token
            settings["signal_bot_webhook_url"] = signal_bot_webhook_url
        else:
            # API Direct 모드로 전환 시 Signal Bot 정보 유지 (나중에 다시 사용 가능)
            # 완전 삭제하려면 주석 해제:
            # settings["signal_bot_token"] = None
            # settings["signal_bot_webhook_url"] = None
            pass

        # Redis에 저장
        await redis_service.set_user_settings(user_id, settings)

        logger.info(
            f"[ExecutorFactory] User {user_id} execution settings updated: "
            f"mode={mode}"
        )

        return settings
