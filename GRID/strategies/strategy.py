import trace
import ccxt
import asyncio
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation, ConversionSyntax
from httpx import get
import redis
from GRID.trading import instance
from GRID.api.apilist import telegram_store
from GRID.trading.get_minimum_qty import round_to_qty, split_contracts, get_perpetual_instruments, get_lot_sizes
import logging
from HYPERRSI import telegram_message
from queue import Queue
from datetime import datetime, timedelta
import pytz  # type: ignore[import-untyped]
import aiohttp
import math
import traceback
from GRID.database import redis_database as database
import random
from typing import Any, Optional
global order_ids

order_ids: dict[str, Any] = {}
from shared.utils import retry_async

seoul_timezone = pytz.timezone('Asia/Seoul')
now = datetime.now(tz=seoul_timezone)


class MemoryCache:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[Any, datetime]] = {}

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        expiry = datetime.now() + timedelta(seconds=ttl_seconds)
        self._cache[key] = (value, expiry)

    def get(self, key: str) -> Any | None:
        if key in self._cache:
            value, expiry = self._cache[key]
            if datetime.now() < expiry:
                return value
            else:
                del self._cache[key]
        return None

    def clear_expired(self) -> None:
        now = datetime.now()
        self._cache = {k: v for k, v in self._cache.items() if v[1] > now}
        
memory_cache = MemoryCache()



MAX_RETRIES = 3
RETRY_DELAY = 3  # 재시도 사이의 대기 시간(초)

# retry_async is now imported from shared.utils


async def get_exchange_instance(exchange_name: str, user_id: str) -> Any | None:
    exchange_name = str(exchange_name).lower()
    try:
        if exchange_name == 'binance':
            exchange_instance = await instance.get_binance_instance(user_id)
        elif exchange_name == 'binance_spot':
            exchange_instance = await instance.get_binance_spot_instance(user_id)
            direction = 'long'
        elif exchange_name == 'upbit':
            exchange_instance = await instance.get_upbit_instance(user_id)
            direction = 'long'
        elif exchange_name == 'bitget':
            exchange_instance = await instance.get_bitget_instance(user_id)
        elif exchange_name == 'bitget_spot':
            exchange_instance = await instance.get_bitget_spot_instance(user_id)
            direction = 'long'

        elif exchange_name == 'okx':
            try:
                print('okx instance 호출', user_id)
                exchange_instance = await instance.get_okx_instance(user_id)
            except Exception as e:
                print(f"Error getting exchange instance for{user_id}5,  {exchange_name}: {e}")
                print(traceback.format_exc())
                return None
        elif exchange_name == 'okx_spot':
            exchange_instance = await instance.get_okx_spot_instance(user_id)
        return exchange_instance
    except Exception as e:
        print(f"Error getting exchange instance for{user_id}7,  {exchange_name}: {e}")
        return None



def safe_abs(input_value: Any) -> float | str:
    try:
        # 문자열을 실수로 변환
        numeric_value = float(input_value)
        # 절대값을 반환
        return abs(numeric_value)
    except ValueError:
        # 변환에 실패하면 오류 메시지 반환
        return "ValueError: input_value must be a number or a string that represents a number"


