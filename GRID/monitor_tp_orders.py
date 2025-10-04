from routes.trading_route import ConnectionManager
from shared_state import user_keys 
from HYPERRSI import telegram_message
import asyncio
from GRID.instance import get_exchange_instance
import ccxt.pro as ccxtpro
import ccxt
from datetime import datetime, timedelta, timezone, date
import random


MAX_RETRIES = 3
RETRY_DELAY = 2  # 재시도 사이의 대기 시간(초)

async def retry_async(func, *args, **kwargs):
    func_name = func.__name__  # 함수 이름 가져오기
    #print(f"Retrying {func_name}")
    for attempt in range(MAX_RETRIES):
        try:
            #print(f"Attempting {func_name}: try {attempt + 1}/{MAX_RETRIES}")
            return await func(*args, **kwargs)
        except Exception as e:
            print(f"{func_name} failed on attempt {attempt + 1}/{MAX_RETRIES}. Error: {str(e)}")
            if attempt == MAX_RETRIES - 1:
                print(f"Maximum retries reached for {func_name}. Exiting.")
                raise e
            await asyncio.sleep(RETRY_DELAY)




manager = ConnectionManager()
async def monitor_tp_orders_websocekts(user_id, exchange_name, symbol_name, take_profit_orders_info):
    first_time_check = True
    async def handle_order_update(order):
        level = None
        for symbol, symbol_info in user_keys[user_id]["symbols"].items():
            take_profit_orders_info = symbol_info["take_profit_orders_info"]
            for lvl, info in take_profit_orders_info.items():
                if info["active"]:
                    level = lvl
                    break
        if level is not None:
            if order['status'] == 'closed':
                print(f"레벨 {level} 익절 주문 체결")
                #global_messages.trading_message.put(f"{symbol_name}의 {level}번째 그리드 익절 주문이 체결되었습니다.\n[수량 : {info['quantity']}, 가격 : {info['target_price']} 시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
                message = f"{symbol_name}의 {level}번째 그리드 익절 주문이 체결되었습니다.\n[수량 : {info['quantity']}, 가격 : {info['target_price']} 시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
                await manager.add_user_message(user_id, message)
                asyncio.create_task(telegram_message.send_telegram_message(message, exchange_name, user_id))
                if info['quantity'] == 0:
                    print("❗️DEBUG: 익절 주문 수량이 0입니다. 확인이 필요합니다")
                    print(f"❗️DEBUG: 익절 주문 정보: {info}")
                    print(f"take_profit_orders_info: {take_profit_orders_info}")
                    asyncio.create_task(telegram_message.send_telegram_message(f"❗️DEBUG: {symbol}의 익절 주문 수량이 0입니다. 확인이 필요합니다", exchange_name, user_id, debug = True))
                user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level] = {"order_id": None, "quantity": 0, "target_price": 0, "active": False, "side": None}
                print(f"{symbol_name}의 {level}번째 그리드 익절 주문이 체결되었습니다.")
            elif order['status'] == 'canceled':
                print(f"레벨 {level} 익절 주문 취소")
                user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level] = {"order_id": None, "quantity": 0, "target_price": 0, "active": True, "side": None} #<-- 이게 active가 True인건지, 확인이 필요함.
                print(f"{symbol_name}의 {level}번째 그리드 익절 주문이 취소되었습니다. 익절 테스크를 종료합니다")
                return
            else:
                print(f"레벨 {level} 주문 상태 업데이트: {order['status']}")
    try:
        exchange_instance = await get_exchange_instance(exchange_name, user_id)
    except Exception as e:
        print(f"An error occurred21: {e}")
        return
    try:
        while True:
            await asyncio.sleep(random.uniform(0.5, 2))
            current_time = datetime.now()
            minutes = current_time.minute
            seconds = current_time.second
            # 15분 단위 시간 확인 (14분 55초, 29분 55초, 44분 55초, 59분 55초에 종료)
            if ((minutes in [15, 30, 45, 0] and seconds >= 55)) and not first_time_check:
                #print("15분봉 마감 도달 - 익절 관리 종료")
                try:
                    for level, info in take_profit_orders_info.items():
                        if info["order_id"] is not None:
                            try:
                                await exchange_instance.cancel_order(info["order_id"], symbol_name)
                            except Exception as e:
                                print(f"익절 주문 취소 실패. {symbol_name} {level}레벨, {info['order_id']}")
                                await telegram_message.send_telegram_message(f"익절 주문 취소 실패: {e}", exchange_name, user_id, debug = True)
                                

                        user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["order_id"] = None
                        user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]["active"] = True
                    return
                except Exception as e:
                    print(f"익절 관리 종료 혹은 주문 취소할 것 없음 Monitor_tp_orders: {e}")
                    return
            else:
                for level, info in take_profit_orders_info.items():
                    if info["active"] and info["order_id"] is not None:
                        print(f"레벨 {level} 익절 주문 감시 시작")
                        order = await exchange_instance.watch_orders(info["order_id"], symbol_name)
                        await handle_order_update(order)
                first_time_check = False
                await asyncio.sleep(7)  # 7초마다 체크

    except Exception as e:
        print(f"기타 예외 처리: {e}")
        await asyncio.sleep(5)
    finally:
        await exchange_instance.close()



