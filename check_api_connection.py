#!/usr/bin/env python3
"""메인 계정의 API 키 설정 및 실제 잔고 확인"""

import asyncio
import ccxt.async_support as ccxt
from shared.database.redis_helper import get_redis_client
import os
from dotenv import load_dotenv

load_dotenv()

async def check_api_and_balance():
    """API 키 설정 상태 확인 및 실제 잔고 조회"""

    redis = await get_redis_client()
    main_uid = "586156710277369942"

    print("=" * 60)
    print("🔍 메인 계정 API 연결 확인")
    print("=" * 60)
    print(f"UID: {main_uid}")
    print("-" * 60)

    # 1. Redis에서 API 키 확인
    api_keys_1 = await redis.hgetall(f"user:{main_uid}:api_keys")
    api_keys_2 = await redis.hgetall(f"user:{main_uid}:api:keys")

    print("\n📋 Redis API 키 상태:")
    if api_keys_1:
        print(f"  api_keys 키 존재: {len(api_keys_1)} 필드")
        for key, value in api_keys_1.items():
            key_str = key.decode() if isinstance(key, bytes) else key
            value_str = value.decode() if isinstance(value, bytes) else value
            # 민감한 정보는 일부만 표시
            if key_str in ['api_key', 'secret_key', 'passphrase']:
                display_value = value_str[:8] + "..." if len(value_str) > 8 else value_str
                print(f"    - {key_str}: {display_value}")
            else:
                print(f"    - {key_str}: {value_str}")
    else:
        print("  ❌ api_keys 키 없음")

    if api_keys_2:
        print(f"  api:keys 키 존재: {len(api_keys_2)} 필드")
    else:
        print("  ❌ api:keys 키 없음")

    # 2. 환경 변수에서 API 키 확인
    print("\n📋 환경 변수 API 키 상태:")
    env_api_key = os.getenv("OKX_API_KEY")
    env_secret = os.getenv("OKX_SECRET_KEY")
    env_passphrase = os.getenv("OKX_PASSPHRASE")

    if env_api_key:
        print(f"  ✅ OKX_API_KEY: {env_api_key[:8]}...")
    else:
        print("  ❌ OKX_API_KEY 없음")

    if env_secret:
        print(f"  ✅ OKX_SECRET_KEY: 설정됨")
    else:
        print("  ❌ OKX_SECRET_KEY 없음")

    if env_passphrase:
        print(f"  ✅ OKX_PASSPHRASE: 설정됨")
    else:
        print("  ❌ OKX_PASSPHRASE 없음")

    # 3. 실제 OKX API 연결 테스트
    print("\n🔌 OKX API 연결 테스트:")

    # API 키 결정 (Redis > 환경 변수)
    if api_keys_1 or api_keys_2:
        api_keys = api_keys_1 if api_keys_1 else api_keys_2
        api_key = api_keys.get(b'api_key', api_keys.get('api_key', b'')).decode() if isinstance(api_keys.get(b'api_key', api_keys.get('api_key', b'')), bytes) else api_keys.get('api_key', '')
        secret_key = api_keys.get(b'secret_key', api_keys.get('secret_key', b'')).decode() if isinstance(api_keys.get(b'secret_key', api_keys.get('secret_key', b'')), bytes) else api_keys.get('secret_key', '')
        passphrase = api_keys.get(b'passphrase', api_keys.get('passphrase', b'')).decode() if isinstance(api_keys.get(b'passphrase', api_keys.get('passphrase', b'')), bytes) else api_keys.get('passphrase', '')
        print("  사용: Redis에 저장된 API 키")
    elif env_api_key and env_secret and env_passphrase:
        api_key = env_api_key
        secret_key = env_secret
        passphrase = env_passphrase
        print("  사용: 환경 변수 API 키")
    else:
        print("  ❌ API 키가 설정되지 않음")
        return

    # OKX 연결
    try:
        exchange = ccxt.okx({
            'apiKey': api_key,
            'secret': secret_key,
            'password': passphrase,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # 무기한 선물
            }
        })

        # 계정 정보 조회
        print("\n📊 계정 잔고 조회:")
        balance = await exchange.fetch_balance()

        # USDT 잔고 확인
        usdt_total = balance.get('USDT', {}).get('total', 0)
        usdt_free = balance.get('USDT', {}).get('free', 0)
        usdt_used = balance.get('USDT', {}).get('used', 0)

        print(f"  💰 USDT 잔고:")
        print(f"     총 잔고: {usdt_total:.2f} USDT")
        print(f"     사용 가능: {usdt_free:.2f} USDT")
        print(f"     사용 중: {usdt_used:.2f} USDT")

        # 계정 정보 확인
        print("\n📊 계정 정보:")
        account_info = await exchange.private_get_account_config()
        account_data = account_info.get('data', [])
        if account_data:
            acc = account_data[0]
            print(f"  계정 UID: {acc.get('uid', 'N/A')}")
            print(f"  계정 레벨: {acc.get('level', 'N/A')}")
            print(f"  계정 타입: {acc.get('acctLv', 'N/A')}")

            # UID가 메인 계정과 일치하는지 확인
            if acc.get('uid') != main_uid:
                print(f"\n⚠️  경고: API 키의 UID({acc.get('uid')})가 메인 계정 UID({main_uid})와 다릅니다!")
                print("  → API 키가 다른 계정의 것일 수 있습니다.")

        await exchange.close()

    except Exception as e:
        print(f"  ❌ API 연결 실패: {str(e)}")
        if 'Invalid API-Key' in str(e):
            print("  → API 키가 잘못되었습니다.")
        elif 'Invalid Sign' in str(e):
            print("  → Secret Key 또는 Passphrase가 잘못되었습니다.")
        elif 'Permission denied' in str(e):
            print("  → API 키 권한이 부족합니다. 거래 권한을 확인하세요.")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(check_api_and_balance())