async def change_leverage(exchange_name: str, symbol: str, leverage: int | str, user_id: str, retries: int = 2, delay: int = 2) -> Any | None:
    leverage_int = int(leverage)
    exchange = None
    try:

        exchange = await get_exchange_instance(exchange_name, user_id)
        if exchange is None:
            return None
        if exchange_name.lower() not in ['binance', 'bitget', 'okx']:
            raise ValueError(f"레버리지 설정은 바이낸스/비트겟/okx에서만 가능합니다. {exchange}" )

        for attempt in range(1, retries + 1):
            try:
                if exchange_name.lower() == 'bitget':
                    response = await exchange.set_leverage(leverage_int, symbol, params={'contract_type': 'swap','position_mode': 'single','marginCoin': 'USDT'})
                    print(f"Attempt {attempt}: Success", response)
                    return response  # 성공 시 반복 종료
                else:
                    try:
                        response = await exchange.set_leverage(leverage_int, symbol)
                        print(f"Attempt {attempt}: Success", response)
                        return response
                    except Exception as e:
                        if 'API' in str(e):
                            print(f"Attempt {attempt}: An error occurred change leverage {symbol} because : {e}. shut down.")
                            redis = await database.get_redis_connection()
                            key = f"{exchange_name}:user:{user_id}"
                            await redis.hset(key, mapping={'is_running': '0'})
                            await exchange.close()
                            return None
                        print(f"Attempt {attempt}: An error occurred change leverage {symbol} because : {e}")
                        return None
            except Exception as e:
                print(f"Attempt {attempt}: An error occurred3a: {e}")
                if attempt == retries:
                    asyncio.create_task(telegram_message.send_telegram_message(f"Final attempt failed: {e}", exchange, debug=True))
                    raise  # 마지막 시도에서도 실패한 경우, 메시지를 보내고 반복 종료
                await asyncio.sleep(delay)  # 지정된 딜레이 후에 다시 시도 # Todo: Performance check
        return None
    finally:
        if exchange is not None:
            await exchange.close()
        

from shared.utils.exchange_precision import (
    get_corrected_rounded_price,
    get_order_price_unit_upbit as get_order_price_unit,
    round_to_upbit_tick_size as round_to_tick_size
)

# Backward compatibility: re-export functions
__all__ = ['get_corrected_rounded_price', 'get_order_price_unit', 'round_to_tick_size']

####거래소별 들어오는 심볼명#####
#binance -> 'ALTUSDT' 형식
#upbit -> 'KRW-TRX'형식
#########################



async def close_position(exchange: Any, symbol: str, side: str, quantity: float, user_id: str) -> None:
    print('close position호출')
    exchange_flag = False
    if not isinstance(exchange, ccxt.Exchange):
        exchange = await get_exchange_instance(exchange, user_id)
        exchange_flag = True
    else:
        exchange = exchange
    await cancel_all_limit_orders(exchange, symbol, user_id)
    try:
        side = side.lower()
        if side in ['long', 'buy']:
            order_side = 'sell'
        elif side in ['short', 'sell']:
            order_side = 'buy'
        else:
            print("Error: Invalid side input")
        order = await exchange.create_order(
            symbol=symbol,
            type='market',
            side=order_side,
            amount=abs(quantity),  # quantity는 절대값으로 지정합니다.
            params={'reduceOnly': True}
        )
        print(f"Closed position for {symbol}: {order}")
    except Exception as e:
        print(f"An error occurred while closing the position for {symbol}: {e}")
    finally:
        if exchange is not None and exchange_flag == True:
            await exchange.close()


