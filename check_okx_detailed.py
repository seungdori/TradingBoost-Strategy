#!/usr/bin/env python3
"""OKX 계좌 상세 확인 스크립트 (Funding vs Trading)"""

import asyncio
import sys
import json
from datetime import datetime
from shared.database.redis_helper import get_redis_client
from HYPERRSI.src.api.dependencies import get_user_api_keys
import ccxt.async_support as ccxt

async def check_okx_accounts(user_id: str = None):
    """OKX의 모든 계좌 타입별 잔고를 확인합니다."""

    print("=" * 80)
    print("🏦 OKX 계좌 타입별 잔고 확인")
    print("=" * 80)

    redis = await get_redis_client()

    # 1. 사용자 ID 확인
    if not user_id:
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
            if len(users) == 1:
                user_id = list(users)[0]
            else:
                user_id = input("사용자 ID를 입력하세요: ")
        else:
            user_id = input("사용자 ID를 직접 입력하세요: ")

    print(f"\n👤 사용자 ID: {user_id}")

    try:
        # API 키 가져오기
        api_keys = await get_user_api_keys(user_id)

        # OKX exchange 객체 생성
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
        print("💳 1. Funding Account (입출금 계좌) - Account ID: 6")
        print("-" * 80)

        try:
            # Funding 계좌 조회
            funding_response = await exchange.private_get_asset_balances()
            funding_data = funding_response.get('data', [])

            funding_total = 0
            if funding_data:
                print("자산 목록:")
                for asset in funding_data:
                    ccy = asset.get('ccy', '')
                    bal = float(asset.get('bal', 0))
                    available = float(asset.get('availBal', 0))
                    frozen = float(asset.get('frozenBal', 0))

                    if bal > 0:
                        print(f"   {ccy}:")
                        print(f"      총액: {bal:,.4f}")
                        print(f"      사용 가능: {available:,.4f}")
                        print(f"      동결: {frozen:,.4f}")
                        if ccy == 'USDT':
                            funding_total = bal
            else:
                print("   ❌ 자산 없음")

        except Exception as e:
            print(f"   ❌ 조회 실패: {str(e)}")

        print("\n" + "=" * 80)
        print("💼 2. Trading Account (거래 계좌) - Account ID: 18")
        print("-" * 80)

        try:
            # Trading 계좌 조회
            trading_response = await exchange.private_get_account_balance()
            trading_data = trading_response.get('data', [])

            trading_total = 0
            if trading_data:
                for account in trading_data:
                    total_eq = float(account.get('totalEq', 0))
                    adj_eq = float(account.get('adjEq', 0))
                    imr = float(account.get('imr', 0))
                    mmr = float(account.get('mmr', 0))
                    margin_ratio = float(account.get('mgnRatio', 0))

                    print(f"계좌 요약:")
                    print(f"   총 자산: ${total_eq:,.2f}")
                    print(f"   조정 자산: ${adj_eq:,.2f}")
                    print(f"   초기 마진: ${imr:,.2f}")
                    print(f"   유지 마진: ${mmr:,.2f}")
                    print(f"   마진 비율: {margin_ratio:,.2f}")

                    details = account.get('details', [])
                    if details:
                        print(f"\n자산별 상세:")
                        for detail in details:
                            ccy = detail.get('ccy', '')
                            cash_bal = float(detail.get('cashBal', 0))
                            avail_bal = float(detail.get('availBal', 0))
                            frozen_bal = float(detail.get('frozenBal', 0))
                            eq = float(detail.get('eq', 0))
                            upl = float(detail.get('upl', 0))

                            if eq > 0 or cash_bal > 0:
                                print(f"   {ccy}:")
                                print(f"      현금 잔고: {cash_bal:,.4f}")
                                print(f"      사용 가능: {avail_bal:,.4f}")
                                print(f"      동결: {frozen_bal:,.4f}")
                                print(f"      자산: {eq:,.4f}")
                                print(f"      미실현 손익: {upl:,.4f}")
                                if ccy == 'USDT':
                                    trading_total = cash_bal
            else:
                print("   ❌ 계좌 정보 없음")

        except Exception as e:
            print(f"   ❌ 조회 실패: {str(e)}")

        print("\n" + "=" * 80)
        print("🔄 3. 자금 이체 필요성 분석")
        print("-" * 80)

        print(f"\n📊 잔고 요약:")
        print(f"   Funding 계좌 USDT: ${funding_total:,.2f}")
        print(f"   Trading 계좌 USDT: ${trading_total:,.2f}")

        if trading_total == 0 and funding_total > 0:
            print(f"\n⚠️  자금 이체가 필요합니다!")
            print(f"   Funding → Trading 계좌로 ${funding_total:,.2f} 이체 필요")
            print(f"\n   이체 방법:")
            print(f"   1. OKX 웹사이트 또는 앱에서:")
            print(f"      Assets → Transfer → Funding to Trading")
            print(f"   2. API를 통한 자동 이체 (아래 명령어):")
            print(f"      python transfer_to_trading.py {user_id} {funding_total}")
        elif trading_total > 0:
            print(f"\n✅ Trading 계좌에 충분한 자금이 있습니다.")
            print(f"   사용 가능 USDT: ${trading_total:,.2f}")
        else:
            print(f"\n❌ 모든 계좌에 USDT가 없습니다.")
            print(f"   OKX에 USDT를 입금해주세요.")

        print("\n" + "=" * 80)
        print("🔍 4. 마진 차단 상태")
        print("-" * 80)

        # Redis에서 margin_block 확인
        symbols = ['ETH-USDT-SWAP', 'BTC-USDT-SWAP']
        for symbol in symbols:
            block_key = f"margin_block:{user_id}:{symbol}"
            retry_key = f"margin_retry_count:{user_id}:{symbol}"

            is_blocked = await redis.get(block_key)
            retry_count = await redis.get(retry_key)

            if is_blocked or retry_count:
                print(f"\n{symbol}:")
                if is_blocked:
                    ttl = await redis.ttl(block_key)
                    print(f"   🔒 차단 상태: 활성 (남은 시간: {ttl}초)")
                if retry_count:
                    print(f"   🔄 재시도 횟수: {int(retry_count)}/15")

        if trading_total == 0 and (is_blocked or retry_count):
            print(f"\n💡 권장 사항:")
            print(f"   1. 먼저 자금을 Trading 계좌로 이체")
            print(f"   2. 그 다음 차단 해제: python check_margin_block.py --clear")

        await exchange.close()

    except Exception as e:
        print(f"\n❌ 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("✅ 계좌 확인 완료")
    print("=" * 80)

if __name__ == "__main__":
    user_id = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(check_okx_accounts(user_id))