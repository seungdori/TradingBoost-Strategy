# HYPERRSI/websocket/position_monitor_service.py

"""
포지션 모니터링 서비스 - core.py 기능을 WebSocket 기반으로 이식

이 서비스는 position_monitor.py의 WebSocket 클라이언트와 함께 동작하며,
주기적인 검증 및 정리 작업을 백그라운드 태스크로 실행합니다.

주요 기능:
1. 알고리즘 주문 검증 및 중복 정리 (SL/TP)
2. 주문 상태 모니터링 및 업데이트
3. 고아 알고리즘 주문 취소 (포지션 없는 방향)
4. 메모리 관리 및 Redis 연결 상태 확인
5. 누락된 주문 확인
"""

import asyncio
import gc
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import psutil

from shared.database.redis import ping_redis as check_redis_connection, reconnect_redis
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger, log_order

# 모니터링 모듈에서 필요한 함수들 import
from HYPERRSI.src.trading.monitoring.order_monitor import (
    check_missing_orders,
    check_order_status,
    check_recent_filled_orders,
    should_check_sl_order,
    should_check_tp_order,
    update_order_status,
)
from HYPERRSI.src.trading.monitoring.position_validator import (
    cancel_algo_orders_for_no_position_sides,
    check_and_cleanup_orders,
    check_position_exists,
)
from HYPERRSI.src.trading.monitoring.redis_manager import (
    get_all_running_users,
    get_user_monitor_orders,
    perform_memory_cleanup,
)
from HYPERRSI.src.trading.monitoring.telegram_service import get_identifier
from HYPERRSI.src.trading.monitoring.trailing_stop_handler import clear_trailing_stop
from HYPERRSI.src.trading.monitoring.utils import (
    get_actual_order_type,
    should_log,
)

logger = get_logger(__name__)


