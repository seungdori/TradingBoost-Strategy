#!/usr/bin/env python3
"""
프론트엔드 정확한 파라미터로 백테스트 검증
"""

import requests
import json
from datetime import datetime

# API 설정
API_URL = "http://localhost:8013/backtest/run"

# 프론트엔드와 정확히 동일한 요청
request_data = {
    "symbol": "BTC/USDT:USDT",
    "timeframe": "5m",
    "start_date": "2025-11-04T00:00:00Z",
    "end_date": "2025-11-24T23:59:59Z",
    "initial_capital": 10000,
    "maker_fee": 0.02,
    "taker_fee": 0.05,
    "data_source": "timescale",
    "strategy_name": "hyperrsi",
    "strategy_params": {
        "rsi_period": 14,
        "rsi_os": 30,
        "rsi_ob": 70,
        "direction": "both",
        "use_trend_filter": True,
        "ema_period": 7,
        "sma_period": 20,
        "entry_option": "rsi_trend",
        "require_trend_confirm": True,
        "use_trend_close": False,  # ← 주목: False!
        "use_tp1": True,
        "tp1_percent": 3,
        "tp1_close_percent": 30,
        "use_tp2": True,
        "tp2_percent": 4,
        "tp2_close_percent": 30,
        "use_tp3": True,
        "tp3_percent": 5,
        "tp3_close_percent": 40,
        "use_trailing_stop": True,
        "trailing_stop_percent": 0.5,
        "trailing_activation_percent": 2,
        "use_break_even": True,
        "use_break_even_tp2": True,
        "use_break_even_tp3": True,
        "use_dca": True,
        "dca_max_orders": 8,
        "dca_price_step_percent": 3,
        "dca_size_multiplier": 1,
        "rsi_entry_option": "돌파",
        "leverage": 10,
        "investment": 35,
        "stop_loss_enabled": False,
        "take_profit_enabled": False,
        "take_profit_percent": None,
        "pyramiding_enabled": True,
        "pyramiding_limit": 8,
        "pyramiding_entry_type": "atr",
        "pyramiding_value": 3,
        "use_rsi_with_pyramiding": True,
        "use_trend_logic": True,
        "trend_timeframe": "1H",
        "tp_option": "atr",
        "tp1_value": 3,
        "tp2_value": 4,
        "tp3_value": 5,
        "tp1_ratio": 30,
        "tp2_ratio": 30,
        "tp3_ratio": 40,
        "trailing_stop_active": True,
        "trailing_start_point": "tp2",
        "trailing_stop_offset_value": 0.5,
        "use_trailing_stop_value_with_tp2_tp3_difference": True,
        "use_dual_side_entry": True,
        "dual_side_entry_trigger": 2,
        "dual_side_entry_ratio_type": "percent_of_position",
        "dual_side_entry_ratio_value": 100,
        "dual_side_entry_tp_trigger_type": "existing_position",
        "close_main_on_hedge_tp": True,
        "use_dual_sl": False,
        "dual_side_pyramiding_limit": 2,
        "dual_side_trend_close": True  # ← 주목: True!
    }
}

print("=" * 80)
print("🔍 프론트엔드 파라미터 검증 테스트")
print("=" * 80)

# 주요 설정 출력
params = request_data["strategy_params"]
print("\n📋 주요 설정:")
print(f"  • Entry: {params['entry_option']} (trend_confirm: {params['require_trend_confirm']})")
print(f"  • Trend close (메인): {params['use_trend_close']}")
print(f"  • Dual-side enabled: {params['use_dual_side_entry']}")
print(f"  • Dual entry trigger: DCA {params['dual_side_entry_trigger']}회")
print(f"  • Dual size: 메인 포지션의 {params['dual_side_entry_ratio_value']}%")
print(f"  • Dual trend close (헤지): {params['dual_side_trend_close']}")
print(f"  • Close main on hedge TP: {params['close_main_on_hedge_tp']}")
print()

# ⚠️ 의도 검증
print("⚠️ 설정 의도 검증:")
print()
print("1. 메인 포지션:")
print(f"   - Trend close: {params['use_trend_close']} ← 트렌드 반전 시 청산 안 함")
print(f"   - Exit: TP1/TP2/TP3 또는 Trailing Stop으로만 청산")
print()
print("2. 헤지 포지션:")
print(f"   - Trend close: {params['dual_side_trend_close']} ← 트렌드 반전 시 청산")
print(f"   - Close main on TP: {params['close_main_on_hedge_tp']} ← 헤지 TP 시 메인도 청산")
print()

