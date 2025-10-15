import json
import os
import traceback
from typing import Any, Optional

import ccxt.pro as ccxtpro
from pydantic import BaseModel, Field

from GRID.core.redis import get_redis_connection
from GRID.services import user_service_pg as user_database
from shared.config import OKX_API_KEY, OKX_PASSPHRASE, OKX_SECRET_KEY, settings  # 환경 변수에서 키 가져오기

# Global user keys cache
user_keys: dict[int, dict[str, Any]] = {}

class ReadOnlyKeys:

    # Binance keys (not configured - use user keys instead)
    binance_keys: str | None = None
    binance_secret: str | None = None

    # Upbit keys (not configured - use user keys instead)
    upbit_keys: str | None = None
    upbit_secret: str | None = None

    # Bitget keys (not configured - use user keys instead)
    bitget_keys: str | None = None
    bitegt_secret: str | None = None
    bitget_password: str | None = None

    # Bybit keys (not configured - use user keys instead)
    bybit_keys: str | None = None
    bybit_secret: str | None = None

    #OKX READ ONLY #아래가, 2025년 2월 25일 최신.
    OKX_API_KEY=OKX_API_KEY
    OKX_SECRET_KEY=OKX_SECRET_KEY
    OKX_PASSPHRASE=OKX_PASSPHRASE

    # Aliases for backward compatibility
    okx_keys = OKX_API_KEY
    okx_secret = OKX_SECRET_KEY
    okx_password = OKX_PASSPHRASE

    #okx_keys = '3091c663-721b-458c-8d5a-92beb887d6f9'
    #okx_secret = '1741A78A76F6C70C0608B3C85566E3D9'
    #okx_password='Tmdehfl2014!'
    #OKX READ ONLY
    #okx_keys = 'f542196a-e52e-45b0-94dd-57f93da29a11'
    #okx_secret = '3CD5713E0466FBF591C50972DE3FB6D3'
    #okx_password='Dlrudtlr11!1'
    #okx_keys = 'd8d10ac3-2890-4bb9-95f0-70f857dc38e3'
    #okx_secret = '7080F1F233F77A081F735E8C0E6F1FF3'
    #okx_password='Lej1321428!'

#================================================================================================
# GET INSTANCE
#================================================================================================

async def get_exchange_instance(exchange_name: str, user_id: int | str) -> Any | None:
    exchange_name = str(exchange_name).lower()
    try:
        if exchange_name == 'binance':
            exchange_instance = await get_binance_instance(user_id)
        elif exchange_name == 'binance_spot':
            exchange_instance = await get_binance_spot_instance(user_id)
            direction = 'long'
        elif exchange_name == 'upbit':
            exchange_instance = await get_upbit_instance(user_id)
            direction = 'long'
        elif exchange_name == 'bitget':
            exchange_instance = await get_bitget_instance(user_id)
        elif exchange_name == 'bitget_spot':
            exchange_instance = await get_bitget_spot_instance(user_id)
            direction = 'long'
        elif exchange_name == 'okx':
            exchange_instance = await get_okx_instance(user_id)
        elif exchange_name == 'okx_spot':
            exchange_instance = await get_okx_spot_instance(user_id)
        print(f"Got exchange instance for {user_id}21,  {exchange_name}")
        return exchange_instance
    except Exception as e:
        print(f"Error getting exchange instance for{user_id}21,  {exchange_name}: {e}")
        return None
    #finally:
    #    await exchange_instance.close()

async def get_upbit_instance(user_id: int | str) -> Any | None:
    redis = await get_redis_connection()
    try:
        #print(f"Getting upbit instance for {user_id}")
        if user_id == 999999999 or user_id == 'admin':
            return ccxtpro.upbit({
                'apiKey': ReadOnlyKeys.upbit_keys,
                'secret': ReadOnlyKeys.upbit_secret,
                'enableRateLimit': True
            })
        else:
            user_key = f'upbit:user:{user_id}'
            user_data = await redis.hgetall(user_key)
            if user_data:
                if 'api_key' in user_data and 'api_secret' in user_data:
                    upbit_instance = ccxtpro.upbit({
                        'apiKey': user_data['api_key'],
                        'secret': user_data['api_secret'],
                        'enableRateLimit': True
                    })
                    return upbit_instance
                else:
                    print(f"Missing API keys for user {user_id}")
            else:
                print(f"No data found for user {user_id}")
            return None
    except Exception as e:
        print(f"Error getting upbit instance for {user_id}: {e}")
        print(traceback.format_exc())
        return None
    finally:
        await redis.close()
        
async def get_okx_instance(user_id: int | str) -> Any | None:
    redis = await get_redis_connection()
    try:
        #print(f"Getting okx instance for {user_id}")

        if user_id == 999999999 or user_id == 'admin':
            return ccxtpro.okx({
                'apiKey': ReadOnlyKeys.okx_keys,
                'secret': ReadOnlyKeys.okx_secret,
                'password': ReadOnlyKeys.okx_password,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future'
                }
            })
        else:
            user_key = f'okx:user:{user_id}'
            user_data = await redis.hgetall(user_key)
            #print(f"User data: {user_data}")

            if user_data and 'api_key' in user_data:
                okx_instance = ccxtpro.okx({
                    'apiKey': user_data['api_key'],
                    'secret': user_data['api_secret'],
                    'password': user_data['password'],
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'future'
                    }
                })
                return okx_instance
            else:
                print(f"No API keys found for user {user_id}")
                return None

    except Exception as e:
        print(f"Error getting okx instance for {user_id}: {e}")
        return None
    finally:
        await redis.close()

