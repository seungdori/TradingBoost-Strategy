"""
Position Handler Exit Module

This module handles position exit logic based on trend reversal conditions.
Includes position closing, stats update, and Redis cleanup.
"""

import traceback
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

# Type checking imports (순환 import 방지)
if TYPE_CHECKING:
    from HYPERRSI.src.trading.trading_service import TradingService

from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.core.logger import setup_error_logger
from HYPERRSI.src.trading.executors import ExecutorFactory
from HYPERRSI.src.trading.models import Position
from HYPERRSI.src.trading.stats import update_trading_stats
from HYPERRSI.src.trading.utils.position_handler.constants import (
    DCA_COUNT_KEY,
    DCA_LEVELS_KEY,
    POSITION_KEY,
    POSITION_SIDE_KEYS,
    POSITION_SYMBOL_KEYS,
    TREND_STATE_STRONG_DOWNTREND,
    TREND_STATE_STRONG_UPTREND,
)

# Import from position_handler package
from HYPERRSI.src.trading.utils.position_handler.core import get_redis_client
from HYPERRSI.src.trading.utils.trading_utils import init_user_position_data
from shared.logging import get_logger
from shared.utils import contracts_to_qty

logger = get_logger(__name__)
error_logger = setup_error_logger()


async def handle_trend_reversal_exit(
    user_id: str,
    settings: dict,
    trading_service: "TradingService",
    symbol: str,
    current_state: int,
    current_position: Position,
    side: str,
    use_dual_side_settings: str,
    trend_close_enabled: str
) -> None:
    """
    Handle position exit based on trend reversal conditions.

    This function checks if the trend has reversed strongly against the current position
    and closes the position if use_trend_close setting is enabled.

    Args:
        user_id: User identifier
        settings: User trading settings dictionary
        trading_service: Trading service instance
        symbol: Trading symbol (e.g., "BTC-USDT-SWAP")
        current_state: Current trend state (-2 to +2)
        current_position: Current position object
        side: Position side ("long" or "short")
        use_dual_side_settings: Whether dual-side trading is enabled
        trend_close_enabled: Whether trend-based closing is enabled

    Returns:
        None

    Side Effects:
        - Closes position via exchange API
        - Updates trading statistics
        - Clears Redis position data
        - Sends Telegram notifications

    Trend Reversal Conditions:
        - Long position: Closes when current_state == -2 (strong downtrend)
        - Short position: Closes when current_state == +2 (strong uptrend)
    """
    redis = await get_redis_client()

    # Check if trend-based closing is enabled
    should_close_with_trend = settings.get('use_trend_close', True)

    if not should_close_with_trend:
        return

    try:
        # Check if trend has reversed strongly against position
        should_exit = (
            (side == "long" and current_state == TREND_STATE_STRONG_DOWNTREND) or
            (side == "short" and current_state == TREND_STATE_STRONG_UPTREND)
        )

        if not should_exit:
            return

        try:
            # Determine dual side if applicable
            dual_side = None
            if side == "long":
                dual_side = "short"
            else:
                dual_side = "long"

            print("트렌드 역전")
            print("강제청산")

            # Close main position
            await _execute_position_close(
                user_id=user_id,
                symbol=symbol,
                side=side,
                trading_service=trading_service,
                reason="트렌드 역전으로 포지션 청산",
                size=current_position.size  # Signal Bot 모드 시 계약 수량 기반 청산
            )

            # Close dual-side position if enabled
            # Note: dual-side는 반대 방향 포지션 정보가 없으므로 size=None (100% 청산)
            if use_dual_side_settings == "true" and trend_close_enabled == "true":
                await _execute_position_close(
                    user_id=user_id,
                    symbol=symbol,
                    side=dual_side,
                    trading_service=trading_service,
                    reason="트렌드 역전으로 양방향 포지션 청산",
                    size=None  # 100% 청산 (percentage_position 방식)
                )

            # Update stats
            await _update_stats_on_close(
                user_id=user_id,
                symbol=symbol,
                side=side,
                current_position=current_position,
                redis_client=redis
            )

            # Cleanup Redis data
            await _cleanup_redis_on_close(
                user_id=user_id,
                symbol=symbol,
                side=side,
                redis_client=redis
            )

        except Exception as e:
            traceback.print_exc()
            error_logger.error(f"[{user_id}]: 트렌드 역전 처리 실패", exc_info=True)
            await send_telegram_message(
                f"⚠️ 트렌드 역전 처리 실패: {str(e)}",
                user_id,
                debug=True
            )

    except Exception as e:
        error_logger.error(f"[{user_id}]:포지션 처리 실패", exc_info=True)
        await send_telegram_message(
            f"⚠️ 포지션 처리 실패: {str(e)}",
            user_id,
            debug=True
        )