async def close(exchange: Any, symbol: str, order_id: str | None = None, qty: float | None = None, qty_perc: int | None = None, message: str | None = None, action: str | None = None, user_id: str | None = None) -> Any | None:
    quantity = 0.0
    new_instance = False
    print(f"close주문의 orderid : {order_id}")
    #print(f"exchange : {exchange}")
    print(f"user_id : ", user_id)
    if not isinstance(exchange, ccxt.Exchange) and user_id is not None:
        exchange = await get_exchange_instance(exchange, user_id)
        new_instance = True
    # qty 변수의 타입과 값을 출력
    initial_qty = safe_abs(qty) if qty is not None else None
    print(f"qty 변수 타입: {type(qty)}, 값: {initial_qty}")
    if qty is not None and isinstance(qty, (str, int)):
        qty = float(qty)
    print(f"변환 후 qty 변수 타입: {type(qty)}, 값: {qty}")
    try:
        if (action != 'close_long') and (action != 'close_short'):
            await cancel_all_limit_orders(exchange, symbol, user_id)
    except Exception as e:
        print(f"주문 취소 중 오류 발생: {e}")
        print(traceback.format_exc())
        # 업비트 또는 빗썸 거래소인 경우
    try:
        order = None
        if (exchange.id).lower() == 'okx':
            market_type = exchange.options.get('defaultType', 'No market type set')
            if market_type == 'future':
                positions_data = await exchange.private_get_account_positions()
                #quantity = 3.0 #<--이렇게 하면 잘 된다.
                for position in positions_data['data']:  # 'data' 키를 통해 실제 포지션 목록에 접근합니다.
                    if position['instId'] == symbol:  # 'instId'를 확인하여 원하는 심볼의 포지션을 찾습니다.
                        quantity = float(position['pos'])  # 'pos' 값을 float로 변환합니다.
                        print(f"type : {type(quantity)}, value : {quantity}")  # 변환된 값을 출력합니다.
            elif market_type == 'spot':
                positions_data = await exchange.fetch_balance()
                #print(f"잔고 데이터 : {balance_data}")
                base_currency = symbol.split('-')[0]
                if base_currency in positions_data:
                    quantity = float(positions_data[base_currency]['free'])
                    print(f"{symbol}의 type : {type(quantity)}, value : {quantity}")
            #print(f"포지션 데이터 : {positions_data}"        
        elif exchange.id.lower() == 'upbit':
            try:
                balance = await exchange.fetch_balance()
                base_currency = symbol.split('-')[1]  # 'KRW-ETC'에서 'ETC'를 추출
                free_balance = balance['free'].get(base_currency)  # 사용 가능 잔고 추출
                # qty가 float 타입인지 확인
                if qty is not None and not isinstance(qty, float):
                    print(f"{exchange}: qty는 float 타입이어야 합니다. 현재 타입: {type(qty)}")  # type: ignore[unreachable]
                    return None
                if qty is None:
                    qty = free_balance
                    if qty is None:
                        print(f"{exchange}: 수량이 지정되지 않았습니다.⛔️디버그 필요!")
                        return None
            
            # 업비트의 시장가 주문 생성
                # 시장가 주문 생성
                if initial_qty is not None:
                    amount = min(safe_abs(qty), initial_qty)
                    print(f"{amount} : min(qty, initial_qty)")
                else:
                    amount = safe_abs(qty)
                    print(f"정확한 값 {safe_abs(qty)} 오더 시도" )
                amount = min(free_balance, amount)
                if (action is None) or action == 'close_long':
                    order = await exchange.create_order(
                    symbol=symbol,
                    type='market',
                    side='sell' if qty > 0 else 'buy',
                    amount=amount)
                    print(f"주문 생성 결과: {order}")
                    try:
                        if message:
                            asyncio.create_task(telegram_message.send_telegram_message(message, exchange, user_id))
                            #global_messages.trading_message.put(message)
                        return order
                    except Exception as e:
                        print("텔레그램 메시지 전송 중 오류 발생:", e)
                return None
            except Exception as e:
                print(f"업비트 종료 주문 생성 중 오류 발생: {e}")
                print(traceback.format_exc())
            

        else:
            if order_id:
                #position = await exchange.fetch_order(symbol, order_id)
                position = await exchange.fetch_positions([symbol], params={'order': order_id})
                positions = [position]  # 단일 포지션을 리스트로 변환

            else:
                
                # order_id가 없는 경우, 해당 심볼의 모든 포지션을 가져오기
                positions = await exchange.fetch_positions([symbol])
                if positions and len(positions) > 0:
                    position = positions[0]  # 첫 번째 포지션 정보 사용
                    quantity = float(position['info']['positionAmt'])  # 포지션 양 추출
                else:
                    position = None
                    print(f"포지션 없음: {symbol}")
                    return None
            quantity = float(position['info']['positionAmt'])
        if not quantity:
            #if message is not None:
            #    asyncio.create_task(telegram_message.send_telegram_message(message, exchange))
            #    return
            #else:
                return None
        else:
            print(f'퀀티티 : {quantity}')
            if qty_perc is not None:
                quantity = (quantity*qty_perc/100)
            else:
                quantity = quantity
            side = 'sell' if quantity > 0 else 'buy'
            if action == 'close_long':
                side = 'sell'
            elif action == 'close_short':
                side = 'buy'
            order = await exchange.create_order(
                symbol=symbol,
                side=side,
                type='market',
                amount=safe_abs(quantity)  # 'quantity'를 'amount'로 변경
            )
            print(f"주문 생성 결과: {order}")
            if order:
                try:
                    if message:
                        asyncio.create_task(telegram_message.send_telegram_message(message, exchange, user_id))
                        #global_messages.trading_message.put(message)
                except Exception as e:
                    print("텔레그램 메시지 전송 중 오류 발생:", e)
        return order  # 생성된 주문 반환
    except ccxt.InvalidOrder as e:
        print(f"최소 주문량 오류, 주문을 스킵합니다: {e}")
        return None
    except Exception as e:
        print(f"close 주문 예외 발생: {e}, qty : {qty}")
        print(traceback.format_exc())
        try:
            if qty is not None:
                await adjust_order_amount(exchange, symbol, float(qty), message)
        except Exception as e:
            logging.error(f"종료 주문 중 오류 발생: {e} qty : {qty}")
            print(traceback.format_exc())
        return None
    finally:
        if new_instance:
            await exchange.close()