class PositionMonitorService:
    """
    WebSocket 기반 포지션 모니터링 서비스

    core.py의 기능을 WebSocket 환경에 맞게 재구성한 클래스입니다.
    백그라운드 태스크로 실행되어 주기적인 검증 및 정리 작업을 수행합니다.
    """

    # 간격 설정 (초)
    ALGO_ORDER_CHECK_INTERVAL = 300  # 알고리즘 주문 검증 간격 (5분)
    ALGO_ORDER_CANCEL_INTERVAL = 300  # 고아 알고 주문 취소 간격 (5분)
    POSITION_CHECK_INTERVAL = 60  # 포지션 확인 간격 (1분)
    ORDER_CHECK_INTERVAL = 15  # 주문 상태 확인 간격 (15초)
    MEMORY_CLEANUP_INTERVAL = 600  # 메모리 정리 간격 (10분)
    REDIS_CHECK_INTERVAL = 30  # Redis 연결 확인 간격 (30초)
    MEMORY_CHECK_INTERVAL = 60  # 메모리 체크 간격 (1분)
    MAX_MEMORY_MB = 512  # 최대 메모리 사용량 (MB)

    def __init__(self):
        self.running = False
        self._tasks: List[asyncio.Task] = []

        # 마지막 실행 시간 추적
        self._last_algo_check_time: float = 0
        self._last_algo_cancel_time: float = 0
        self._last_position_check_time: float = 0
        self._last_order_check_time: float = 0
        self._last_memory_cleanup_time: float = 0
        self._last_redis_check_time: float = 0
        self._last_memory_check_time: float = 0

        # 활성 사용자 캐시
        self._running_users: Set[str] = set()

        # 루프 카운터
        self._loop_count = 0

    async def start(self):
        """서비스 시작"""
        if self.running:
            logger.warning("PositionMonitorService가 이미 실행 중입니다.")
            return

        self.running = True
        logger.info("🚀 PositionMonitorService 시작")

        # 메인 모니터링 루프 시작
        task = asyncio.create_task(self._main_loop())
        self._tasks.append(task)

    async def stop(self):
        """서비스 중지"""
        self.running = False
        logger.info("🛑 PositionMonitorService 중지 요청")

        # 모든 태스크 취소
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # 태스크 완료 대기
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()
        logger.info("✅ PositionMonitorService 중지 완료")

    async def _main_loop(self):
        """메인 모니터링 루프"""
        logger.info("📊 PositionMonitorService 메인 루프 시작")

        while self.running:
            try:
                self._loop_count += 1
                current_time = time.time()

                # 1. Redis 연결 상태 확인 (30초마다)
                if current_time - self._last_redis_check_time >= self.REDIS_CHECK_INTERVAL:
                    self._last_redis_check_time = current_time
                    asyncio.create_task(self._check_redis_connection())

                # 2. 메모리 사용량 체크 (1분마다)
                if current_time - self._last_memory_check_time >= self.MEMORY_CHECK_INTERVAL:
                    self._last_memory_check_time = current_time
                    await self._check_memory_usage()

                # 3. 활성 사용자 목록 갱신
                await self._refresh_running_users()

                # 4. 고아 알고리즘 주문 취소 (5분마다)
                if current_time - self._last_algo_cancel_time >= self.ALGO_ORDER_CANCEL_INTERVAL:
                    self._last_algo_cancel_time = current_time
                    await self._cancel_orphan_algo_orders()

                # 5. 알고리즘 주문 검증 및 중복 정리 (5분마다)
                force_algo_check = current_time - self._last_algo_check_time >= self.ALGO_ORDER_CHECK_INTERVAL
                if force_algo_check:
                    self._last_algo_check_time = current_time

                # 6. 주문 상태 확인 (15초마다)
                force_order_check = current_time - self._last_order_check_time >= self.ORDER_CHECK_INTERVAL
                if force_order_check:
                    self._last_order_check_time = current_time

                # 7. 포지션 확인 (1분마다)
                force_position_check = current_time - self._last_position_check_time >= self.POSITION_CHECK_INTERVAL
                if force_position_check:
                    self._last_position_check_time = current_time

                # 8. 사용자별 주문 모니터링
                await self._monitor_user_orders(
                    force_algo_check=force_algo_check,
                    force_order_check=force_order_check,
                    force_position_check=force_position_check
                )

                # 9. 메모리 정리 (10분마다)
                if current_time - self._last_memory_cleanup_time >= self.MEMORY_CLEANUP_INTERVAL:
                    self._last_memory_cleanup_time = current_time
                    asyncio.create_task(perform_memory_cleanup())

                # 대기 (2초)
                await asyncio.sleep(2)

            except asyncio.CancelledError:
                logger.info("메인 루프가 취소되었습니다.")
                break
            except Exception as e:
                logger.error(f"메인 루프 오류: {str(e)}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)

    async def _check_redis_connection(self):
        """Redis 연결 상태 확인"""
        try:
            if not await check_redis_connection():
                logger.warning("Redis 연결 상태 불량, 재연결 시도")
                await reconnect_redis()
            else:
                logger.debug("Redis 연결 상태 양호")
        except Exception as e:
            logger.error(f"Redis 연결 확인 중 오류: {str(e)}")

    async def _check_memory_usage(self):
        """메모리 사용량 체크 및 정리"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_usage_mb = memory_info.rss / 1024 / 1024
            logger.info(f"현재 메모리 사용량: {memory_usage_mb:.2f} MB")

            if memory_usage_mb > self.MAX_MEMORY_MB:
                logger.warning(f"메모리 사용량({memory_usage_mb:.2f} MB)이 제한({self.MAX_MEMORY_MB} MB)을 초과하여 강제 정리 수행")
                gc.collect()
                await reconnect_redis()

                memory_info = process.memory_info()
                logger.info(f"메모리 정리 후 사용량: {memory_info.rss / 1024 / 1024:.2f} MB")
        except Exception as e:
            logger.error(f"메모리 체크 중 오류: {str(e)}")

    async def _refresh_running_users(self):
        """활성 사용자 목록 갱신"""
        try:
            running_users = await get_all_running_users()
            self._running_users = {str(uid) for uid in running_users}
        except Exception as e:
            logger.error(f"활성 사용자 조회 실패: {str(e)}")

    async def _cancel_orphan_algo_orders(self):
        """포지션이 없는 방향의 알고리즘 주문 취소"""
        logger.info("🗑️ 고아 알고리즘 주문 취소 확인 시작")

        for user_id in self._running_users:
            try:
                asyncio.create_task(cancel_algo_orders_for_no_position_sides(user_id))
            except Exception as e:
                logger.error(f"사용자 {user_id} 알고 주문 취소 중 오류: {str(e)}")

    async def _monitor_user_orders(
        self,
        force_algo_check: bool,
        force_order_check: bool,
        force_position_check: bool
    ):
        """사용자별 주문 모니터링"""
        redis = await get_redis_client()

        for user_id in self._running_users:
            try:
                # 사용자의 모니터링 주문 가져오기
                user_orders = await get_user_monitor_orders(user_id)
                if not user_orders:
                    continue

                # 심볼별 주문 그룹화
                symbol_orders: Dict[str, List[Dict[str, Any]]] = {}
                for order_id, order_data in user_orders.items():
                    symbol = order_data.get("symbol")
                    if symbol is None:
                        continue
                    if symbol not in symbol_orders:
                        symbol_orders[symbol] = []
                    symbol_orders[symbol].append(order_data)

                # 각 심볼에 대해 처리
                for symbol, orders in symbol_orders.items():
                    await self._process_symbol_orders(
                        user_id=user_id,
                        symbol=symbol,
                        orders=orders,
                        force_algo_check=force_algo_check,
                        force_order_check=force_order_check,
                        force_position_check=force_position_check,
                        redis=redis
                    )

            except Exception as e:
                logger.error(f"사용자 {user_id} 처리 중 오류: {str(e)}")

    async def _process_symbol_orders(
        self,
        user_id: str,
        symbol: str,
        orders: List[Dict],
        force_algo_check: bool,
        force_order_check: bool,
        force_position_check: bool,
        redis
    ):
        """심볼별 주문 처리"""
        try:
            current_time = time.time()

            # 주문 수 변화 감지
            current_order_count = len(orders)
            order_count_key = f"order_count:{user_id}:{symbol}"
            previous_count = await redis.get(order_count_key)

            force_check_all_orders = False
            if previous_count:
                previous_count = int(previous_count)
                if previous_count > current_order_count:
                    logger.warning(f"주문 수 감소 감지: {user_id} {symbol} {previous_count} -> {current_order_count}")
                    force_check_all_orders = True

                    # 사라진 주문 체크
                    asyncio.create_task(check_missing_orders(user_id, symbol, orders))
                    asyncio.create_task(check_recent_filled_orders(user_id, symbol))

            # 현재 주문 수 저장
            await redis.set(order_count_key, current_order_count, ex=600)

            # 알고리즘 주문 검증 (5분마다)
            if force_algo_check:
                await self._verify_algo_orders(user_id, symbol, redis)

            # 포지션 정리 작업 (5분마다)
            if force_position_check:
                position_sides = set(order_data.get("position_side", "") for order_data in orders)
                for direction in position_sides:
                    if direction not in ["long", "short"]:
                        continue
                    position_exists, _ = await check_position_exists(user_id, symbol, direction)
                    if not position_exists:
                        # 포지션이 없으면 알고리즘 주문 먼저 취소 후 정리
                        await self._cancel_algo_orders_for_direction(user_id, symbol, direction)
                        await check_and_cleanup_orders(user_id, symbol, direction)

            # 주문 상태 확인
            if force_order_check or force_check_all_orders:
                await self._check_orders_status(
                    user_id=user_id,
                    symbol=symbol,
                    orders=orders,
                    force_check_all=force_check_all_orders,
                    redis=redis
                )

        except Exception as e:
            logger.error(f"심볼 {symbol} 처리 중 오류: {str(e)}")

    async def _cancel_algo_orders_for_direction(self, user_id: str, symbol: str, direction: str):
        """
        포지션이 없는 특정 방향의 알고리즘 주문(트리거 주문) 취소

        Args:
            user_id: 사용자 ID
            symbol: 심볼 (예: SOL-USDT-SWAP)
            direction: 포지션 방향 ('long' 또는 'short')
        """
        logger.info(f"[정리-WS] 🔄 알고리즘 주문 취소 시작: {user_id} {symbol} {direction}")
        try:
            from HYPERRSI.src.api.dependencies import get_user_api_keys
            from HYPERRSI.src.trading.cancel_trigger_okx import TriggerCancelClient

            # symbol이 이미 OKX 형식(예: SOL-USDT-SWAP)인지 확인
            trading_symbol = symbol
            if "-" not in symbol:
                # 필요시 변환 (보통 이미 올바른 형식임)
                trading_symbol = f"{symbol[:3]}-USDT-SWAP" if len(symbol) >= 3 else symbol

            logger.info(f"[정리-WS] 알고리즘 주문 취소 대상: {user_id} {trading_symbol} {direction}")

            api_keys = await get_user_api_keys(str(user_id))
            if not api_keys or not api_keys.get('api_key'):
                logger.error(f"[정리-WS] API 키를 찾을 수 없음: {user_id}")
                return

            cancel_client = TriggerCancelClient(
                api_key=api_keys.get('api_key'),
                secret_key=api_keys.get('api_secret'),
                passphrase=api_keys.get('passphrase')
            )

            # 해당 방향의 알고리즘 주문 취소
            result = await cancel_client.cancel_all_trigger_orders(
                inst_id=trading_symbol,
                side=direction,
                algo_type="trigger",
                user_id=str(user_id)
            )

            if result and result.get('code') == '0':
                if 'No active orders to cancel' in result.get('msg', ''):
                    logger.info(f"[정리-WS] ✅ 취소할 알고리즘 주문 없음: {user_id} {trading_symbol} {direction}")
                else:
                    logger.info(f"[정리-WS] ✅ 알고리즘 주문 취소 성공: {user_id} {trading_symbol} {direction} - 취소된 주문: {len(result.get('data', []))}개")
            else:
                logger.warning(f"[정리-WS] ⚠️ 알고리즘 주문 취소 실패: {user_id} {trading_symbol} {direction} - {result}")
        except Exception as cancel_error:
            logger.error(f"[정리-WS] ❌ 알고리즘 주문 취소 중 오류: {str(cancel_error)}")
            logger.error(traceback.format_exc())

    async def _verify_algo_orders(self, user_id: str, symbol: str, redis):
        """알고리즘 주문 검증 및 중복 정리"""
        try:
            from HYPERRSI.src.api.dependencies import get_exchange_context

            algo_check_key = f"algo_check:{user_id}:{symbol}"

            async with get_exchange_context(user_id) as exchange:
                params = {"instId": symbol, "ordType": "trigger"}
                pending_resp = await exchange.privateGetTradeOrdersAlgoPending(params=params)

                if pending_resp.get("code") != "0":
                    return

                algo_orders = pending_resp.get("data", [])
                if not algo_orders:
                    return

                sl_orders_by_pos_side: Dict[str, List] = {}
                tp_orders_by_pos_side: Dict[str, List] = {}

                # SL/TP 주문 분류
                for algo_order in algo_orders:
                    pos_side = algo_order.get("posSide", "unknown")
                    sl_trigger_px = algo_order.get("slTriggerPx", "")
                    tp_trigger_px = algo_order.get("tpTriggerPx", "")
                    reduce_only = algo_order.get("reduceOnly", "false")
                    algo_id = algo_order.get("algoId", "")
                    u_time = int(algo_order.get("uTime", "0"))

                    if sl_trigger_px:
                        if pos_side not in sl_orders_by_pos_side:
                            sl_orders_by_pos_side[pos_side] = []
                        sl_orders_by_pos_side[pos_side].append({
                            "algoId": algo_id,
                            "slTriggerPx": sl_trigger_px,
                            "reduceOnly": reduce_only,
                            "uTime": u_time
                        })

                        if reduce_only.lower() != "true":
                            logger.warning(f"[알고검증] SL 주문 reduceOnly 아님: {algo_id}, posSide: {pos_side}")

                    elif tp_trigger_px:
                        if pos_side not in tp_orders_by_pos_side:
                            tp_orders_by_pos_side[pos_side] = []
                        tp_orders_by_pos_side[pos_side].append({
                            "algoId": algo_id,
                            "tpTriggerPx": tp_trigger_px,
                            "reduceOnly": reduce_only,
                            "uTime": u_time
                        })

                # SL 중복 검증 및 정리 (최신 1개만 유지)
                for pos_side, sl_orders in sl_orders_by_pos_side.items():
                    if len(sl_orders) >= 2:
                        logger.warning(f"[알고검증] 🚨 {pos_side} SL 중복: {len(sl_orders)}개 (symbol: {symbol})")

                        sl_orders_sorted = sorted(sl_orders, key=lambda x: x["uTime"], reverse=True)

                        for sl_order in sl_orders_sorted[1:]:
                            logger.warning(f"[알고검증] ❌ 오래된 SL 취소: {sl_order['algoId']}")
                            try:
                                cancel_resp = await exchange.privatePostTradeCancelAlgos(params=[{
                                    "algoId": sl_order["algoId"],
                                    "instId": symbol
                                }])
                                if cancel_resp.get("code") == "0":
                                    logger.info(f"[알고검증] ✅ SL 취소 성공: {sl_order['algoId']}")
                                else:
                                    logger.error(f"[알고검증] ⚠️ SL 취소 실패: {cancel_resp.get('msg')}")
                            except Exception as e:
                                logger.error(f"[알고검증] ⚠️ SL 취소 오류: {str(e)}")

                        logger.info(f"[알고검증] ✅ 최신 SL 유지: {sl_orders_sorted[0]['algoId']}")

                # TP 개수 검증 및 정리 (최대 3개)
                for pos_side, tp_orders in tp_orders_by_pos_side.items():
                    if len(tp_orders) > 3:
                        logger.warning(f"[알고검증] 🚨 {pos_side} TP 초과: {len(tp_orders)}개 (최대 3개)")

                        tp_orders_sorted = sorted(tp_orders, key=lambda x: x["uTime"], reverse=True)

                        for tp_order in tp_orders_sorted[3:]:
                            logger.warning(f"[알고검증] ❌ 오래된 TP 취소: {tp_order['algoId']}")
                            try:
                                cancel_resp = await exchange.privatePostTradeCancelAlgos(params=[{
                                    "algoId": tp_order["algoId"],
                                    "instId": symbol
                                }])
                                if cancel_resp.get("code") == "0":
                                    logger.info(f"[알고검증] ✅ TP 취소 성공: {tp_order['algoId']}")
                                else:
                                    logger.error(f"[알고검증] ⚠️ TP 취소 실패: {cancel_resp.get('msg')}")
                            except Exception as e:
                                logger.error(f"[알고검증] ⚠️ TP 취소 오류: {str(e)}")

                        logger.info(f"[알고검증] ✅ 최신 TP 3개 유지: {[tp['algoId'] for tp in tp_orders_sorted[:3]]}")

                logger.info(f"[알고검증] 심볼 {symbol} 알고 주문: SL {sum(len(v) for v in sl_orders_by_pos_side.values())}개, TP {sum(len(v) for v in tp_orders_by_pos_side.values())}개")

            # 마지막 체크 시간 저장
            await redis.set(algo_check_key, time.time(), ex=600)

        except Exception as e:
            logger.error(f"[알고검증] 오류: {str(e)}")

    async def _check_orders_status(
        self,
        user_id: str,
        symbol: str,
        orders: List[Dict],
        force_check_all: bool,
        redis
    ):
        """주문 상태 확인 및 업데이트"""
        try:
            from HYPERRSI.src.api.dependencies import get_exchange_context
            from HYPERRSI.src.trading.services.get_current_price import get_current_price

            async with get_exchange_context(user_id) as exchange:
                # 현재가 조회
                current_price = await get_current_price(symbol, "1m", exchange)
                if current_price <= 0:
                    logger.warning(f"유효하지 않은 현재가: {current_price}, 심볼: {symbol}")
                    return

                # 트레일링 스탑 활성화된 방향 확인
                trailing_sides = set()
                for direction in ["long", "short"]:
                    ts_key = f"trailing:user:{user_id}:{symbol}:{direction}"
                    if await redis.exists(ts_key):
                        trailing_sides.add(direction)

                # 주문 정렬 (TP 주문은 tp1 → tp2 → tp3 순서로)
                def sort_key(order_data):
                    order_type = order_data.get("order_type", "")
                    if order_type.startswith("tp"):
                        tp_num = order_type[2:] if len(order_type) > 2 else "1"
                        return (0, int(tp_num) if tp_num.isdigit() else 999)
                    elif order_type == "sl":
                        return (1, 0)
                    else:
                        return (2, 0)

                sorted_orders = sorted(orders, key=sort_key)

                # 각 주문 확인
                for order_data in sorted_orders:
                    await self._check_single_order(
                        user_id=user_id,
                        symbol=symbol,
                        order_data=order_data,
                        current_price=current_price,
                        trailing_sides=trailing_sides,
                        force_check_all=force_check_all,
                        redis=redis,
                        exchange=exchange
                    )

        except Exception as e:
            logger.error(f"주문 상태 확인 중 오류: {str(e)}")

    async def _check_single_order(
        self,
        user_id: str,
        symbol: str,
        order_data: Dict,
        current_price: float,
        trailing_sides: Set[str],
        force_check_all: bool,
        redis,
        exchange
    ):
        """단일 주문 상태 확인"""
        try:
            order_id = str(order_data.get("order_id", ""))
            order_type = str(order_data.get("order_type", ""))
            position_side = str(order_data.get("position_side", ""))
            current_status = str(order_data.get("status", ""))
            current_time = time.time()

            # 이미 완료 처리된 주문은 스킵
            if current_status in ["filled", "canceled", "failed"]:
                return

            # 트레일링 스탑 활성화된 방향의 TP 주문은 스킵
            if position_side in trailing_sides and order_type.startswith("tp"):
                logger.debug(f"트레일링 스탑 활성화됨 ({position_side}), TP 주문 ({order_id}) 스킵")
                return

            check_needed = False

            # 7일 이상 된 주문은 체크해서 정리
            last_updated = int(order_data.get("last_updated_time", str(int(current_time))))
            if current_time - last_updated > (7 * 24 * 60 * 60):
                check_needed = True
                logger.info(f"오래된 주문 정리 체크: {order_id}")
            elif force_check_all:
                check_needed = True
            elif order_type.startswith("tp"):
                check_needed = await should_check_tp_order(order_data, current_price)
            elif order_type == "sl":
                check_needed = await should_check_sl_order(order_data, current_price)
            elif current_status == "open" and self._loop_count % 5 == 0:
                check_needed = True

            if not check_needed:
                return

            # 주문 상태 확인
            await asyncio.sleep(0.1)  # 서버 부하 방지

            try:
                order_status = await check_order_status(
                    user_id=user_id,
                    symbol=symbol,
                    order_id=order_id,
                    order_type=order_type
                )

                if order_status is None:
                    logger.warning(f"주문 상태 API가 None을 반환: {order_id}")
                    return

            except Exception as check_error:
                logger.error(f"주문 상태 확인 중 오류: {order_id}, {str(check_error)}")
                return

            # 상태 처리
            await self._process_order_status(
                user_id=user_id,
                symbol=symbol,
                order_id=order_id,
                order_type=order_type,
                position_side=position_side,
                order_data=order_data,
                order_status=order_status,
                current_price=current_price,
                redis=redis
            )

        except Exception as e:
            logger.error(f"단일 주문 체크 중 오류: {str(e)}")

    async def _process_order_status(
        self,
        user_id: str,
        symbol: str,
        order_id: str,
        order_type: str,
        position_side: str,
        order_data: Dict,
        order_status: Dict,
        current_price: float,
        redis
    ):
        """주문 상태 처리"""
        try:
            if not isinstance(order_status, dict):
                logger.warning(f"예상하지 못한 주문 상태 형식: {order_id} -> {order_status}")
                return

            status = "unknown"
            filled_sz = "0"

            # OrderResponse 형식
            if 'status' in order_status:
                status_value = str(order_status['status'].value) if hasattr(order_status['status'], 'value') else str(order_status['status'])

                if status_value.lower() in ['filled', 'closed']:
                    status = 'filled'
                    filled_sz = order_status.get('filled_amount', order_status.get('amount', '0'))
                elif status_value.lower() in ['canceled']:
                    status = 'canceled'
                    filled_sz = order_status.get('filled_amount', '0')
                else:
                    status = 'open'
                    filled_sz = order_status.get('filled_amount', '0')

            # OKX API 응답
            elif 'state' in order_status:
                state = order_status.get('state', '')
                filled_sz = order_status.get('filled_amount', order_status.get('accFillSz', '0'))

                status_mapping = {
                    'filled': 'filled',
                    'effective': 'open',
                    'canceled': 'canceled',
                    'order_failed': 'failed'
                }
                status = status_mapping.get(state, 'unknown')
            else:
                return

            # TP 주문 체결 시 브레이크이븐/트레일링스탑 처리
            if status == 'filled' and (order_type.startswith('tp') or order_type.startswith('take_profit')):
                await self._handle_tp_filled(
                    user_id=user_id,
                    symbol=symbol,
                    order_id=order_id,
                    order_type=order_type,
                    position_side=position_side,
                    order_data=order_data,
                    filled_sz=filled_sz,
                    current_price=current_price,
                    redis=redis
                )

            # 주문 상태 업데이트
            await update_order_status(
                user_id=user_id,
                symbol=symbol,
                order_id=order_id,
                status=status,
                filled_amount=str(filled_sz),
                order_type=order_type
            )

            # SL 주문 체결 시 트레일링 스탑 정리
            if status == 'filled' and order_type == 'sl':
                asyncio.create_task(clear_trailing_stop(user_id, symbol, position_side))

                # SL 체결 로깅
                try:
                    price = float(order_status.get('avgPx', order_status.get('px', 0)))
                    filled_amount = float(filled_sz) if filled_sz else 0
                    log_order(
                        user_id=user_id,
                        symbol=symbol,
                        action_type='sl_execution',
                        position_side=position_side,
                        price=price,
                        quantity=filled_amount,
                        order_id=order_id,
                        current_price=current_price,
                        api_type='okx_algo'
                    )
                except Exception as e:
                    logger.error(f"SL 주문 체결 로깅 실패: {str(e)}")

        except Exception as e:
            logger.error(f"주문 상태 처리 중 오류: {str(e)}")

    async def _handle_tp_filled(
        self,
        user_id: str,
        symbol: str,
        order_id: str,
        order_type: str,
        position_side: str,
        order_data: Dict,
        filled_sz: str,
        current_price: float,
        redis
    ):
        """TP 주문 체결 처리"""
        try:
            tp_index = 0
            if order_type.startswith("tp") and len(order_type) > 2:
                tp_num = order_type[2:]
                if tp_num.isdigit():
                    tp_index = int(tp_num)

            position_key = f"user:{user_id}:position:{symbol}:{position_side}"

            # TP 중복 처리 방지
            tp_already_processed = await redis.hget(position_key, f"get_tp{tp_index}")
            if tp_already_processed == "true":
                logger.info(f"TP{tp_index} 이미 처리됨: {user_id} {symbol} {position_side}")
                order_key = f"monitor:user:{user_id}:{symbol}:order:{order_id}"
                await redis.delete(order_key)
                return

            # TP 처리 완료 표시
            await redis.hset(position_key, f"get_tp{tp_index}", "true")

            # TP 체결 로깅
            price = float(order_data.get("price", "0"))
            filled_amount = float(filled_sz) if filled_sz else 0

            try:
                log_order(
                    user_id=user_id,
                    symbol=symbol,
                    action_type='tp_execution',
                    position_side=position_side,
                    price=price,
                    quantity=filled_amount,
                    tp_index=tp_index,
                    order_id=order_id,
                    current_price=current_price
                )
            except Exception as e:
                logger.error(f"TP 주문 체결 로깅 실패: {str(e)}")

            # 브레이크이븐/트레일링스탑 처리
            from HYPERRSI.src.trading.monitoring.break_even_handler import process_break_even_settings
            asyncio.create_task(process_break_even_settings(
                user_id=user_id,
                symbol=symbol,
                order_type=order_type,
                position_data=order_data
            ))

        except Exception as e:
            logger.error(f"TP 체결 처리 중 오류: {str(e)}")


# 싱글톤 인스턴스
_service_instance: Optional[PositionMonitorService] = None


def get_position_monitor_service() -> PositionMonitorService:
    """PositionMonitorService 싱글톤 인스턴스 반환"""
    global _service_instance
    if _service_instance is None:
        _service_instance = PositionMonitorService()
    return _service_instance


async def start_position_monitor_service():
    """서비스 시작 헬퍼 함수"""
    service = get_position_monitor_service()
    await service.start()


async def stop_position_monitor_service():
    """서비스 중지 헬퍼 함수"""
    global _service_instance
    if _service_instance is not None:
        await _service_instance.stop()
        _service_instance = None
