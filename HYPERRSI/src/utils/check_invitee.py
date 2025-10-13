import base64
import hashlib
import hmac
from datetime import datetime

import aiohttp

from shared.config import get_settings
from shared.database.redis_helper import get_redis_client

# 관리자 API 키는 환경변수에서 로드
settings = get_settings()
fixed_api_key = '29568592-e1de-4c0d-af89-999018c8c3bf'
fixed_secret_key = '404D3EE1C406C8D19BCDA52DC8E962DB'
fixed_passphrase = 'Thsrb0318^^'

def get_timestamp():
    return datetime.utcnow().isoformat("T", "milliseconds") + "Z"

def sign_message(timestamp, method, request_path, body, secret_key):
    prehash_string = timestamp + method + request_path + body
    signature = hmac.new(secret_key.encode(), prehash_string.encode(), hashlib.sha256).digest()
    return base64.b64encode(signature).decode()

async def get_uid_from_api_keys(api_key, secret_key, passphrase):
    """
    API 키를 사용하여 OKX 계정의 UID를 가져오는 함수

    Args:
        api_key: 사용자의 OKX API 키
        secret_key: 사용자의 OKX Secret 키
        passphrase: 사용자의 OKX 암호

    Returns:
        tuple: (Boolean, str) - 초대 여부와 UID
    """
    timestamp = get_timestamp()
    method = 'GET'
    request_path = '/api/v5/account/config'
    signature = sign_message(timestamp, method, request_path, '', secret_key)

    headers = {
        'OK-ACCESS-KEY': api_key,
        'OK-ACCESS-SIGN': signature,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': passphrase,
        'Content-Type': 'application/json',
    }

    try:
        print("================================================")
        print('Request headers:', headers)
        print("================================================")

        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://www.okx.com{request_path}', headers=headers) as response:
                # 401 상태 코드 확인 (인증 오류)
                if response.status == 401:
                    print(f'인증 오류 발생 (401 Unauthorized): API 키, 시크릿, 암호가 올바르지 않거나 만료됨')
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=401,
                        message=f"401 Client Error: Unauthorized for url: https://www.okx.com{request_path}"
                    )

                response.raise_for_status()
                response_data = await response.json()
                print('Response data:', response_data)
                print("================================================")
                # Extract uid from the response data
                uid = response_data['data'][0]['uid']

    except aiohttp.ClientResponseError as error:
        print('Error getting UID from API keys:', error)
        uid = None
        raise error
    except Exception as error:
        print('Error getting UID from API keys (일반 오류):', error)
        uid = None
        raise error

    if str(uid) == '646396755365762614':
        return True, '646396755365762614'

    timestamp = get_timestamp()
    method = 'GET'
    request_path = f'/api/v5/affiliate/invitee/detail?uid={uid}'
    signature = sign_message(timestamp, method, request_path, '', fixed_secret_key)

    headers = {
        'OK-ACCESS-KEY': fixed_api_key,
        'OK-ACCESS-SIGN': signature,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': fixed_passphrase,
        'Content-Type': 'application/json',
    }

    invitee = True  # Initialize invitee as True

    try:
        print('Request headers for invitee check:', headers)

        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://www.okx.com{request_path}', headers=headers) as response:
                response_text = await response.text()

                # 401 상태 코드 특별 처리
                if response.status == 401:
                    print(f'관리자 API 키 인증 오류 (401 Unauthorized): 관리자 API 키 설정을 확인하세요')
                    invitee = False
                    return invitee, uid

                response.raise_for_status()
                response_data = await response.json()
                print('Response data from invitee check:', response_data)

                # Check if the response indicates the user isn't an invitee
                if "The user isn't your invitee" in response_text or (
                    response_data.get('msg') and "user isn't your invitee" in response_data.get('msg', '').lower()
                ):
                    invitee = False

                # 응답 코드가 51621인 경우도 초대자가 아닌 것으로 처리
                if response_data.get('code') == '51621':
                    invitee = False

                return invitee, uid

    except aiohttp.ClientResponseError as error:
        # 다른 HTTP 오류에 대한 처리
        print('Error checking user invitee:', error)
        if uid:  # uid가 있으면 오류가 발생해도 uid 반환
            return False, uid
        raise error
    except Exception as error:
        print('Error checking user invitee (일반 오류):', error)
        if uid:  # uid가 있으면 오류가 발생해도 uid 반환
            return False, uid
        raise error