def safe_decimal_convert(value: Any) -> Decimal | None:
    if value is None:
        print('safe decimal convert에서 value가 None입니다.')
        return None
    if isinstance(value, dict):
        value = next(iter(value.values()))
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ConversionSyntax) as e:
        print(f"Invalid decimal value: {value}. Error: {e}")
        return None


async def place_order(exchange: Any, symbol: str, order_type: str, side: str, amount: Any, price: Any = None) -> Any | None:
    print(f"place {symbol} order amount : {amount} on {price}")
    #UPBIT 전용 for GRID#
    await asyncio.sleep(0.1)
    exchange_name = str(exchange).lower()
    try:
        if price is None:
            order_type = 'market'
        if price is None and order_type == 'market':
            if (exchange_name == 'upbit'): 
                exchange.options['createMarketBuyOrderRequiresPrice'] = False
            else:
                # 다른 거래소의 경우 기본 동작 유지
                pass
        # 수량과 가격을 Decimal 객체로 변환
        #print(f"원본 amount: {amount}, price: {price}")
        try:
            amount = Decimal(str(amount).replace('{', '').replace('}', ''))
        except InvalidOperation as e:
            print(f"Invalid amount value: {amount}. Error: {e}")
            amount = amount
        #print(f"Decimal 변환 후 amount: {amount}")
        try:
            if price is not None:
                price = Decimal(str(price))
        except InvalidOperation as e:
            print(f"Invalid price value: {price}. Error: {e}")
        
            #print(f"Decimal 변환 후 price: {price}")
        try:
            # 주문 생성

            order = await exchange.create_order(symbol, order_type, side, amount, price)
        except Exception as e:
            print(f"주문 생성 중 오류 발생: {e}")
            print(f"주문하려던 amount : {amount}")
            print(f"주문하려던 side : {side}")
            
            print(traceback.format_exc())
            raise e

        # 주문 ID 확인
        if 'id' in order:
            order_id = order['id']
            #print(f"주문 ID: {order_id}")
        else:
            print("주문 ID가 없습니다.")
        if side == 'sell' and exchange_name == 'upbit':
            try:
                print(order)
                time = datetime.now()
                today = time.strftime('%Y-%m-%d %H:%M:%S')
                print(f"주문 생성 성공 - {symbol}side: {side} qty = {amount} price = {price}, today = {today}")
            except Exception as e:
                print(f"주문 생성 실패확인 : {e}")
        return order
    except Exception as e:
        print(f"Entry failed: {e}")
        print(traceback.format_exc())
        if "Event loop is closed" in str(e) and "session" in str(e):  # "Event loop is closed" 메시지가 포함되어 있을 경우
            # 여기서 아무런 동작도 하지 않음
            pass
        if "insufficient_funds" in str(e):
            print("Need to Handling insufficient funds error...")
            print(f"주문하려던 포지션 크기 : {price}*{amount}  = {price*amount}")
            message = "주문가능한 금액이 부족합니다. 잔고를 확인해주세요"
            asyncio.create_task(telegram_message.send_telegram_message(message, exchange, debug=True))
            raise e
        if 'Authentication error' in str(e):
            print("Need to Handling Authentication error...")
            message = "API 키가 잘못되었습니다. 확인해주세요."
            asyncio.create_task(telegram_message.send_telegram_message(message, exchange, debug=True))
            raise e
        else:  # 다른 예외의 경우에는 Telegram 메시지를 보냄
            asyncio.create_task(telegram_message.send_telegram_message(str(e), exchange, debug=True))
        return None


