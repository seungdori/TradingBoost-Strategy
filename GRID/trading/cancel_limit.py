
import asyncio
import json
import os
import traceback

from shared.database.redis_patterns import redis_context, RedisTTL
from GRID.strategies import strategy
from shared.config import settings

async def get_all_positions(exchange_name, user_id):
    async with redis_context() as redis:
        # Try new Hash pattern first (Phase 2)
        index_key = f'positions:index:{user_id}:{exchange_name}'
        position_keys = await redis.smembers(index_key)

        if position_keys:
            # New Hash pattern: individual positions
            result = {}

            for pos_key in position_keys:
                # pos_key format: "{symbol}:{side}"
                try:
                    symbol, side = pos_key.split(':')
                    position_key = f'positions:{user_id}:{exchange_name}:{symbol}:{side}'

                    # Get position hash
                    position = await redis.hgetall(position_key)
                    if position:
                        pos = float(position.get('pos', 0))

                        if pos != 0:
                            # Aggregate positions by symbol (sum long and short)
                            result[symbol] = result.get(symbol, 0) + pos
                except (ValueError, KeyError) as e:
                    print(f"Error processing position key {pos_key}: {e}")
                    continue

            return result

        # Fallback to legacy JSON array pattern
        position_key = f'{exchange_name}:positions:{user_id}'
        position_data = await redis.get(position_key)

        if position_data is None:
            return {}  # 포지션 정보가 없으면 빈 딕셔너리 반환

        try:
            positions = json.loads(position_data)
            result = {}

            if isinstance(positions, list):
                for position in positions:
                    if isinstance(position, dict):
                        symbol = position.get('instId')
                        pos = float(position.get('pos', 0))
                        if pos != 0:
                            result[symbol] = pos
            elif isinstance(positions, dict):
                for symbol, position in positions.items():
                    if isinstance(position, dict):
                        pos = float(position.get('pos', 0))
                        if pos != 0:
                            result[symbol] = pos

            return result  # 0이 아닌 포지션만 포함된 딕셔너리 반환

        except (json.JSONDecodeError, ValueError, AttributeError) as e:
            print(f"Error processing position data: {e}")
            return {}  # 데이터 파싱 오류 시 빈 딕셔너리 반환


async def cancel_specific_symbol_limit_orders(user_id, exchange_name, symbol):
    print(f'========================[CANCEL ORDERS REQUEST FOR {symbol}]========================')
    async with redis_context() as redis:
        try:
            user_key = f'{exchange_name}:user:{user_id}'
            user_data = await redis.hgetall(user_key)
            if not user_data:
                print(f"User ID {user_id} not found in Redis")
                return

            # 해당 심볼에 대한 포지션 확인
            all_positions = await get_all_positions(exchange_name, user_id)

            if symbol in all_positions:
                await strategy.cancel_all_limit_orders(exchange_name, symbol, user_id)
                print(f"{user_id}의 {symbol}에 대한 모든 Limit Order가 취소되었습니다.")
            else:
                print(f"{user_id}의 {symbol}에 대한 포지션이 없거나 Limit Order가 없습니다.")

        except Exception as e:
            print(f"An error occurred in cancel_specific_symbol_limit_orders: {e}")
            print(traceback.format_exc())
            raise e


async def cancel_user_limit_orders(user_id, exchange_name):
    print('========================[ALL CANCEL ORDERS REQUEST]========================')
    async with redis_context() as redis:
        try:
            user_key = f'{exchange_name}:user:{user_id}'
            user_data = await redis.hgetall(user_key)
            if not user_data:
                print(f"User ID {user_id} not found in Redis")
                return

            # get_all_positions 함수 호출 (await 사용)
            all_positions = await get_all_positions(exchange_name, user_id)

            # all_positions는 이제 {symbol: pos} 형태의 딕셔너리입니다.
            for symbol in all_positions.keys():
                await strategy.cancel_all_limit_orders(exchange_name, symbol, user_id)
                print(f"{user_id}의 {symbol}에 대한 모든 Limit Order가 취소되었습니다.")

            print(f"{user_id}의 모든 심볼에 대한 Limit Order가 취소되었습니다.")
        except Exception as e:
            print(f"An error occurred in cancel_user_limit_orders: {e}")
            print(traceback.format_exc())
            raise e


if __name__ == "__main__":
    user_id = input("사용자 ID를 입력하세요: ")
    exchange_name = 'okx'
    
    # asyncio.run()을 사용하여 비동기 함수 실행
    asyncio.run(cancel_user_limit_orders(user_id, exchange_name))