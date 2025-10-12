import os
from operator import is_
from typing import List, Optional

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException
from redis.exceptions import RedisError

from GRID.database import redis_database
from GRID.infra import bot_state_store
from GRID.trading.shared_state import user_keys
from shared.config import settings
from shared.constants.enterstrategy import EnterStrategy
from shared.constants.exchange import Exchange
from shared.dtos.bot_state import BotStateDto, BotStateKeyDto

REDIS_PASSWORD = settings.REDIS_PASSWORD


async def get_redis():
    if REDIS_PASSWORD:
        return aioredis.from_url(settings.REDIS_URL, encoding='utf-8', decode_responses=True, password = REDIS_PASSWORD)
    else:
        return aioredis.from_url(settings.REDIS_URL, encoding='utf-8', decode_responses=True)


def build_bot_state_key(dto: BotStateKeyDto) -> str:
    return f"{dto.exchange_name}_{dto.enter_strategy}_{dto.user_id}"




async def get_bot_state(dto: BotStateKeyDto) -> Optional[BotStateDto]:
    redis = await get_redis()
    try:
        user_key = f'{dto.exchange_name}:user:{dto.user_id}'
        is_running_value = await redis.hget(user_key, 'is_running')
        #print(f"[DEBUG] Raw is_running_value: {is_running_value}")
        
        if is_running_value is None:
            is_running = False
        else:
            is_running = is_running_value == '1'
        
        #print(f"[DEBUG] Processed is_running: {is_running}")
        
        return BotStateDto(
            key=f"{dto.exchange_name}_{dto.enter_strategy}_{dto.user_id}",
            exchange_name=dto.exchange_name,
            enter_strategy=dto.enter_strategy,
            user_id=dto.user_id,
            is_running=is_running,
            error=None
        )
    finally:
        await redis.close()


async def get_all_bot_state(app: FastAPI) -> List[BotStateDto]:
    running_user_ids = await redis_database.get_all_running_user_ids()
    bot_states = [BotStateDto(
                    key=f"running_user_{user_id}",
                    exchange_name="",
                    user_id=user_id,
                    enter_strategy="",
                    is_running=True,
                    error=None
                  ) for user_id in running_user_ids]
    return bot_states


async def set_bot_state(new_state: BotStateDto) -> BotStateDto:
    redis = await get_redis()
    user_key = f'{new_state.exchange_name}:user:{new_state.user_id}'

    try:
        # Redis에 봇 상태 업데이트
        await redis.hset(user_key, mapping={'is_running': '1' if new_state.is_running else '0'})

        print(f"Bot state updated for user {new_state.user_id} in {new_state.exchange_name}")
        return new_state

    except RedisError as e:
        print(f"Error updating bot state in Redis: {e}")
        raise
    finally:
        await redis.close()

## services/bot_state_service.py 수정
#async def init_bot_state(app: FastAPI, exchange_names):
#    for exchange_name in exchange_names:
#        user_keys = await user_database.get_user_keys(exchange_name)
#        for user_id in user_keys:
#            user_id_str = str(user_id)
#            for enter_strategy in ['long', 'short', 'long-short']:
#                key = build_bot_state_key(
#                    dto=BotStateKeyDto(
#                        exchange_name=exchange_name,
#                        enter_strategy=enter_strategy,
#                        user_id=user_id_str
#                    )
#                )
#                await set_bot_state(
#                    new_state=BotStateDto(
#                        key=key,

#                        exchange_name=exchange_name,
#                        enter_strategy=enter_strategy,
#                        user_id=user_id_str,
#                        is_running=False
#                    )
#                )
#    print('Bot state initialized')