async def check_order_status(exchange: Any, symbol: str, order_id: str, max_retries: int = 3, delay: int = 2) -> Any | None:
    retry_count = 0
    while retry_count < max_retries:
        try:
            print(f"시도 {retry_count + 1}: check_order_status의 order_id : {order_id}")
            print(f"Entering function check_order_status with symbol: {symbol} and order_id: {order_id}")
            order_status = await exchange.fetch_order(order_id, symbol)
            print(f"order_status: {order_status}")
            return order_status
        except Exception as e:
            print(f"시도 {retry_count + 1}: Error in fetch_order: {e}")
            retry_count += 1
            if retry_count < max_retries:
                print("잠시 후에 재시도합니다...")
                await asyncio.sleep(delay)  # 잠시 대기 후 재시도
            else:
                print("주문 상태 조회 실패. 최대 재시도 횟수 도달.")
                return None
    return None


async def cancel_all_limit_orders(exchange: Any, symbol: str, user_id: str | None = None, side: str | None = None) -> tuple[list[str], list[tuple[str, str]]]:
    print(f"Cancelling symbol : {symbol}" + (f" with side: {side}" if side else ""))
    retry_delay = 2
    max_retries = 4
    retry_attempts = 0
    exchange_name = str(exchange).lower()
    close_instance_flag = False
    cancelled_orders: list[str] = []
    failed_orders: list[tuple[str, str]] = []

    # side 값 정규화
    normalized_side = None
    if side:
        if side.lower() in ['sell', 'short']:
            normalized_side = 'sell'
        elif side.lower() in ['buy', 'long']:
            normalized_side = 'buy'

    try:
        if not isinstance(exchange, ccxt.Exchange) and user_id is not None:
            exchange = await get_exchange_instance(exchange, user_id)
            close_instance_flag = True

        while retry_attempts < max_retries:
            cache_key = f"{exchange_name}:{symbol}:open_orders"
            cached_orders = memory_cache.get(cache_key)
            
            if cached_orders is None:
                orders = await retry_async(exchange.fetch_open_orders, symbol)
                memory_cache.set(cache_key, orders, 10)
            else:
                orders = cached_orders

            # side가 지정된 경우 해당 side의 limit 주문만 필터링
            if normalized_side:
                limit_order_ids = [order['id'] for order in orders if order['type'] == 'limit' and order['side'] == normalized_side]
            else:
                limit_order_ids = [order['id'] for order in orders if order['type'] == 'limit']
            
            if not limit_order_ids:
                return [], []

            side_text = f"{normalized_side} " if normalized_side else ""
            print(f"{symbol}에 대한 {side_text}limit order 갯수 : {len(limit_order_ids)}")

            if exchange_name == 'upbit':
                await cancel_orders_individually(exchange, symbol, limit_order_ids, cancelled_orders, failed_orders)
            else:
                try:
                    results = await exchange.cancel_orders(limit_order_ids, symbol)
                    for order_id, result in zip(limit_order_ids, results):
                        if isinstance(result, dict) and result.get('status') == 'canceled':
                            cancelled_orders.append(order_id)
                        else:
                            failed_orders.append((order_id, str(result)))
                except ccxt.ExchangeError as e:
                    if "Canceled order count exceeds the limit 20" in str(e):
                        print("Batch cancellation limit exceeded. Switching to individual cancellation.")
                        await cancel_orders_individually(exchange, symbol, limit_order_ids, cancelled_orders, failed_orders)
                    else:
                        raise
                except ccxt.NotSupported:
                    print(f"Batch cancellation not supported for {exchange.id}, switching to individual cancellation.")
                    await cancel_orders_individually(exchange, symbol, limit_order_ids, cancelled_orders, failed_orders)

            side_msg = f"{normalized_side} " if normalized_side else ""
            message = f"Cancelled {len(cancelled_orders)} {side_msg}limit orders for {symbol}.\n"
            if failed_orders:
                message += f"Failed to cancel {len(failed_orders)} orders."
            print(message)
            return cancelled_orders, failed_orders

    except Exception as e:
        #print(traceback.format_exc())
        print(f"An error occurred: {e}. Retrying...")
        retry_attempts += 1
        await asyncio.sleep(retry_delay)
    finally:
        if close_instance_flag:
            await exchange.close()
            close_instance_flag = False
    return cancelled_orders, failed_orders