async def _execute_position_close(
    user_id: str,
    symbol: str,
    side: str,
    trading_service: "TradingService",
    reason: str,
    size: Optional[float] = None
) -> None:
    """
    Execute position close via trading service.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side to close
        trading_service: Trading service instance
        reason: Reason for closing (for logging/notification)
        size: Position size (contracts) to close. If None, closes 100%

    Raises:
        Exception: If position close fails
    """
    # ============================================================
    # Signal Bot 모드 분기
    # ============================================================
    if trading_service.execution_mode == "signal_bot" and trading_service.signal_token:
        size_info = f"{size} contracts" if size else "100%"
        logger.info(f"[{user_id}][SignalBot] Closing {side} position: {symbol} ({size_info})")

        # Signal Bot Executor 생성
        executor = await ExecutorFactory.create_signal_bot_executor(
            user_id=user_id,
            signal_token=trading_service.signal_token
        )

        try:
            # 심볼 변환: BTC-USDT-SWAP → BTC/USDT:USDT (CCXT 형식)
            ccxt_symbol = symbol.replace("-SWAP", "").replace("-", "/") + ":USDT"

            # Signal Bot을 통해 청산 주문 실행
            # size가 있으면 해당 수량만, 없으면 100% 청산
            await executor.close_position(
                symbol=ccxt_symbol,
                side=side,
                size=size,  # None이면 100% 청산
            )

            # 텔레그램 알림
            side_kr = "롱" if side == "long" else "숏"
            await send_telegram_message(
                f"✅ [Signal Bot] {side_kr} 포지션 청산 완료\n"
                f"\n"
                f"📊 심볼: {symbol}\n"
                f"📉 방향: {side_kr}\n"
                f"💰 수량: {size_info}\n"
                f"📝 사유: {reason}",
                user_id
            )

            logger.info(f"[{user_id}][SignalBot] Position closed: {symbol} {side} ({size_info}) - {reason}")

        finally:
            # Executor 정리
            await executor.close()

        return

    # ============================================================
    # API Direct 모드 (기존 로직)
    # ============================================================
    await trading_service.close_position(
        user_id=user_id,
        symbol=symbol,
        side=side,
        reason=reason
    )
    logger.info(f"[{user_id}] Position closed: {symbol} {side} - {reason}")


async def _update_stats_on_close(
    user_id: str,
    symbol: str,
    side: str,
    current_position: Position,
    redis_client: Any,
    close_type: str = 'trend_reversal'
) -> None:
    """
    Update trading statistics after position close.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side
        current_position: Position object with entry price and size
        redis_client: Redis client instance
        close_type: Close type (trend_reversal, take_profit, stop_loss, etc.)

    Side Effects:
        - Records trade statistics in database
        - Logs success or failure
    """
    try:
        # Get position info from Redis
        position_key = POSITION_KEY.format(user_id=user_id, symbol=symbol, side=side)
        position_info = await redis_client.hgetall(position_key)

        # Calculate PnL
        size = current_position.size
        entry_price = current_position.entry_price

        # Use mark_price from Position object, or fallback to entry_price
        current_price = current_position.mark_price if current_position.mark_price is not None else entry_price

        if side == "long":
            pnl = size * (current_price - float(entry_price))
        else:
            pnl = size * (float(entry_price) - current_price)

        # Convert contracts to quantity
        position_qty = await contracts_to_qty(symbol, int(size))
        if position_qty is None:
            position_qty = 0.0

        # Get DCA count from Redis
        dca_count_key = DCA_COUNT_KEY.format(user_id=user_id, symbol=symbol, side=side)
        dca_count_str = await redis_client.get(dca_count_key)
        dca_count = int(dca_count_str) if dca_count_str else 0

        # Get leverage from position info
        leverage = int(position_info.get("leverage", 1)) if position_info.get("leverage") else 1

        # Update trading stats with new parameters for PostgreSQL recording
        await update_trading_stats(
            user_id=user_id,
            symbol=symbol,
            entry_price=float(entry_price),
            exit_price=float(current_price),
            position_size=float(position_qty),
            pnl=float(pnl),
            side=side,
            entry_time=position_info.get("entry_time", str(datetime.now())),
            exit_time=str(datetime.now()),
            close_type=close_type,
            leverage=leverage,
            dca_count=dca_count,
            avg_entry_price=float(position_info.get("avg_entry_price", entry_price)) if position_info.get("avg_entry_price") else None,
        )

        logger.info(
            f"[{user_id}] Stats updated: {symbol} {side} - PnL: {pnl:+.2f} USDT"
        )

    except Exception as e:
        error_logger.error(f"[{user_id}]: 포지션 통계 업데이트 실패", exc_info=True)
        await send_telegram_message(
            f"⚠️ 포지션 통계 업데이트 실패: {str(e)}",
            user_id,
            debug=True
        )


