"""
백테스트 결과 저장 API 통합 테스트

이 스크립트는 백테스트 결과 저장/조회/삭제 API 엔드포인트를 테스트합니다.

실행 방법:
1. BACKTEST 서비스 시작: cd BACKTEST && python main.py
2. 별도 터미널에서: python BACKTEST/test_results_api.py

필수 조건:
- TimescaleDB가 실행 중이어야 함
- DCA 마이그레이션(003_add_dca_columns.sql)이 적용되어 있어야 함
- PostgreSQL에 백테스트 테이블들이 생성되어 있어야 함
"""

import asyncio
import httpx
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Any

# API 베이스 URL
BASE_URL = "http://localhost:8013"


def create_sample_backtest_result() -> Dict[str, Any]:
    """샘플 백테스트 결과 생성"""
    backtest_id = uuid4()
    # 고정된 테스트 사용자 ID 사용
    user_id = "11111111-1111-1111-1111-111111111111"
    now = datetime.now(timezone.utc)

    return {
        "id": str(backtest_id),
        "user_id": str(user_id),
        "symbol": "BTC-USDT-SWAP",
        "timeframe": "5m",
        "start_date": "2025-01-01T00:00:00Z",
        "end_date": "2025-01-15T23:59:59Z",
        "strategy_name": "hyperrsi",
        "strategy_params": {
            "entry_option": "rsi_trend",
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "leverage": 10,
            "investment": 100,
            "pyramiding_enabled": True,
            "pyramiding_limit": 3
        },
        "status": "completed",
        "started_at": now.isoformat(),
        "completed_at": (now).isoformat(),
        "execution_time_seconds": 120.5,
        "initial_balance": 10000.0,
        "final_balance": 11500.0,
        "total_return_percent": 15.0,
        "sharpe_ratio": 1.5,
        "max_drawdown_percent": -8.2,
        "total_trades": 25,
        "winning_trades": 18,
        "losing_trades": 7,
        "win_rate": 72.0,
        "profit_factor": 2.3,
        "avg_win": 120.0,
        "avg_loss": -65.0,
        "largest_win": 350.0,
        "largest_loss": -180.0,
        "total_fees_paid": 75.5,
        "detailed_metrics": {
            "volatility": 0.12,
            "sortino_ratio": 1.8,
            "calmar_ratio": 1.83,
            "recovery_factor": 2.1
        },
        "trades": [
            {
                "trade_number": 1,
                "side": "long",
                "entry_timestamp": "2025-01-02T10:30:00Z",
                "entry_price": 42000.0,
                "quantity": 0.024,
                "leverage": 10.0,
                "exit_timestamp": "2025-01-02T14:45:00Z",
                "exit_price": 42500.0,
                "exit_reason": "take_profit",
                "pnl": 120.0,
                "pnl_percent": 2.86,
                "entry_fee": 1.5,
                "exit_fee": 1.5,
                "dca_count": 0,
                "entry_history": [
                    {
                        "price": 42000.0,
                        "quantity": 0.024,
                        "investment": 100.8,
                        "timestamp": "2025-01-02T10:30:00Z",
                        "reason": "initial_entry",
                        "dca_count": 0
                    }
                ],
                "total_investment": 100.8,
                "is_partial_exit": False
            },
            {
                "trade_number": 2,
                "side": "long",
                "entry_timestamp": "2025-01-03T08:15:00Z",
                "entry_price": 41500.0,
                "quantity": 0.024,
                "leverage": 10.0,
                "exit_timestamp": "2025-01-03T16:20:00Z",
                "exit_price": 42100.0,
                "exit_reason": "take_profit",
                "pnl": 144.0,
                "pnl_percent": 3.47,
                "entry_fee": 1.75,
                "exit_fee": 1.75,
                "dca_count": 2,
                "entry_history": [
                    {
                        "price": 41500.0,
                        "quantity": 0.012,
                        "investment": 49.8,
                        "timestamp": "2025-01-03T08:15:00Z",
                        "reason": "initial_entry",
                        "dca_count": 0
                    },
                    {
                        "price": 41200.0,
                        "quantity": 0.006,
                        "investment": 24.72,
                        "timestamp": "2025-01-03T10:30:00Z",
                        "reason": "dca_entry",
                        "dca_count": 1
                    },
                    {
                        "price": 40900.0,
                        "quantity": 0.006,
                        "investment": 24.54,
                        "timestamp": "2025-01-03T12:45:00Z",
                        "reason": "dca_entry",
                        "dca_count": 2
                    }
                ],
                "total_investment": 99.06,
                "is_partial_exit": True,
                "tp_level": 1,
                "exit_ratio": 0.5,
                "remaining_quantity": 0.012,
                "tp1_price": 42100.0,
                "tp2_price": 42600.0,
                "tp3_price": 43100.0
            }
        ],
        "equity_curve": [
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "balance": 10000.0,
                "equity": 10000.0,
                "drawdown": 0.0
            },
            {
                "timestamp": "2025-01-02T14:45:00Z",
                "balance": 10120.0,
                "equity": 10120.0,
                "drawdown": 0.0
            },
            {
                "timestamp": "2025-01-03T16:20:00Z",
                "balance": 10264.0,
                "equity": 10264.0,
                "drawdown": 0.0
            },
            {
                "timestamp": "2025-01-15T23:59:59Z",
                "balance": 11500.0,
                "equity": 11500.0,
                "drawdown": -8.2
            }
        ]
    }