async def cancel_orders_individually(exchange: Any, symbol: str, order_ids: list[str], cancelled_orders: list[str], failed_orders: list[tuple[str, str]]) -> None:
    for order_id in order_ids:
        try:
            await exchange.cancel_order(order_id, symbol)
            cancelled_orders.append(order_id)
        except Exception as e:
            if "does not exist" in str(e) or "주문을 찾지 못했습니다" in str(e):
                cancelled_orders.append(order_id)
            else:
                print(f"Error cancelling order {order_id}: {e}")
                failed_orders.append((order_id, str(e)))
        await asyncio.sleep(0.35)  # 개별 취소 사이에 짧은 지연 추가    

async def cancel_long_limit_orders(exchange: Any, symbol: str) -> str | None:
    retry_delay =2
    max_retries = 3
    retry_attempts = 0
    while retry_attempts < max_retries:
        try:
            # 주어진 심볼에 대한 모든 주문 조회
            orders = await exchange.fetch_open_orders(symbol)
            message = ""
            for order in orders:
                # 빗썸 거래소인 경우, 매도('sell') 지정가 주문만 취소
                # 다른 거래소의 경우, 모든 지정가 주문 취소
                if order['type'] == 'limit':
                    await exchange.cancel_order(order['id'], symbol)
                    message += f"Cancelled Limit Order: {order['id']}\n"


            if message == "":
                message = "No limit orders to cancel."

            print(message)
            return message
        except Exception as e:
            print(f"An error occurred2a: {e}. Retrying...")
            retry_attempts += 1
            await asyncio.sleep(retry_delay)

    return None

async def cancel_short_limit_orders(exchange: Any, symbol: str) -> str | None:
    retry_delay =2
    max_retries = 3
    retry_attempts = 0
    while retry_attempts < max_retries:
        try:
            # 주어진 심볼에 대한 모든 주문 조회
            orders = await exchange.fetch_open_orders(symbol)
            message = ""
            for order in orders:
                # 빗썸 거래소인 경우, 매도('sell') 지정가 주문만 취소
                # 다른 거래소의 경우, 모든 지정가 주문 취소
                if order['type'] == 'limit' and order['side'] == 'sell':
                    await exchange.cancel_order(order['id'], symbol)
                    message += f"Cancelled Limit Order: {order['id']}\n"


            if message == "":
                message = "No limit orders to cancel."

            print(message)
            return message
        except Exception as e:
            print(f"An error occurred7a: {e}. Retrying...")
            retry_attempts += 1
            await asyncio.sleep(retry_delay)

    return None