#아래는, Cluad가 고쳐준 것. 0628 1715
async def monitor_tp_orders_websockets(exchange_instance, symbol_name, user_id, level):
    first_time_check = True
    exchange_name = str(exchange_instance).lower()

    async def handle_order_update(order):
        info = user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level]
        if order['id'] == info['order_id']:
            if order['status'] == 'closed':
                print(f"Fetched order for level {level}: {order}")
                message = f"{symbol_name}의 {level}번째 그리드 익절 주문이 체결되었습니다.\n[수량 : {info['quantity']}, 가격 : {info['target_price']} 시간 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                await manager.add_user_message(user_id, message)
                asyncio.create_task(telegram_message.send_telegram_message(message, exchange_name, user_id))
                if info['quantity'] == 0:
                    print(f"❗️DEBUG2: 익절 주문 수량이 0입니다. 확인이 필요합니다. 레벨: {level}")
                    print(f"❗️DEBUG2: 익절 주문 정보: {info}")
                    print(f"take_profit_orders_info: {user_keys[user_id]['symbols'][symbol_name]['take_profit_orders_info']}")
                print(f"{symbol_name}의 {level}번째 그리드 익절 주문이 체결되었습니다.")    
                user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level] = {"order_id": None, "quantity": 0, "target_price": 0, "active": False, "side": None}
            elif order['status'] == 'canceled':
                print(f"레벨 {level} 익절 주문 취소")
                user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"][level] = {"order_id": None, "quantity": 0, "target_price": 0, "active": False, "side": None}
                print(f"{symbol_name}의 {level}번째 그리드 익절 주문이 취소되었습니다. 익절 테스크를 종료합니다")
                return

    try:
        while user_keys[user_id]["is_running"]:
            await asyncio.sleep(random.uniform(0.7, 2.5))
            current_time = datetime.now()
            minutes = current_time.minute
            seconds = current_time.second
            take_profit_orders_info = user_keys[user_id]["symbols"][symbol_name]["take_profit_orders_info"]

            if ((minutes in [15, 30, 45, 0] and seconds >= 4)) and not first_time_check:
                print("15분봉 마감 도달 - 익절 관리 종료")
                try:
                    if take_profit_orders_info[level]["order_id"] is not None:
                        try:
                            await retry_async(exchange_instance.cancel_order, take_profit_orders_info[level]["order_id"], symbol_name)
                        except Exception as e: 
                            print(f"익절 주문 취소 실패.{symbol_name} {level}레벨, {take_profit_orders_info[level]['order_id']}")
                            print(f"익절 주문 취소 실패: {e}")
                            await telegram_message.send_telegram_message(f"익절 주문 취소 실패: {e}", exchange_name, user_id, debug=True)
                    
                    take_profit_orders_info[level]["order_id"] = None
                    take_profit_orders_info[level]["active"] = True
                    print(f"[{symbol_name}]Set take_profit_orders_info[{level}]['active'] = {take_profit_orders_info[level]['active']}. 물량 : {take_profit_orders_info[level]['quantity']}")
                    print(take_profit_orders_info[level])
                    return
                except Exception as e:
                    print(f"익절 관리 종료 혹은 주문 취소할 것 없음 Monitor_tp_orders: {e}")
                    return
            else:        
                try:
                    info = take_profit_orders_info[level]
                    if info["active"]:
                        order_id = info['order_id']
                        if order_id is not None:
                            if first_time_check:
                                print(f"DEBUG: Fetching order_id {order_id} for level {level}")
                            order = await exchange_instance.watch_order(order_id, symbol_name)
                            await handle_order_update(order)
                        else:
                            continue
                    first_time_check = False
                    await asyncio.sleep(random.uniform(7, 8.5))
                except ccxt.OrderNotFound:
                    print("익절 주문이 이미 체결되었거나 취소되었습니다. 태스크를 종료합니다.")
                    break
    except Exception as e:
        print(f"기타 예외 처리: {e}")
        await telegram_message.send_telegram_message(f"모니터링 중 예외 발생: {e}", exchange_name, user_id, debug=True)
        await asyncio.sleep(5)