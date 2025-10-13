# HYPERRSI/src/trading/modules/order_manager.py
"""
Order Manager

주문 생성, 취소, 모니터링 등 주문 관리 기능
"""

import json
import traceback
from datetime import datetime
from typing import Optional

import ccxt.async_support as ccxt

from HYPERRSI.src.trading.cancel_trigger_okx import TriggerCancelClient
from HYPERRSI.src.trading.models import OrderStatus
from HYPERRSI.src.trading.services.order_utils import get_order_info as get_order_info_from_module
from HYPERRSI.src.trading.services.order_utils import try_send_order
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger
from shared.utils import safe_float

logger = get_logger(__name__)

# Dynamic redis_client access


class OrderManager:
    """주문 관리 서비스"""

    def __init__(self, trading_service):
        """
        Args:
            trading_service: TradingService 인스턴스
        """
        self.trading_service = trading_service

    async def cleanup(self):
        """인스턴스 정리 및 클라이언트 반환"""
        if hasattr(self.trading_service, 'client') and self.trading_service.client:
            # 클라이언트가 존재하면 닫기
            try:
                # ccxt 클라이언트의 경우 close 메소드 호출
                if hasattr(self.trading_service.client, 'close'):
                    await self.trading_service.client.close()
                # 그렇지 않은 경우 - 이미 컨텍스트 매니저로 관리되었으므로 추가 작업 필요 없음
                self.trading_service.client = None
                logger.info(f"Client cleanup completed for user {self.trading_service.user_id}")
            except Exception as e:
                logger.error(f"Error during client cleanup: {e}")

    async def _cancel_order(
        self,
        user_id: str,
        symbol: str,
        order_id: str = None,
        side: str = None,
        order_type: str = None  # 'limit' | 'market' | 'stop_loss' | 'take_profit' 등
    ) -> None:
        """
        OKX에서 지정된 order_id의 주문을 취소합니다.
        order_type 등을 통해 일반 주문 / Algo 주문 취소를 분기 처리합니다.
        """
        try:
            print("호출 1")
            print(f"[취소주문 {user_id}] : side : {side}, order_id : {order_id}, order_type : {order_type}")

            exchange = None
            api_keys = await self.trading_service.okx_fetcher.get_user_api_keys(user_id)
            # ✅ OKX 클라이언트 생성
            exchange = ccxt.okx({
                'apiKey': api_keys.get('api_key'),
                'secret': api_keys.get('api_secret'),
                'password': api_keys.get('passphrase'),
                'enableRateLimit': True,
                'options': {'defaultType': 'swap'}
            })

            # 2) Algo 주문인지 여부를 order_type이나 order_id 저장방식으로 판단
            #    예: order_type이 'stop_loss'나 'take_profit'이면 algo 취소로 분기
            is_algo_order = order_type in ('stop_loss', 'trigger', 'conditional', 'stopLoss')

            if is_algo_order:
                # ---- Algo 주문 취소 ----
                # (1) cancelOrder() 시도
                try:
                    api_keys = await self.trading_service.okx_fetcher.get_user_api_keys(user_id)
                    trigger_cancel_client = TriggerCancelClient(
                        api_key=api_keys.get('api_key'),
                        secret_key=api_keys.get('api_secret'),
                        passphrase=api_keys.get('passphrase')
                    )
                    # OKX에서는 cancelOrder() 파라미터가 독특하여 algoId로 전달
                    await trigger_cancel_client.cancel_all_trigger_orders(inst_id=symbol, side=side, algo_type="trigger", user_id=user_id)
                    logger.info(f"Canceled algo order {order_id} for {symbol}")
                except Exception as e:
                    # (2) cancelOrder()가 안 된다면 private_post_trade_cancel_algos() 직접 호출
                    logger.warning(f"[{user_id}] cancelOrder() failed for algo; trying private_post_trade_cancel_algos. Err={str(e)}")
                    try:
                        await exchange.private_post_trade_cancel_algos({
                            "algoId": [order_id],  # 배열로 multiple IDs 가능
                            "instId": symbol
                        })
                        logger.info(f"Canceled algo order via private_post_trade_cancel_algos: {order_id}")
                    except Exception as e2:
                        logger.error(f"Failed to cancel algo order {order_id} via both ways. {str(e2)}")
                        raise

            else:
                # ---- 일반 주문 취소 ----
                await exchange.cancelOrder(order_id, symbol)
                logger.info(f"Canceled normal order {order_id} for {symbol}")

        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {str(e)}")
            raise
        finally:
            if exchange is not None:
                await exchange.close()

    async def cancel_all_open_orders(self, exchange, symbol, user_id, side: str = None):
        """모든 미체결 주문 취소"""
        redis = await get_redis_client()
        try:
            # 먼저 미체결 주문들을 가져옵니다
            print(f"취소할 주문 조회: {symbol}, side: {side}")
            open_orders = await exchange.fetch_open_orders(symbol)
            # side로 필터링
            if side:
                open_orders = [order for order in open_orders if order['side'].lower() == side.lower()]

            len_open_orders = len(open_orders)
            print(f"미체결 주문 수: {len_open_orders}")
            try:
                api_keys = await self.trading_service.okx_fetcher.get_user_api_keys(user_id)
                trigger_cancel_client = TriggerCancelClient(
                    api_key=api_keys.get('api_key'),
                    secret_key=api_keys.get('api_secret'),
                    passphrase=api_keys.get('passphrase')
                )
                await trigger_cancel_client.cancel_all_trigger_orders(inst_id=symbol, side=side, algo_type="trigger", user_id=user_id)
            except Exception as e:
                logger.error(f"Failed to cancel trigger orders: {str(e)}")

            # 취소 요청 리스트를 만듭니다
            if len(open_orders) > 0:
                cancellation_requests = [
                    {
                        "id": order['id'],
                        "symbol": order['symbol'],
                        "clientOrderId": order.get('clientOrderId')  # clientOrderId가 있는 경우 포함
                    }
                    for order in open_orders
                ]

                if len(cancellation_requests) > 0:
                    # 한번에 모든 주문을 취소합니다
                    # 일반 주문 취소
                    response = await exchange.cancel_orders_for_symbols(cancellation_requests)

                # 취소된 주문들을 Redis에 저장
                closed_orders_key = f"user:{user_id}:closed_orders"

                # 리스트로 저장
                for order in open_orders:
                    await redis.rpush(closed_orders_key, json.dumps(order))

                # 열린 주문 목록 삭제
                await redis.delete(f"user:{user_id}:open_orders")

                return True
            else:
                print("미체결 주문이 없습니다.")
                return True
        except Exception as e:
            logger.error(f"Failed to cancel all open orders: {str(e)}")
            return False

    async def _try_send_order(
        self,
        user_id: str,
        symbol: str,
        side: str,
        size: float,
        leverage: float = None,
        order_type: str = 'market',
        price: float = None,
        trigger_price: float = None,
        direction: Optional[str] = None
    ) -> OrderStatus:
        """주문 전송"""
        debug_order_params = {
            'symbol': symbol,
            'side': side,
            'size': size,
            'leverage': leverage,
            'order_type': order_type,
            'price': price,
            'trigger_price': trigger_price,
            'direction': direction
        }
        try:
            exchange = self.trading_service.client
            order_status = await try_send_order(user_id=user_id, symbol=symbol, side=side, size=size, leverage=leverage, order_type=order_type, price=price, trigger_price=trigger_price, direction=direction, exchange=exchange)
            return order_status
        except Exception as e:
            logger.error(f"Failed to send order: {str(e)}")
            raise

    async def _store_order_in_redis(self, user_id: str, order_state: OrderStatus):
        """
        open_orders 리스트/해시 등으로 관리 (여기서는 리스트 예시)
        - key: user:{user_id}:open_orders
        - value: JSON (OrderStatus)
        """

        redis = await get_redis_client()
        redis_key = f"user:{user_id}:open_orders"
        existing = await redis.get(f"open_orders:{user_id}:{order_state.order_id}")
        if existing:
            return
        order_data = {
            "order_id": order_state.order_id,
            "symbol": order_state.symbol,
            "side": order_state.side,
            "size": order_state.size,
            "filled_size": order_state.filled_size,
            "status": order_state.status,
            "avg_fill_price": order_state.avg_fill_price,
            "create_time": order_state.create_time.isoformat(),
            "update_time": order_state.update_time.isoformat(),
            "order_type": order_state.order_type,
            "posSide": order_state.posSide
        }
        # 간단히 lpush
        await redis.lpush(redis_key, json.dumps(order_data))

    async def monitor_orders(self, user_id: str):
        """
        - 폴링 기반으로 'open_orders' 목록을 조회
        - 각 주문의 최신 상태(체결량, 가격, 상태)를 API로 확인
        - Redis 업데이트: open 주문과 closed 주문을 별도의 키로 관리
        """

        redis = await get_redis_client()
        open_key = f"user:{user_id}:open_orders"
        closed_key = f"user:{user_id}:closed_orders"  # 종료된 주문을 저장할 새로운 Redis 키

        open_orders = await redis.lrange(open_key, 0, -1)

        new_open_list = []   # 계속 open 상태인 주문들
        closed_list = []     # 종료(closed)된 주문들

        for data in open_orders:
            try:
                order_json = json.loads(data)
                order_id = order_json['order_id']
                symbol = order_json['symbol']
                order_type = order_json.get('order_type', '')
                is_algo = order_type in ['stop_loss']
                try:
                    if is_algo:
                        # 알고리즘 주문 조회
                        try:
                            latest = await self.trading_service.client.fetch_order(order_id, symbol, params={'stop': True, 'ordType': 'trigger'})
                            # 응답 구조가 다르므로 데이터 매핑
                            if latest.get('data') and len(latest['data']) > 0:
                                algo_order = latest['data'][0]
                                latest = {
                                    'status': algo_order.get('state', 'open'),
                                    'filled_size': float(algo_order.get('sz', 0)),
                                    'avg_fill_price': float(algo_order.get('avgPx', 0))
                                }
                                if latest.get('status') in ["closed", "canceled", "error", "rejected"]:
                                    closed_list.append(json.dumps(order_json))

                        except Exception as e:
                            logger.error(f"알고주문 조회 실패: {str(e)}")
                            new_open_list.append(data)  # 조회 실패 시 기존 데이터 유지
                            continue  # 다음 주문으로 넘어감
                    else:
                        try:
                            # 일반 주문 조회
                            latest = await self.trading_service.client.fetch_order(order_id, symbol)
                        except Exception as e:
                            logger.error(f"일반 주문 조회 실패: {str(e)}")
                            new_open_list.append(data)  # 조회 실패 시 기존 데이터 유지
                            continue  # 다음 주문으로 넘어감
                except Exception as e:
                    logger.error(f"주문 조회 실패: {str(e)}")
                    new_open_list.append(data)  # 조회 실패 시 기존 데이터 유지
                    continue  # 다음 주문으로 넘어감

                # 최신 주문 정보 예시: {'status': 'partially_filled', 'filled_size': '0.02', 'avg_fill_price': '19000.0', ...}
                filled_size = float(latest.get('filled_size', 0.0))
                avg_fill_price = float(latest.get('avg_fill_price', 0.0))
                status = latest.get('status', 'open')

                order_json['filled_size'] = filled_size
                order_json['avg_fill_price'] = avg_fill_price
                order_json['status'] = status
                order_json['update_time'] = datetime.now().isoformat()

                if status in ("filled", "canceled", "error", "closed", "rejected"):
                    # 종료된 주문은 open_orders 목록에서 제거하고 closed_orders로 옮김
                    logger.info(f"[monitor_orders] Order {order_id} -> {status}. Moving to closed_orders.")
                    closed_list.append(json.dumps(order_json))
                else:
                    # 여전히 open 또는 partially_filled 인 경우, open 주문 목록에 유지
                    new_open_list.append(json.dumps(order_json))
            except Exception as ex:
                logger.error(f"[monitor_orders] 주문 상태 업데이트 오류: {str(ex)}")
                traceback.print_exc()
                # 문제 발생 시 원본 데이터를 유지
                new_open_list.append(data)

        # open_orders 키 업데이트: 기존 데이터를 삭제하고 새로 open 상태인 주문들만 추가
        await redis.delete(open_key)
        for item in new_open_list:
            await redis.rpush(open_key, item)

        # closed_orders 키에 종료된 주문 추가 (기존 데이터와 합칠지, 새로 저장할지는 비즈니스 로직에 맞게 결정)
        if closed_list:
            for item in closed_list:
                await redis.rpush(closed_key, item)
            logger.info(f"[{user_id}] Closed orders moved to key: {closed_key}")

    async def close(self):
        """클라이언트 리소스 정리"""
        try:
            if self.trading_service.client is not None:
                # ccxt exchange 인스턴스 정리
                await self.trading_service.client.close()
                self.trading_service.client = None

            logger.debug(f"Trading service closed for user {self.trading_service.user_id}")
        except Exception as e:
            logger.error(f"Error closing trading service: {e}")

    async def get_order_status(self, *, user_id: str, order_id: str, symbol: str) -> dict:
        """
        주어진 주문 ID에 대해 주문 상태를 조회합니다.
        OKX API (ccxt의 fetch_order)를 활용하여 주문 상태를 가져오며,
        주문 상태 딕셔너리 예시:
          {
              "order_id": order_id,
              "status": "filled" or "open" or "error",
              "filled_size": <float>,
              "avg_fill_price": <float>
          }
        """
        try:
            # OKX API를 통해 주문 상태 조회
            order_status = await self.trading_service.client.fetch_order(order_id, symbol)
            # 주문 상태 값은 상황에 따라 다를 수 있으므로, 필요한 필드를 추출합니다.
            status = order_status.get("status", "unknown")
            filled_size = safe_float(order_status.get("filled_size", order_status.get("filled", 0.0)))
            avg_fill_price = safe_float(order_status.get("avg_fill_price", order_status.get("average", 0.0)))
            return {
                "order_id": order_id,
                "status": status,
                "filled_size": filled_size,
                "avg_fill_price": avg_fill_price,
            }
        except Exception as e:
            logger.error(f"get_order_status() error for order {order_id}: {str(e)}")
            return {
                "order_id": order_id,
                "status": "error",
                "error": str(e)
            }

    async def get_order_info(self, user_id: str, symbol: str, order_id: str, is_algo=False, exchange: ccxt.Exchange = None) -> dict:
        """
        ccxt 기반으로 해당 order_id의 주문 정보를 반환한다.
        OKX 기준:
          - 일반 주문: fetch_order(order_id, symbol)
          - 알고(ALGO) 주문: OKX 전용 Private API 호출
        :param is_algo: SL같은 ALGO 주문이면 True
        :return: {
            "status": "filled" / "canceled" / "open" ...
            "id": "...",
            ...
        }
        """
        exchange = self.trading_service.client if not exchange else exchange
        try:
            return await get_order_info_from_module(user_id=user_id, symbol=symbol, order_id=order_id, is_algo=is_algo, exchange=exchange)
        except Exception as e:
            logger.error(f"get_order_info() 오류: {str(e)}")
            raise
