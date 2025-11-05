#!/usr/bin/env python
"""ATR 기반 DCA 백테스트 실행 스크립트"""
import json
import requests

# 백테스트 설정 로드
with open('backtest_3m_dca.json', 'r') as f:
    config = json.load(f)

print("🚀 ATR 기반 DCA 백테스트 실행 중...")
print(f"Entry Type: {config['strategy_params']['pyramiding_entry_type']}")
print(f"Entry Value: {config['strategy_params']['pyramiding_value']}")
print()

# API 호출
response = requests.post(
    'http://localhost:8013/backtest/run',
    json=config,
    headers={'Content-Type': 'application/json'}
)

if response.status_code == 200:
    data = response.json()

    # 결과 저장
    with open('backtest_result_atr_clean.json', 'w') as f:
        json.dump(data, f, indent=2)

    # 요약 출력
    print("✅ 백테스트 완료!")
    print(f"\n📊 기본 정보:")
    print(f"  • Entry Type: {data['strategy_params']['pyramiding_entry_type']}")
    print(f"  • Entry Value: {data['strategy_params']['pyramiding_value']}")
    print(f"  • 기간: {data['start_date']} ~ {data['end_date']}")
    print(f"  • 실행 시간: {data['execution_time_seconds']:.2f}초")

    print(f"\n💰 수익 성과:")
    print(f"  • 총 수익률: {data['total_return_percent']:.2f}%")
    print(f"  • 최대 낙폭: {data['max_drawdown_percent']:.2f}%")
    print(f"  • Sharpe Ratio: {data['sharpe_ratio']:.2f}")

    print(f"\n📈 거래 통계:")
    print(f"  • 총 거래: {data['total_trades']}회")
    print(f"  • 승률: {data['win_rate']:.2f}%")

    print(f"\n🎯 DCA 분석:")
    total_dca = 0
    for i, trade in enumerate(data['trades'], 1):
        entries = trade.get('additional_entries', [])
        dca_count = len(entries)
        total_dca += dca_count

        status = "✅ DCA 발동" if dca_count > 0 else "⚠️ DCA 미발동"
        print(f"  거래 #{i} ({trade['side'].upper()}): {status} - {dca_count}회 추가 진입")

        if dca_count > 0:
            for j, entry in enumerate(entries, 1):
                print(f"    └─ DCA #{j}: ${entry['price']:.2f} @ {entry['timestamp']}")

    print(f"\n📊 전체 DCA 발동: {total_dca}회")

    if total_dca == 0:
        print("\n⚠️ ATR 기반으로도 DCA가 발동하지 않았습니다!")
        print("   → ATR 조건 또는 기타 필터 조건을 재검토해야 합니다.")
    else:
        print(f"\n✅ ATR 기반 DCA가 성공적으로 발동했습니다!")

    print(f"\n📁 상세 결과: backtest_result_atr_clean.json")

else:
    print(f"❌ 백테스트 실패: HTTP {response.status_code}")
    print(response.text)