async def get_okx_spot_instance(user_id: int | str) -> Any:
    global user_keys
    user_id = int(user_id)
    if user_id not in user_keys or 'api_key' not in user_keys[user_id]:
        user_keys = await user_database.get_user_keys('okx')
    return ccxtpro.okx({
        'apiKey': user_keys[user_id]['api_key'],
        'secret': user_keys[user_id]['api_secret'],
        'password': user_keys[user_id]['password'],
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot'  # 'spot'를 사용하여 스팟 거래소로 설정
        }
    })

async def get_binance_instance(user_id: int | str) -> Any:
    global user_keys
    if user_id == 999999999 or user_id == 'admin':
        return ccxtpro.binance({
            'apiKey': ReadOnlyKeys.binance_keys,
            'secret': ReadOnlyKeys.binance_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future'  # 'future'를 사용하여 선물 거래소로 설정
            }})
    else:
        user_id = int(user_id)
        if user_id not in user_keys or 'api_key' not in user_keys[user_id]:
            user_keys = await user_database.get_user_keys('binance')
        return ccxtpro.binance({
            'apiKey': user_keys[user_id]['api_key'],
            'secret': user_keys[user_id]['api_secret'],
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future'  # 'future'를 사용하여 선물 거래소로 설정
            }
        })

async def get_binance_spot_instance(user_id: int | str) -> Any:
    global user_keys
    if user_id == 999999999 or user_id == 'admin':
        return ccxtpro.binance({
            'apiKey': ReadOnlyKeys.binance_keys,
            'secret': ReadOnlyKeys.binance_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'  # 'spot'를 사용하여 스팟 거래소로 설정
            }})
    else:
        user_id = int(user_id)
        if user_id not in user_keys or 'api_key' not in user_keys[user_id]:
            user_keys = await user_database.get_user_keys('binance')
        return ccxtpro.binance({
            'apiKey': user_keys[user_id]['api_key'],
            'secret': user_keys[user_id]['api_secret'],
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'  # 'spot'를 사용하여 스팟 거래소로 설정
            }
        })

    
async def get_bitget_instance(user_id: int | str) -> Any:
    global user_keys
    if user_id == 999999999 or  user_id == 'admin':
        return ccxtpro.bitget({
            'apiKey': ReadOnlyKeys.bitget_keys,
            'secret': ReadOnlyKeys.bitegt_secret,
            'password': ReadOnlyKeys.bitget_password,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap'  # 'swap'를 사용하여 선물 거래소로 설정
            }
        })
    else:
        user_id = int(user_id)
        if user_id not in user_keys or 'api_key' not in user_keys[user_id]:
            user_keys = await user_database.get_user_keys('bitget')
        return ccxtpro.bitget({
            'apiKey': user_keys[user_id]['api_key'],
            'secret': user_keys[user_id]['api_secret'],
            'password': user_keys[user_id]['password'],
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap'  # 'swap'를 사용하여 선물 거래소로 설정
            }
        })
            
            
        
    
async def get_bitget_spot_instance(user_id: int | str) -> Any:
    global user_keys
    if  user_id == 999999999 or user_id == 'admin':
        return ccxtpro.bitget({
            'apiKey': ReadOnlyKeys.bitget_keys,
            'secret': ReadOnlyKeys.bitegt_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'  # 'spot'를 사용하여 스팟 거래소로 설정
            }
        })
    else:
        user_id = int(user_id)
        if user_id not in user_keys or 'api_key' not in user_keys[user_id]:
            user_keys = await user_database.get_user_keys('bitget')
        return ccxtpro.bitget({
            'apiKey': user_keys[user_id]['api_key'],
            'secret': user_keys[user_id]['api_secret'],
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'  # 'spot'를 사용하여 스팟 거래소로 설정
            }
        })
    



async def get_bybit_instance(user_id: int | str) -> Any:
    global user_keys
    if user_id == 'admin' or user_id == 999999999:
        return ccxtpro.bybit({
            'apiKey': ReadOnlyKeys.bybit_keys,
            'secret': ReadOnlyKeys.bybit_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future'  # 'future'를 사용하여 선물 거래소로 설정
            }
        })
    else:
        user_id = int(user_id)
        if user_id not in user_keys or 'api_key' not in user_keys[user_id]:
            user_keys = await user_database.get_user_keys('bybit')
        return ccxtpro.bybit({
            'apiKey': user_keys[user_id]['api_key'],
            'secret': user_keys[user_id]['api_secret'],
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future'  # 'future'를 사용하여 선물 거래소로 설정
            }
        })


async def get_bybit_spot_instance(user_id: int | str) -> Any:
    global user_keys
    user_id = int(user_id)
    if user_id not in user_keys or 'api_key' not in user_keys[user_id]:
        user_keys = await user_database.get_user_keys('bybit')
    return ccxtpro.bybit({
        'apiKey': user_keys[user_id]['api_key'],
        'secret': user_keys[user_id]['api_secret'],
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot'  # 'spot'를 사용하여 스팟 거래소로 설정
        }
    })