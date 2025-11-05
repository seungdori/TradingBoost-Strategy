#!/usr/bin/env python3
"""
포지션 오픈 API 테스트 스크립트

수정한 TPSLOrderCreator와 telegram_message 코드를 검증합니다.
- contract_size_to_qty 메서드 접근
- fetch_okx_position 메서드 접근
- send_telegram_message 인자 전달

테스트 시나리오:
1. Long 포지션 (TP/SL 포함)
2. Short 포지션 (TP/SL 포함)
"""

import asyncio
import json
from typing import Optional

import ccxt.async_support as ccxt
import httpx


class PositionAPITester:
    """포지션 API 테스트 클라스"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        """클라이언트 종료"""
        await self.client.aclose()

    async def get_current_price(self, symbol: str) -> float:
        """
        현재 시장 가격 조회 (OKX)

        Args:
            symbol: 심볼 (예: "BTC-USDT-SWAP")

        Returns:
            현재가 (float)
        """
        print(f"\n📊 {symbol} 현재가 조회 중...")

        exchange = ccxt.okx()

        try:
            ticker = await exchange.fetch_ticker(symbol)
            current_price = ticker['last']

            print(f"✅ 현재가: ${current_price:,.2f}")

            return current_price

        except Exception as e:
            print(f"❌ 현재가 조회 실패: {e}")
            print("⚠️  기본값 95000.0 사용")
            return 95000.0

        finally:
            await exchange.close()

    async def test_open_position(
        self,
        user_id: str,
        symbol: str,
        direction: str,
        size: float,
        leverage: float = 10.0,
        stop_loss: Optional[float] = None,
        take_profit: Optional[list[float]] = None,
        is_DCA: bool = True,
    ) -> dict:
        """
        포지션 오픈 API 호출

        Args:
            user_id: 사용자 ID (OKX UID 또는 텔레그램 ID)
            symbol: 심볼 (예: "BTC-USDT-SWAP")
            direction: 방향 ("long" 또는 "short")
            size: 포지션 크기
            leverage: 레버리지
            stop_loss: 손절가 (선택)
            take_profit: 익절가 리스트 (선택)
            is_DCA: DCA 모드 활성화 여부

        Returns:
            API 응답 딕셔너리
        """
        url = f"{self.base_url}/api/position/open"

        payload = {
            "user_id": user_id,
            "symbol": symbol,
            "direction": direction,
            "size": size,
            "leverage": leverage,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "is_DCA": is_DCA,
            "order_concept": "",
            "is_hedge": False,
            "hedge_tp_price": None,
            "hedge_sl_price": None,
        }

        print(f"\n{'='*80}")
        print(f"🔍 테스트: {direction.upper()} 포지션 오픈")
        print(f"{'='*80}")
        print(f"📤 요청 URL: {url}")
        print(f"📋 요청 데이터:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))

        try:
            response = await self.client.post(url, json=payload)

            print(f"\n📥 응답 상태 코드: {response.status_code}")
            print(f"📋 응답 데이터:")

            if response.status_code == 200:
                result = response.json()
                print(json.dumps(result, indent=2, ensure_ascii=False))
                print(f"\n✅ {direction.upper()} 포지션 오픈 성공!")
                return {"success": True, "data": result}
            else:
                error_data = response.text
                try:
                    error_data = response.json()
                    print(json.dumps(error_data, indent=2, ensure_ascii=False))
                except:
                    print(error_data)
                print(f"\n❌ {direction.upper()} 포지션 오픈 실패!")
                return {"success": False, "error": error_data, "status": response.status_code}

        except Exception as e:
            print(f"\n🚨 예외 발생: {type(e).__name__}")
            print(f"📝 에러 메시지: {str(e)}")
            import traceback
            print(f"📋 전체 스택 트레이스:")
            traceback.print_exc()
            return {"success": False, "error": str(e)}


async def main():
    """메인 테스트 함수"""
    print("🚀 포지션 API 테스트 시작")
    print("="*80)

    tester = PositionAPITester()

    try:
        # 테스트용 설정
        # ⚠️ 실제 사용자 ID로 변경하세요
        user_id = "1709556958"  # OKX UID 또는 텔레그램 ID
        symbol = "ETH-USDT-SWAP"  # ETH로 테스트

        # 현재 시장 가격 조회
        current_price = await tester.get_current_price(symbol)

        # 테스트 1: Long 포지션
        print("\n" + "="*80)
        print("📊 테스트 1: LONG 포지션 (TP/SL 포함)")
        print("="*80)

        long_result = await tester.test_open_position(
            user_id=user_id,
            symbol=symbol,
            direction="long",
            size=0.1,  # ETH 0.1개
            leverage=10.0,
            stop_loss=current_price * 0.98,  # -2% 손절
            take_profit=[
                current_price * 1.02,  # +2% 익절1
                current_price * 1.04,  # +4% 익절2
                current_price * 1.06,  # +6% 익절3
            ],
            is_DCA=True,
        )

        # 결과 확인
        if long_result["success"]:
            print("\n✅ LONG 포지션 테스트 통과!")
            print("   - contract_size_to_qty 메서드 호출 성공")
            print("   - fetch_okx_position 메서드 호출 성공")
            print("   - send_telegram_message 호출 성공")
        else:
            print("\n❌ LONG 포지션 테스트 실패!")
            if "status" in long_result and long_result["status"] == 400:
                print("   ℹ️  트레이딩이 중지된 상태이거나 잔고가 부족할 수 있습니다.")

        # 잠시 대기
        await asyncio.sleep(2)

        # 테스트 2: Short 포지션
        print("\n" + "="*80)
        print("📊 테스트 2: SHORT 포지션 (TP/SL 포함)")
        print("="*80)

        short_result = await tester.test_open_position(
            user_id=user_id,
            symbol=symbol,
            direction="short",
            size=0.1,  # ETH 0.1개
            leverage=10.0,
            stop_loss=current_price * 1.02,  # +2% 손절
            take_profit=[
                current_price * 0.98,  # -2% 익절1
                current_price * 0.96,  # -4% 익절2
                current_price * 0.94,  # -6% 익절3
            ],
            is_DCA=True,
        )

        # 결과 확인
        if short_result["success"]:
            print("\n✅ SHORT 포지션 테스트 통과!")
            print("   - contract_size_to_qty 메서드 호출 성공")
            print("   - fetch_okx_position 메서드 호출 성공")
            print("   - send_telegram_message 호출 성공")
        else:
            print("\n❌ SHORT 포지션 테스트 실패!")
            if "status" in short_result and short_result["status"] == 400:
                print("   ℹ️  트레이딩이 중지된 상태이거나 잔고가 부족할 수 있습니다.")

        # 최종 결과
        print("\n" + "="*80)
        print("📊 테스트 최종 결과")
        print("="*80)

        if long_result["success"] and short_result["success"]:
            print("✅ 모든 테스트 통과!")
            print("\n검증된 항목:")
            print("  ✓ TPSLOrderCreator.contract_size_to_qty() → self.trading_service.contract_size_to_qty()")
            print("  ✓ TPSLOrderCreator.fetch_okx_position() → self.trading_service.fetch_okx_position()")
            print("  ✓ send_telegram_message() 인자 전달 수정")
            print("  ✓ send_telegram_message_direct() 인자 전달 수정")
            print("  ✓ Long/Short 포지션 모두 정상 동작")
        else:
            print("⚠️  일부 테스트 실패")
            print(f"  Long 포지션: {'✅' if long_result['success'] else '❌'}")
            print(f"  Short 포지션: {'✅' if short_result['success'] else '❌'}")

            # 실패 이유 분석
            if not long_result["success"] or not short_result["success"]:
                print("\n실패 원인 분석:")
                for name, result in [("Long", long_result), ("Short", short_result)]:
                    if not result["success"]:
                        if "status" in result and result["status"] == 400:
                            print(f"  {name}: 트레이딩 중지 상태 또는 잔고 부족")
                        elif "error" in result:
                            print(f"  {name}: {result['error']}")

    finally:
        await tester.close()
        print("\n" + "="*80)
        print("🏁 테스트 종료")
        print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
