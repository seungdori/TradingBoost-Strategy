#!/usr/bin/env python3
"""OKX API 키 및 계정 설정 검증 스크립트"""

import asyncio
import sys
from datetime import datetime
from shared.database.redis_helper import get_redis_client
from HYPERRSI.src.api.dependencies import get_user_api_keys
import ccxt.async_support as ccxt

async def verify_api_and_account(user_id: str = None):
    """API 키와 계정 설정을 검증합니다."""

    print("=" * 80)
    print("🔍 OKX API 키 및 계정 설정 검증")
    print("=" * 80)

    redis = await get_redis_client()

    # 사용자 ID 확인
    if not user_id:
        user_id = "587662504768345929"  # 기본값

    print(f"\n👤 사용자 ID: {user_id}")

    try:
        # API 키 가져오기
        api_keys = await get_user_api_keys(user_id)

        print("\n" + "=" * 80)
        print("🔑 1. API 키 정보")
        print("-" * 80)
        print(f"   API Key: {api_keys['api_key'][:8]}...{api_keys['api_key'][-4:]}")
        print(f"   Passphrase: {'*' * len(api_keys['passphrase'])}")

        # OKX exchange 객체 생성
        exchange = ccxt.okx({
            'apiKey': api_keys['api_key'],
            'secret': api_keys['api_secret'],
            'password': api_keys['passphrase'],
            'enableRateLimit': True,
        })

        print("\n" + "=" * 80)
        print("👤 2. 계정 정보 확인")
        print("-" * 80)

        # 계정 정보 조회
        try:
            account_info = await exchange.private_get_account_config()
            data = account_info.get('data', [])

            if data:
                config = data[0]
                print(f"   UID: {config.get('uid', 'N/A')}")
                print(f"   계정 레벨: {config.get('acctLv', 'N/A')}")
                print(f"   메인 UID: {config.get('mainUid', 'N/A')}")
                print(f"   레벨: {config.get('level', 'N/A')}")
                print(f"   포지션 모드: {config.get('posMode', 'N/A')}")
                print(f"   자동 대출: {config.get('autoLoan', 'N/A')}")

                # 계정 레벨 설명
                acct_lv = config.get('acctLv', '')
                if acct_lv == '1':
                    print(f"   계정 타입: Simple (단순 모드)")
                elif acct_lv == '2':
                    print(f"   계정 타입: Single-currency margin (단일 통화 마진)")
                elif acct_lv == '3':
                    print(f"   계정 타입: Multi-currency margin (다중 통화 마진)")
                elif acct_lv == '4':
                    print(f"   계정 타입: Portfolio margin (포트폴리오 마진)")

                # 서브 계정 여부 확인
                main_uid = config.get('mainUid', '')
                uid = config.get('uid', '')
                if main_uid and main_uid != uid:
                    print(f"   ⚠️  서브 계정입니다! 메인 계정 UID: {main_uid}")

        except Exception as e:
            print(f"   ❌ 계정 정보 조회 실패: {str(e)}")

        print("\n" + "=" * 80)
        print("💰 3. 모든 계좌 타입별 잔고 확인")
        print("-" * 80)

        # 1. Unified Account (통합 계정) 확인
        print("\n📊 Unified Account 잔고:")
        try:
            # defaultType을 spot으로 변경하여 통합 계정 조회
            exchange.options['defaultType'] = 'spot'
            balance = await exchange.fetch_balance()

            if 'USDT' in balance and balance['USDT']['total'] > 0:
                print(f"   USDT: {balance['USDT']['total']:,.2f}")
                print(f"      사용 가능: {balance['USDT']['free']:,.2f}")
                print(f"      사용 중: {balance['USDT']['used']:,.2f}")

            # 다른 자산도 확인
            for asset, info in balance.items():
                if asset not in ['info', 'free', 'used', 'total', 'USDT']:
                    if isinstance(info, dict) and info.get('total', 0) > 0:
                        print(f"   {asset}: {info['total']:,.4f}")

        except Exception as e:
            print(f"   조회 실패: {str(e)}")

        # 2. Trading Account (거래 계좌) - 다른 방법으로 조회
        print("\n💼 Trading Account (다른 API):")
        try:
            # v5 API 사용
            trading_balance = await exchange.private_get_account_balance({'ccy': 'USDT'})
            data = trading_balance.get('data', [])

            if data:
                for account in data:
                    total_eq = float(account.get('totalEq', 0))
                    details = account.get('details', [])

                    print(f"   총 자산: ${total_eq:,.2f}")

                    for detail in details:
                        if detail.get('ccy') == 'USDT':
                            print(f"   USDT:")
                            print(f"      현금 잔고: {float(detail.get('cashBal', 0)):,.2f}")
                            print(f"      사용 가능: {float(detail.get('availBal', 0)):,.2f}")
                            print(f"      자산: {float(detail.get('eq', 0)):,.2f}")

        except Exception as e:
            print(f"   조회 실패: {str(e)}")

        # 3. Funding Account 재확인
        print("\n💳 Funding Account:")
        try:
            funding = await exchange.private_get_asset_balances({'ccy': 'USDT'})
            data = funding.get('data', [])

            if data:
                for asset in data:
                    if asset.get('ccy') == 'USDT':
                        bal = float(asset.get('bal', 0))
                        avail = float(asset.get('availBal', 0))
                        print(f"   USDT: {bal:,.2f}")
                        print(f"      사용 가능: {avail:,.2f}")
            else:
                print(f"   자산 없음")

        except Exception as e:
            print(f"   조회 실패: {str(e)}")

        print("\n" + "=" * 80)
        print("🔧 4. API 권한 확인")
        print("-" * 80)

        # API 권한 테스트
        try:
            # 읽기 권한 테스트
            await exchange.fetch_ticker('BTC/USDT:USDT')
            print(f"   ✅ 읽기 권한: 정상")
        except:
            print(f"   ❌ 읽기 권한: 실패")

        try:
            # 거래 권한 테스트 (실제 주문은 하지 않음)
            markets = await exchange.fetch_markets()
            print(f"   ✅ 마켓 정보 조회: 정상")
        except:
            print(f"   ❌ 마켓 정보 조회: 실패")

        print("\n" + "=" * 80)
        print("💡 5. 가능한 문제와 해결 방법")
        print("-" * 80)

        print("\n1. **계정 모드 확인**:")
        print("   OKX 웹/앱 → Assets → 우측 상단 ⚙️ → Account mode")
        print("   - Simple mode: 기본 거래 모드")
        print("   - Single-currency margin: 단일 통화 마진")
        print("   - Multi-currency margin: 다중 통화 마진 (권장)")
        print("   - Portfolio margin: 포트폴리오 마진")

        print("\n2. **자금 위치 확인**:")
        print("   OKX 웹/앱 → Assets에서 자금이 어디에 있는지 확인")
        print("   - Funding account → Trading account 이체 필요")
        print("   - 이체: Transfer 버튼 클릭")

        print("\n3. **API 키 권한 확인**:")
        print("   OKX 웹/앱 → Profile → API")
        print("   필요 권한:")
        print("   - Read (읽기)")
        print("   - Trade (거래)")
        print("   - 필요시: Transfer (이체)")

        print("\n4. **서브 계정 문제**:")
        print("   메인 계정의 API 키를 사용 중인지 확인")

        await exchange.close()

    except Exception as e:
        print(f"\n❌ 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("✅ 검증 완료")
    print("=" * 80)

if __name__ == "__main__":
    user_id = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(verify_api_and_account(user_id))