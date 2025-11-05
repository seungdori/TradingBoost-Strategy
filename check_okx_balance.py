#!/usr/bin/env python3
"""OKX 계좌 잔고 전체 확인 스크립트"""

import asyncio
import sys
import json
from datetime import datetime
from shared.database.redis_helper import get_redis_client
from HYPERRSI.src.api.dependencies import get_user_api_keys
from HYPERRSI.src.trading.services.order_wrapper import OrderWrapper
from shared.utils import safe_float
import ccxt.async_support as ccxt

async def check_all_balances(user_id: str = None):
    """OKX의 모든 계좌 잔고를 확인합니다."""

    print("=" * 80)
    print("💰 OKX 전체 계좌 잔고 확인")
    print("=" * 80)

    redis = await get_redis_client()

    # 1. 사용자 ID 확인
    if not user_id:
        # Redis에서 모든 사용자 찾기
        pattern = "user:*:trading:status"
        cursor = 0
        users = set()

        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                parts = key_str.split(":")
                if len(parts) >= 2:
                    users.add(parts[1])
            if cursor == 0:
                break

        if users:
            print(f"\n📋 발견된 사용자 ID: {list(users)}")
            if len(users) == 1:
                user_id = list(users)[0]
                print(f"✅ 단일 사용자 선택: {user_id}")
            else:
                user_id = input("확인할 사용자 ID를 입력하세요: ")
        else:
            user_id = input("사용자 ID를 직접 입력하세요: ")

    print(f"\n👤 사용자 ID: {user_id}")

    try:
        # API 키 가져오기
        api_keys = await get_user_api_keys(user_id)

        # OKX exchange 객체 직접 생성 (CCXT 사용)
        exchange = ccxt.okx({
            'apiKey': api_keys['api_key'],
            'secret': api_keys['api_secret'],
            'password': api_keys['passphrase'],
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # 영구 선물
            }
        })

        print("\n" + "=" * 80)
        print("📊 1. 전체 잔고 조회 (fetch_balance)")
        print("-" * 80)

        # 전체 잔고 조회
        balance = await exchange.fetch_balance()

        # USDT 잔고 확인
        if 'USDT' in balance:
            usdt = balance['USDT']
            print(f"💵 USDT 잔고:")
            print(f"   총액 (total): {usdt.get('total', 0):,.2f} USDT")
            print(f"   사용 가능 (free): {usdt.get('free', 0):,.2f} USDT")
            print(f"   사용 중 (used): {usdt.get('used', 0):,.2f} USDT")
        else:
            print("⚠️  USDT 잔고 없음")

        # 다른 자산도 표시
        print(f"\n📈 기타 자산:")
        for asset, info in balance.items():
            if asset not in ['info', 'free', 'used', 'total', 'USDT'] and info.get('total', 0) > 0:
                print(f"   {asset}: {info.get('total', 0):,.4f}")

        print("\n" + "=" * 80)
        print("🏦 2. 계좌별 잔고 조회 (OKX API 직접 호출)")
        print("-" * 80)

        # Trading Account (18)
        try:
            trading_balance = await exchange.private_get_account_balance()
            details = trading_balance.get('data', [])

            if details:
                print(f"\n💼 Trading Account:")
                for detail in details:
                    balances = detail.get('details', [])
                    for bal in balances:
                        ccy = bal.get('ccy', '')
                        if ccy == 'USDT' or float(bal.get('cashBal', 0)) > 0:
                            print(f"   {ccy}:")
                            print(f"      현금 잔고: {float(bal.get('cashBal', 0)):,.2f}")
                            print(f"      이용 가능: {float(bal.get('availBal', 0)):,.2f}")
                            print(f"      동결: {float(bal.get('frozenBal', 0)):,.2f}")
                            print(f"      자산: {float(bal.get('eq', 0)):,.2f}")
                            print(f"      미실현 손익: {float(bal.get('upl', 0)):,.2f}")
        except Exception as e:
            print(f"❌ Trading Account 조회 실패: {str(e)}")

        # Funding Account (6)
        try:
            funding_balance = await exchange.private_get_asset_balances()
            funding_data = funding_balance.get('data', [])

            if funding_data:
                print(f"\n💳 Funding Account:")
                for asset in funding_data:
                    ccy = asset.get('ccy', '')
                    bal = float(asset.get('bal', 0))
                    if ccy == 'USDT' or bal > 0:
                        print(f"   {ccy}: {bal:,.2f}")
        except Exception as e:
            print(f"❌ Funding Account 조회 실패: {str(e)}")

        print("\n" + "=" * 80)
        print("⚙️  3. 계좌 설정 확인")
        print("-" * 80)

        # 계좌 설정 확인
        try:
            config = await exchange.private_get_account_config()
            config_data = config.get('data', [])

            if config_data:
                cfg = config_data[0]
                print(f"   계좌 레벨: {cfg.get('acctLv', 'N/A')}")
                print(f"   포지션 모드: {cfg.get('posMode', 'N/A')}")
                print(f"   자동 대출: {cfg.get('autoLoan', 'N/A')}")
                print(f"   그리스 문자 표시: {cfg.get('greeksType', 'N/A')}")
                print(f"   레벨: {cfg.get('level', 'N/A')}")
                print(f"   UID: {cfg.get('uid', 'N/A')}")
        except Exception as e:
            print(f"❌ 계좌 설정 조회 실패: {str(e)}")

        print("\n" + "=" * 80)
        print("📍 4. 현재 포지션 확인")
        print("-" * 80)

        # 포지션 확인
        try:
            positions = await exchange.fetch_positions()

            if positions:
                print(f"\n📊 열린 포지션:")
                for pos in positions:
                    if pos.get('contracts', 0) > 0:
                        print(f"   {pos.get('symbol')}:")
                        print(f"      계약 수: {pos.get('contracts')}")
                        print(f"      노출: ${pos.get('notional', 0):,.2f}")
                        print(f"      미실현 손익: ${pos.get('unrealizedPnl', 0):,.2f}")
                        print(f"      마진: ${pos.get('initialMargin', 0):,.2f}")
            else:
                print("   열린 포지션 없음")
        except Exception as e:
            print(f"❌ 포지션 조회 실패: {str(e)}")

        print("\n" + "=" * 80)
        print("🔄 5. 자금 이체 필요성 확인")
        print("-" * 80)

        # Trading 계좌 USDT가 0인지 확인
        need_transfer = False
        trading_usdt = 0
        funding_usdt = 0

        try:
            # Trading 계좌 USDT
            for detail in trading_balance.get('data', []):
                for bal in detail.get('details', []):
                    if bal.get('ccy') == 'USDT':
                        trading_usdt = float(bal.get('cashBal', 0))

            # Funding 계좌 USDT
            for asset in funding_balance.get('data', []):
                if asset.get('ccy') == 'USDT':
                    funding_usdt = float(asset.get('bal', 0))

            print(f"💵 Trading 계좌 USDT: {trading_usdt:,.2f}")
            print(f"💳 Funding 계좌 USDT: {funding_usdt:,.2f}")

            if trading_usdt == 0 and funding_usdt > 0:
                print(f"\n⚠️  자금 이체가 필요합니다!")
                print(f"   Funding → Trading 계좌로 {funding_usdt:,.2f} USDT 이체 필요")
                print(f"\n   이체 방법:")
                print(f"   1. OKX 웹/앱에서 직접 이체")
                print(f"   2. API를 통한 이체 (아래 명령어 실행):")
                print(f"      python transfer_funds.py {user_id} {funding_usdt}")
            elif trading_usdt > 0:
                print(f"\n✅ Trading 계좌에 충분한 자금이 있습니다.")
            else:
                print(f"\n⚠️  모든 계좌에 USDT가 없습니다. 입금이 필요합니다.")

        except Exception as e:
            print(f"❌ 자금 확인 중 오류: {str(e)}")

        await exchange.close()

    except Exception as e:
        print(f"\n❌ 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("✅ 잔고 확인 완료")
    print("=" * 80)

if __name__ == "__main__":
    user_id = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(check_all_balances(user_id))