async def close_remain_position(exchange: Any, symbol: str) -> Any | None:
    max_retries=3
    retry_delay=2
    retry_count = 0
    while retry_count < max_retries:
        try:
            # 포지션 정보 가져오기
            balance = await exchange.fetch_balance({'type': 'future'})
            positions = balance['info']['positions']
            symbol_position = next((item for item in positions if item['symbol'] == exchange.market_id(symbol)), None)
            if symbol_position and float(symbol_position['positionAmt']) != 0:
                # 포지션 종료
                side = 'sell' if float(symbol_position['positionAmt']) > 0 else 'buy'
                quantity = abs(float(symbol_position['positionAmt']))
                order = await exchange.create_market_order(symbol, side, quantity)
                print(order)
                #await exchange.close()
                return order
            else:
                print("No open position for this symbol.")
                break
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            print(f"Error occurred...! : {e}, retrying in {retry_delay} seconds...")
            await asyncio.sleep(retry_delay)
            retry_count += 1
    if retry_count >= max_retries:
        print("Max retries reached, giving up.")
    return None




async def adjust_order_amount(exchange: Any, symbol: str, qty: float, message: str | None = None) -> Any | None:
    try:
        positions: Any = None
        free_balance: Any = 0.0

        if exchange.name.lower() == 'okx':
            print(symbol)
            positions = await exchange.private_get_account_positions()
            #position = await okx.fetch_positions(symbol)
            print(positions)
            base_currency = symbol
            free_balance = int(positions['pos'])

            #base_currency = symbol.split('-')[0]
            #free_balance = balance[base_currency]['free']
            #print(base_currency)
        # 사용 가능한 잔액 조회
        balance = await exchange.fetch_balance()
        print(balance)
        base_currency = symbol.split('/')[0]
        if exchange.name.lower() == 'binance':
            base_currency = symbol.split('USDT')[0]
        bitget_symbol = symbol + '/USDT:USDT'
        free_balance = balance[base_currency]['free']
        if exchange.name.lower() == 'upbit':
            base_currency = symbol.split('-')[1]  # 'KRW-ETC'에서 'ETC'를 추출
            print(base_currency)
            if positions is not None:
                target_position = next((position for position in positions if position['symbol'] == symbol), None)
            else:
                target_position = None
            free_balance = float(balance[symbol]['positionAmt'])
            # 해당 심볼의 positionAmt 얻기
            if target_position:
                position_amt = float(target_position['positionAmt'])
                print(position_amt)
                if free_balance is None :
                    free_balance = float(balance[symbol]['positionAmt'])
            else:
                print(f"{symbol} 포지션을 찾을 수 없습니다.")
            

            
            print(f"freebalance : {free_balance}")

        # 해당 통화의 사용 가능 잔액을 가져옴 (예: ETH)
        print(f"Base currency: {base_currency}")
        print(free_balance)

        # 주문량이 사용 가능 잔액보다 클 경우, 사용 가능 잔액으로 조정
        if qty > abs(free_balance):
            logging.info(f"조정된 주문량: {free_balance} (최초 주문량: {qty})")
            if free_balance == 0:
                return None
            if free_balance < 0:
                qty = max(free_balance, qty)
                order = await exchange.create_order(
                    symbol= symbol if exchange.name.lower() != 'bitget' else bitget_symbol,
                    type='market',
                    side='buy',
                    amount=qty,
                    params={'reduceOnly': True}
                )
            if free_balance > 0:
                qty = min(free_balance, qty)
                order = await exchange.create_order(
                    symbol= symbol if exchange.name.lower() != 'bitget' else bitget_symbol,
                    type='market',
                    side='sell',
                    amount=qty,
                    params={'reduceOnly': True}
                )


        # 조정된 주문량으로 시장가 주문 생성

        print(order)
        asyncio.create_task(telegram_message.send_telegram_message(message, exchange))
        return order
    except Exception as e:
        logging.error(f"주문 생성 중 오류 발생: {e}")

        return None

async def check_position(exchange: Any, symbol: str) -> Any:
    # 포지션 확인
    positions = await exchange.fetchPositions([symbol])
    print(positions)
    await exchange.close()
    return positions