async def test_save_result(client: httpx.AsyncClient, result: Dict[str, Any]) -> str:
    """백테스트 결과 저장 테스트"""
    print("\n📝 테스트 1: 백테스트 결과 저장 (POST /api/results/save)")
    print("=" * 80)

    try:
        response = await client.post(
            f"{BASE_URL}/api/results/save",
            json=result
        )

        print(f"응답 상태 코드: {response.status_code}")

        if response.status_code == 201:
            data = response.json()
            print(f"✅ 저장 성공!")
            print(f"   - 백테스트 ID: {data['backtest_id']}")
            print(f"   - 메시지: {data['message']}")
            return data["backtest_id"]
        else:
            print(f"❌ 저장 실패: {response.text}")
            return None

    except Exception as e:
        print(f"❌ 예외 발생: {e}")
        return None


async def test_get_result(client: httpx.AsyncClient, backtest_id: str):
    """백테스트 결과 조회 테스트"""
    print("\n🔍 테스트 2: 백테스트 결과 조회 (GET /api/results/{id})")
    print("=" * 80)

    try:
        response = await client.get(f"{BASE_URL}/api/results/{backtest_id}")

        print(f"응답 상태 코드: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"✅ 조회 성공!")
            print(f"   - 심볼: {data['symbol']}")
            print(f"   - 전략: {data['strategy_name']}")
            print(f"   - 총 수익률: {data['total_return_percent']}%")
            print(f"   - 거래 수: {data['total_trades']}")
            print(f"   - 승률: {data['win_rate']}%")
            print(f"   - DCA 거래: {sum(1 for t in data.get('trades', []) if t.get('dca_count', 0) > 0)}개")
            return True
        else:
            print(f"❌ 조회 실패: {response.text}")
            return False

    except Exception as e:
        print(f"❌ 예외 발생: {e}")
        return False


async def test_list_results(client: httpx.AsyncClient, user_id: str):
    """사용자별 백테스트 목록 조회 테스트"""
    print("\n📋 테스트 3: 백테스트 목록 조회 (GET /api/results/list/{user_id})")
    print("=" * 80)

    try:
        response = await client.get(
            f"{BASE_URL}/api/results/list/{user_id}",
            params={"limit": 10, "offset": 0, "include_stats": True}
        )

        print(f"응답 상태 코드: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"✅ 목록 조회 성공!")
            print(f"   - 백테스트 개수: {len(data['backtests'])}")
            print(f"   - 페이지네이션: limit={data['pagination']['limit']}, offset={data['pagination']['offset']}")

            if "stats" in data:
                stats = data["stats"]
                print(f"   - 통계:")
                print(f"     · 총 백테스트: {stats.get('total_backtests', 0)}")
                print(f"     · 평균 수익률: {stats.get('avg_return', 0):.2f}%")
                print(f"     · 평균 승률: {stats.get('avg_win_rate', 0):.2f}%")

            return True
        else:
            print(f"❌ 목록 조회 실패: {response.text}")
            return False

    except Exception as e:
        print(f"❌ 예외 발생: {e}")
        return False


async def test_get_stats(client: httpx.AsyncClient, user_id: str):
    """사용자 통계 조회 테스트"""
    print("\n📊 테스트 4: 사용자 통계 조회 (GET /api/results/stats/{user_id})")
    print("=" * 80)

    try:
        response = await client.get(f"{BASE_URL}/api/results/stats/{user_id}")

        print(f"응답 상태 코드: {response.status_code}")

        if response.status_code == 200:
            stats = response.json()
            print(f"✅ 통계 조회 성공!")
            print(f"   - 총 백테스트: {stats.get('total_backtests', 0)}")
            print(f"   - 완료된 백테스트: {stats.get('completed_backtests', 0)}")
            print(f"   - 평균 수익률: {stats.get('avg_return', 0):.2f}%")
            print(f"   - 평균 샤프 비율: {stats.get('avg_sharpe', 0):.2f}")
            print(f"   - 평균 승률: {stats.get('avg_win_rate', 0):.2f}%")
            print(f"   - 총 거래 수: {stats.get('total_trades', 0)}")
            return True
        else:
            print(f"❌ 통계 조회 실패: {response.text}")
            return False

    except Exception as e:
        print(f"❌ 예외 발생: {e}")
        return False


async def test_delete_result(client: httpx.AsyncClient, backtest_id: str, user_id: str):
    """백테스트 결과 삭제 테스트"""
    print("\n🗑️  테스트 5: 백테스트 결과 삭제 (DELETE /api/results/{id})")
    print("=" * 80)

    try:
        response = await client.delete(
            f"{BASE_URL}/api/results/{backtest_id}",
            params={"user_id": user_id}
        )

        print(f"응답 상태 코드: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(f"✅ 삭제 성공!")
            print(f"   - 메시지: {data['message']}")
            return True
        else:
            print(f"❌ 삭제 실패: {response.text}")
            return False

    except Exception as e:
        print(f"❌ 예외 발생: {e}")
        return False


async def main():
    """메인 테스트 실행"""
    print("\n" + "=" * 80)
    print("백테스트 결과 저장 API 통합 테스트")
    print("=" * 80)

    # HTTP 클라이언트 생성
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. 샘플 데이터 생성
        sample_result = create_sample_backtest_result()
        user_id = sample_result["user_id"]

        # 2. 저장 테스트
        backtest_id = await test_save_result(client, sample_result)

        if not backtest_id:
            print("\n❌ 저장 테스트 실패로 인해 나머지 테스트를 건너뜁니다.")
            return

        # 3. 조회 테스트
        await test_get_result(client, backtest_id)

        # 4. 목록 조회 테스트
        await test_list_results(client, user_id)

        # 5. 통계 조회 테스트
        await test_get_stats(client, user_id)

        # 6. 삭제 테스트
        await test_delete_result(client, backtest_id, user_id)

        # 7. 삭제 후 조회 테스트 (404 확인)
        print("\n🔍 테스트 6: 삭제 후 조회 (404 확인)")
        print("=" * 80)
        response = await client.get(f"{BASE_URL}/api/results/{backtest_id}")
        if response.status_code == 404:
            print(f"✅ 삭제 확인 성공! (404 응답)")
        else:
            print(f"❌ 삭제 확인 실패: {response.status_code}")

    print("\n" + "=" * 80)
    print("테스트 완료!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