# 의도 분석
print("🤔 이 설정의 의미:")
print("   ✓ 메인: 트렌드 반전 무시, TP/Trailing만으로 청산")
print("   ✓ 헤지: 트렌드 반전 시 청산 (메인 보호)")
print("   ✓ 헤지 TP 도달 → 메인도 함께 청산 (수익 실현)")
print()
print("   → 헤지는 '트렌드 반전 감지기' 역할")
print("   → 헤지가 수익 나면 메인도 청산 (안전 수익)")
print()

# 백테스트 실행
print("=" * 80)
print("🚀 백테스트 실행 중...")
print("=" * 80)

try:
    response = requests.post(API_URL, json=request_data, timeout=300)
    response.raise_for_status()
    result = response.json()

    print("\n✅ 백테스트 완료!")
    print()
    print("=" * 80)
    print("📊 전체 결과")
    print("=" * 80)
    print(f"총 거래: {result['total_trades']}")
    print(f"승률: {result['win_rate']:.2f}%")
    print(f"최종 잔고: ${result['final_balance']:.2f}")
    print(f"수익률: {result['total_return']:.2f}%")
    print()

    # 거래 분석
    trades = result.get('trades', [])

    # 메인/헤지 분류
    main_trades = [t for t in trades if not t.get('is_dual_side_position', False)]
    hedge_trades = [t for t in trades if t.get('is_dual_side_position', False)]

    # 부분 청산 분류
    full_exits = [t for t in main_trades if not t.get('is_partial_exit', False)]
    partial_exits = [t for t in main_trades if t.get('is_partial_exit', False)]

    print("=" * 80)
    print("📊 거래 분류")
    print("=" * 80)
    print(f"메인 포지션: {len(main_trades)}")
    print(f"  - 전체 청산: {len(full_exits)}")
    print(f"  - 부분 청산: {len(partial_exits)}")
    print(f"헤지 포지션: {len(hedge_trades)}")
    print()

    # Exit reason 분석 (메인 포지션)
    if main_trades:
        exit_reasons = {}
        for trade in main_trades:
            reason = trade.get('exit_reason', 'unknown')
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

        print("=" * 80)
        print("📊 메인 포지션 청산 이유")
        print("=" * 80)
        for reason, count in sorted(exit_reasons.items()):
            print(f"  {reason}: {count}회")
        print()

    # Exit reason 분석 (헤지 포지션)
    if hedge_trades:
        hedge_exit_reasons = {}
        for trade in hedge_trades:
            reason = trade.get('exit_reason', 'unknown')
            hedge_exit_reasons[reason] = hedge_exit_reasons.get(reason, 0) + 1

        print("=" * 80)
        print("📊 헤지 포지션 청산 이유")
        print("=" * 80)
        for reason, count in sorted(hedge_exit_reasons.items()):
            print(f"  {reason}: {count}회")
        print()

    # DCA 분석
    dca_counts = [t.get('dca_count', 0) for t in trades if not t.get('is_partial_exit', False)]
    if dca_counts:
        print("=" * 80)
        print("📊 DCA 분석")
        print("=" * 80)
        print(f"평균 DCA 횟수: {sum(dca_counts) / len(dca_counts):.2f}")
        print(f"최대 DCA 횟수: {max(dca_counts)}")
        print(f"DCA >= 2인 거래: {sum(1 for c in dca_counts if c >= 2)}개")
        print()

    # 🔍 의도 검증: 헤지가 트렌드로 청산되었는가?
    trend_close_hedges = [t for t in hedge_trades if t.get('exit_reason') == 'trend_reversal']
    linked_exit_hedges = [t for t in hedge_trades if t.get('exit_reason') == 'linked_exit']

    print("=" * 80)
    print("🔍 의도 검증 결과")
    print("=" * 80)
    print(f"1. 헤지의 트렌드 청산: {len(trend_close_hedges)}회")
    if len(trend_close_hedges) > 0:
        print("   ✅ 헤지가 트렌드 반전을 감지하여 청산됨")
    else:
        print("   ⚠️ 헤지의 트렌드 청산이 없음 (트렌드 반전 없었거나 로직 미작동)")
    print()

    print(f"2. 헤지의 linked_exit: {len(linked_exit_hedges)}회")
    if len(linked_exit_hedges) > 0:
        print("   ✅ 메인 청산 시 헤지도 함께 청산됨")
    print()

    # 저장
    with open('frontend_exact_result.json', 'w') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print("💾 결과 저장: frontend_exact_result.json")

except requests.exceptions.RequestException as e:
    print(f"\n❌ API 요청 실패: {e}")
    if hasattr(e.response, 'text'):
        print(f"응답: {e.response.text}")
except Exception as e:
    print(f"\n❌ 오류 발생: {e}")
    import traceback
    traceback.print_exc()