async def cleanup_position_redis_keys(
    user_id: str,
    symbol: str,
    side: str,
    redis_client: Any,
    cleanup_both_sides: bool = False,
    cleanup_symbol_keys: bool = True
) -> int:
    """
    포지션 관련 모든 Redis 키를 삭제하는 통합 함수.

    이 함수는 포지션 청산 시 관련된 모든 Redis 키를 일관성 있게 삭제합니다.
    고아 키(orphaned keys) 문제를 방지하기 위해 모든 삭제 로직에서 이 함수를 사용해야 합니다.

    Args:
        user_id: 사용자 ID
        symbol: 거래 심볼 (e.g., "BTC-USDT-SWAP")
        side: 포지션 방향 ("long" 또는 "short")
        redis_client: Redis 클라이언트 인스턴스
        cleanup_both_sides: True면 long/short 둘 다 삭제, False면 지정된 side만 삭제
        cleanup_symbol_keys: True면 심볼 전체 키(position_state 등)도 삭제

    Returns:
        int: 삭제된 키 개수

    Side Effects:
        - POSITION_SIDE_KEYS에 정의된 side별 키 삭제
        - cleanup_symbol_keys=True면 POSITION_SYMBOL_KEYS에 정의된 심볼 키도 삭제

    Example:
        # 특정 side만 삭제
        deleted = await cleanup_position_redis_keys(user_id, symbol, "long", redis)

        # 양쪽 모두 삭제 (전체 청산)
        deleted = await cleanup_position_redis_keys(
            user_id, symbol, "long", redis,
            cleanup_both_sides=True, cleanup_symbol_keys=True
        )
    """
    keys_to_delete = []
    sides_to_cleanup = ["long", "short"] if cleanup_both_sides else [side]

    # 1. Side별 키 수집 (POSITION_SIDE_KEYS)
    for s in sides_to_cleanup:
        for key_pattern in POSITION_SIDE_KEYS:
            key = key_pattern.format(user_id=user_id, symbol=symbol, side=s)
            keys_to_delete.append(key)

    # 2. 심볼 전체 키 수집 (POSITION_SYMBOL_KEYS) - cleanup_symbol_keys가 True일 때만
    if cleanup_symbol_keys:
        for key_pattern in POSITION_SYMBOL_KEYS:
            key = key_pattern.format(user_id=user_id, symbol=symbol)
            keys_to_delete.append(key)

    # 3. 일괄 삭제 (pipeline 사용으로 성능 최적화)
    deleted_count = 0
    if keys_to_delete:
        try:
            # Redis pipeline으로 일괄 삭제
            deleted_count = await redis_client.delete(*keys_to_delete)
            logger.debug(
                f"[{user_id}] Position cleanup: {deleted_count}/{len(keys_to_delete)} keys deleted "
                f"for {symbol} (sides={sides_to_cleanup}, symbol_keys={cleanup_symbol_keys})"
            )
        except Exception as e:
            logger.error(f"[{user_id}] Position cleanup failed: {e}")
            raise

    return deleted_count


async def _cleanup_redis_on_close(
    user_id: str,
    symbol: str,
    side: str,
    redis_client: Any
) -> None:
    """
    Clean up Redis position data after position close.

    Args:
        user_id: User identifier
        symbol: Trading symbol
        side: Position side
        redis_client: Redis client instance

    Side Effects:
        - Deletes position-related Redis keys
        - Reinitializes position data
        - Logs success or failure
    """
    try:
        # 통합 삭제 함수 사용 - 특정 side만 삭제, 심볼 키는 유지 (반대쪽 포지션이 있을 수 있음)
        # init_user_position_data가 이제 POSITION_SIDE_KEYS와 POSITION_SYMBOL_KEYS를 사용하므로
        # cleanup_position_redis_keys 호출이 필요 없음 (중복 제거)
        deleted_count = await init_user_position_data(
            user_id=user_id,
            symbol=symbol,
            side=side,
            cleanup_symbol_keys=False  # 반대 포지션이 있을 수 있으므로 심볼 키 유지
        )

        logger.info(f"[{user_id}] Redis cleanup completed for {symbol} {side} ({deleted_count} keys)")

    except Exception as e:
        error_logger.error(f"[{user_id}]: REDIS 포지션 정리 실패", exc_info=True)
        await send_telegram_message(
            f"⚠️ REDIS 포지션 정리 실패: {str(e)}",
            user_id,
            debug=True
        )