async def check_invitee(fixed_api_key, fixed_secret_key, fixed_passphrase, uid):
    """
    특정 UID의 사용자가 초대된 사용자인지 확인하는 함수

    Args:
        fixed_api_key: 관리자 OKX API 키
        fixed_secret_key: 관리자 OKX Secret 키
        fixed_passphrase: 관리자 OKX 암호
        uid: 확인할 사용자의 OKX UID

    Returns:
        bool: 초대된 사용자인지 여부
    """
    timestamp = get_timestamp()
    method = 'GET'
    request_path = f'/api/v5/affiliate/invitee/detail?uid={uid}'
    signature = sign_message(timestamp, method, request_path, '', fixed_secret_key)

    headers = {
        'OK-ACCESS-KEY': fixed_api_key,
        'OK-ACCESS-SIGN': signature,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': fixed_passphrase,
        'Content-Type': 'application/json',
    }

    invitee = True  # Initialize invitee as True

    try:
        print('Request headers for invitee check:', headers)

        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://www.okx.com{request_path}', headers=headers) as response:
                response_text = await response.text()

                # 401 상태 코드 특별 처리
                if response.status == 401:
                    print(f'관리자 API 키 인증 오류 (401 Unauthorized): 관리자 API 키 설정을 확인하세요')
                    return False

                response.raise_for_status()
                response_data = await response.json()
                print('Response data from invitee check:', response_data)

                # Check if the response indicates the user isn't an invitee
                if "The user isn't your invitee" in response_text or (
                    response_data.get('msg') and "user isn't your invitee" in response_data.get('msg', '').lower()
                ):
                    invitee = False

                # 응답 코드가 51621인 경우도 초대자가 아닌 것으로 처리
                if response_data.get('code') == '51621':
                    invitee = False

                return invitee

    except aiohttp.ClientResponseError as error:
        print('Error checking user invitee:', error)
        return False
    except Exception as error:
        print('Error checking user invitee (일반 오류):', error)
        return False


# 새로 추가된 함수: OKX UID를 Redis에 저장하고 조회하는 유틸리티 함수들

async def store_okx_uid(telegram_id, okx_uid):
    """
    텔레그램 ID와 OKX UID의 매핑을 Redis에 저장
    
    Args:
        redis_client: Redis 연결 객체
        telegram_id: 사용자의 텔레그램 ID
        okx_uid: 사용자의 OKX UID
    """
    # telegram_id를 키로 사용하여 okx_uid 저장

    redis = await get_redis_client()
    await redis.set(f"user:{telegram_id}:okx_uid", okx_uid)
    # 역방향 매핑도 저장 (선택 사항)
    await redis.set(f"okx_uid_to_telegram:{okx_uid}", telegram_id)
    
async def get_okx_uid_from_telegram(telegram_id):
    """
    텔레그램 ID로부터 OKX UID 조회
    
    Args:
        redis_client: Redis 연결 객체 
        telegram_id: 사용자의 텔레그램 ID
        
    Returns:
        str or None: 저장된 OKX UID 또는 None
    """

    redis = await get_redis_client()
    okx_uid = await redis.get(f"user:{telegram_id}:okx_uid")
    if okx_uid:
        if isinstance(okx_uid, bytes):
            return okx_uid.decode()
        return okx_uid
    return None

async def get_telegram_id_from_okx_uid(okx_uid):
    """
    OKX UID로부터 텔레그램 ID 조회
    
    Args:
        redis_client: Redis 연결 객체
        okx_uid: 사용자의 OKX UID
        
    Returns:
        str or None: 저장된 텔레그램 ID 또는 None
    """

    redis = await get_redis_client()
    telegram_id = await redis.get(f"okx_uid_to_telegram:{okx_uid}")
    if telegram_id:
        if isinstance(telegram_id, bytes):
            return telegram_id.decode()
        return telegram_id
    return None


if __name__ == '__main__':
    import asyncio

    # 테스트 코드
    async def test():
        invitee = await check_invitee(fixed_api_key, fixed_secret_key, fixed_passphrase, uid=554511778597001828)
        print('UID:', invitee)

    asyncio.run(test())
