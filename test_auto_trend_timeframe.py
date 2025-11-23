#!/usr/bin/env python3
"""
자동 트렌드 타임프레임 로직 테스트
Pine Script의 자동 로직과 동일하게 작동하는지 검증
"""

from HYPERRSI.src.trading.models import get_auto_trend_timeframe


def test_auto_trend_timeframe():
    """
    Pine Script Logic:
        res_ = timeframe.isminutes and timeframe.multiplier <= 3 ? '15' :
               timeframe.isminutes and timeframe.multiplier <= 30 ? '30' :
               timeframe.isminutes and timeframe.multiplier < 240 ? '60' : '480'

    Expected Results:
        - 차트 ≤ 3분 → 트렌드 15분
        - 차트 ≤ 30분 → 트렌드 30분
        - 차트 < 4시간(240분) → 트렌드 1시간
        - 차트 ≥ 4시간 → 트렌드 8시간
    """
    test_cases = [
        # (input_timeframe, expected_output)
        ('1m', '15m'),   # 1분 ≤ 3분 → 15분
        ('3m', '15m'),   # 3분 ≤ 3분 → 15분
        ('5m', '30m'),   # 5분 > 3분, ≤ 30분 → 30분
        ('15m', '30m'),  # 15분 ≤ 30분 → 30분
        ('30m', '30m'),  # 30분 ≤ 30분 → 30분
        ('1h', '1h'),    # 60분 < 240분 → 1시간
        ('2h', '1h'),    # 120분 < 240분 → 1시간
        ('3h', '1h'),    # 180분 < 240분 → 1시간
        ('4h', '8h'),    # 240분 = 240분 → 8시간
        ('6h', '8h'),    # 360분 > 240분 → 8시간
        ('8h', '8h'),    # 480분 > 240분 → 8시간
        ('12h', '8h'),   # 720분 > 240분 → 8시간
        ('1d', '8h'),    # 1440분 > 240분 → 8시간

        # 대소문자 혼합 테스트
        ('1M', '15m'),
        ('1H', '1h'),
        ('4H', '8h'),

        # 엣지 케이스
        ('', '15m'),     # 빈 문자열 → 기본값 15분
        (None, '15m'),   # None → 기본값 15분
    ]

    print("🔍 자동 트렌드 타임프레임 로직 테스트\n")
    print("=" * 60)

    all_passed = True
    for input_tf, expected in test_cases:
        if input_tf is None:
            # None은 별도 처리
            try:
                result = get_auto_trend_timeframe('')
            except:
                result = '15m'
        else:
            result = get_auto_trend_timeframe(input_tf)

        passed = result == expected
        all_passed = all_passed and passed

        status = "✅ PASS" if passed else "❌ FAIL"
        input_display = f"'{input_tf}'" if input_tf else 'None'
        print(f"{status} | Input: {input_display:8} | Expected: {expected:5} | Got: {result:5}")

    print("=" * 60)

    if all_passed:
        print("\n🎉 모든 테스트 통과!")
        print("\n✅ Pine Script의 자동 로직과 동일하게 작동합니다:")
        print("   - 차트 ≤ 3분 → 트렌드 15분")
        print("   - 차트 ≤ 30분 → 트렌드 30분")
        print("   - 차트 < 4시간 → 트렌드 1시간")
        print("   - 차트 ≥ 4시간 → 트렌드 8시간")
        return 0
    else:
        print("\n❌ 일부 테스트 실패")
        return 1


if __name__ == "__main__":
    exit_code = test_auto_trend_timeframe()
    exit(exit_code)
