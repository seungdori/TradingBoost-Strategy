"""
Pine Script vs Python BB_State_MTF 상세 진단 도구

중간 계산 값들을 출력하여 정확한 차이점 분석:
- BB_State (기본 타임프레임)
- BB_State_MTF (상위 타임프레임)
- CYCLE_Bull, CYCLE_Bear
- trend_state 최종 값
"""

import asyncio
from datetime import datetime, timedelta, timezone
from shared.indicators._trend import compute_trend_state
from shared.config import get_settings
from BACKTEST.data.okx_provider import OKXProvider


async def analyze_bb_state_mtf_detailed(symbol: str, timeframe: str, days: int = 7):
    """
    Pine Script와 Python의 중간 계산 값들을 상세히 비교

    Args:
        symbol: 거래쌍 (예: BTC-USDT-SWAP)
        timeframe: 타임프레임 (1m, 5m, 15m 등)
        days: 분석할 일수
    """
    print("=" * 80)
    print(f"BB_State_MTF 상세 진단 - {symbol} {timeframe}")
    print("=" * 80)

    # 1. 데이터 수집
    print("\n📊 1단계: 캔들 데이터 수집 중...")
    settings = get_settings()

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=days)

    # OKX Data Provider 사용
    okx_provider = OKXProvider()

    candles_raw = await okx_provider.get_candles(
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_time,
        end_date=end_time
    )

    # Candle 객체를 dict로 변환
    candles = [
        {
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        }
        for c in candles_raw
    ]

    print(f"✅ 총 {len(candles)}개 캔들 수집 완료")
    print(f"   기간: {candles[0]['timestamp']} ~ {candles[-1]['timestamp']}")

    # 2. 타임프레임 분석
    print("\n🔍 2단계: 타임프레임 분석")

    # Pine Script 로직: line 355
    # bb_mtf = timeframe.multiplier <= 3 and timeframe.isminutes ? '5' :
    #          timeframe.multiplier <= 15 and timeframe.isminutes ? '15' : '60'

    tf_minutes = {
        '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
        '1h': 60, '2h': 120, '4h': 240, '1d': 1440
    }

    current_tf = tf_minutes.get(timeframe, 1)

    # bb_mtf 결정 (Pine Script 로직)
    if current_tf <= 3:
        bb_mtf_str = '5m'
        bb_mtf_minutes = 5
    elif current_tf <= 15:
        bb_mtf_str = '15m'
        bb_mtf_minutes = 15
    else:
        bb_mtf_str = '60m'
        bb_mtf_minutes = 60

    print(f"   현재 타임프레임: {timeframe} ({current_tf}분)")
    print(f"   BB_State MTF: {bb_mtf_str} ({bb_mtf_minutes}분)")

    # 3. BB_State_MTF 캔들 수집
    print(f"\n📊 3단계: BB_State_MTF용 {bb_mtf_str} 캔들 수집 중...")

    candles_bb_mtf_raw = await okx_provider.get_candles(
        symbol=symbol,
        timeframe=bb_mtf_str,
        start_date=start_time,
        end_date=end_time
    )

    candles_bb_mtf = [
        {
            'timestamp': c.timestamp,
            'open': c.open,
            'high': c.high,
            'low': c.low,
            'close': c.close,
            'volume': c.volume
        }
        for c in candles_bb_mtf_raw
    ]

    print(f"✅ 총 {len(candles_bb_mtf)}개 BB_MTF 캔들 수집 완료")

    # 4. compute_trend_state 실행 (백테스트 모드)
    print("\n⚙️  4단계: trend_state 계산 중...")

    # 진짜 5분봉 데이터 전달 (리샘플링 아님!)
    result = compute_trend_state(
        candles,
        use_longer_trend=False,
        current_timeframe_minutes=current_tf,
        candles_bb_mtf=candles_bb_mtf,  # 진짜 5분봉 데이터 사용!
        is_confirmed_only=True  # 백테스트 모드
    )

    print(f"✅ {len(result)}개 캔들 계산 완료")

    # 5. 상세 분석: 마지막 50개 캔들
    print("\n" + "=" * 80)
    print("📊 상세 분석: 마지막 50개 캔들의 중간 계산 값")
    print("=" * 80)

    analysis_start = max(0, len(result) - 50)

    # 헤더
    print(f"\n{'Index':<8} {'Timestamp':<20} {'Close':>10} "
          f"{'BB_State':>10} {'BB_MTF':>10} {'CYCLE_B':>10} {'CYCLE_b':>10} "
          f"{'trend':>6}")
    print("-" * 100)

    # 통계 수집
    bb_state_counts = {-2: 0, -1: 0, 0: 0, 1: 0, 2: 0}
    bb_mtf_counts = {-2: 0, -1: 0, 0: 0, 1: 0, 2: 0}
    trend_state_counts = {-2: 0, 0: 0, 2: 0}

    for i in range(analysis_start, len(result)):
        candle = result[i]

        # 중간 계산 값들
        timestamp = candle.get('timestamp', 'N/A')
        close = candle.get('close', 0)
        bb_state = candle.get('BB_State', 0)
        bb_state_mtf = candle.get('BB_State_MTF', 0)
        cycle_bull = candle.get('CYCLE_Bull', False)
        cycle_bear = candle.get('CYCLE_Bear', False)
        trend_state = candle.get('trend_state', 0)

        # 통계 업데이트
        bb_state_counts[bb_state] = bb_state_counts.get(bb_state, 0) + 1
        bb_mtf_counts[bb_state_mtf] = bb_mtf_counts.get(bb_state_mtf, 0) + 1
        trend_state_counts[trend_state] = trend_state_counts.get(trend_state, 0) + 1

        # 출력
        cycle_bull_str = "Bull" if cycle_bull else "----"
        cycle_bear_str = "Bear" if cycle_bear else "----"

        print(f"{i:<8} {str(timestamp)[:19]:<20} {close:>10.2f} "
              f"{bb_state:>10} {bb_state_mtf:>10} "
              f"{cycle_bull_str:>10} {cycle_bear_str:>10} "
              f"{trend_state:>6}")

    # 6. 통계 요약
    print("\n" + "=" * 80)
    print("📊 통계 요약 (마지막 50개 캔들)")
    print("=" * 80)

    total = len(result) - analysis_start

    print("\n1️⃣  BB_State 분포:")
    for state in sorted(bb_state_counts.keys()):
        count = bb_state_counts[state]
        pct = count / total * 100 if total > 0 else 0
        print(f"   State {state:>2}: {count:>3}회 ({pct:>5.1f}%)")

    print("\n2️⃣  BB_State_MTF 분포:")
    for state in sorted(bb_mtf_counts.keys()):
        count = bb_mtf_counts[state]
        pct = count / total * 100 if total > 0 else 0
        print(f"   State {state:>2}: {count:>3}회 ({pct:>5.1f}%)")

    print("\n3️⃣  trend_state 분포:")
    for state in sorted(trend_state_counts.keys()):
        count = trend_state_counts[state]
        pct = count / total * 100 if total > 0 else 0
        state_name = {-2: "강한 하락", 0: "중립", 2: "강한 상승"}.get(state, "알 수 없음")
        print(f"   State {state:>2} ({state_name}): {count:>3}회 ({pct:>5.1f}%)")

    # 7. 의심 구간 찾기
    print("\n" + "=" * 80)
    print("🔍 의심 구간 찾기: BB_State_MTF가 트렌드에 영향을 준 시점")
    print("=" * 80)

    suspect_count = 0
    for i in range(analysis_start, len(result)):
        candle = result[i]

        bb_state_mtf = candle.get('BB_State_MTF', 0)
        trend_state = candle.get('trend_state', 0)
        cycle_bull = candle.get('CYCLE_Bull', False)
        cycle_bear = candle.get('CYCLE_Bear', False)

        # 의심 조건: BB_State_MTF=2 이고 trend_state=2 (강한 상승)
        # 또는 BB_State_MTF=-2 이고 trend_state=-2 (강한 하락)
        if (bb_state_mtf == 2 and trend_state == 2 and cycle_bull) or \
           (bb_state_mtf == -2 and trend_state == -2 and cycle_bear):
            suspect_count += 1
            print(f"   [{i}] {candle.get('timestamp', 'N/A')} → "
                  f"BB_MTF={bb_state_mtf}, trend={trend_state}, "
                  f"CYCLE_Bull={cycle_bull}, CYCLE_Bear={cycle_bear}")

    print(f"\n   총 {suspect_count}개 의심 구간 발견")

    print("\n" + "=" * 80)
    print("✅ 상세 진단 완료")
    print("=" * 80)

    # 8. 결론 및 권장사항
    print("\n💡 분석 결과:")
    print("   1. BB_State와 BB_State_MTF의 분포를 확인하세요")
    print("   2. CYCLE_Bull/Bear와 trend_state의 관계를 검증하세요")
    print("   3. 의심 구간의 중간 계산 값들을 Pine Script와 직접 비교하세요")
    print("\n🎯 다음 단계:")
    print("   - Pine Script에서 동일한 timestamp의 중간 값 출력")
    print("   - Python vs Pine Script 값 1:1 비교")
    print("   - 차이가 나는 첫 번째 지점 식별")

    # OKX provider 닫기
    await okx_provider.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("사용법: python debug_bb_state_mtf_detailed.py <symbol> <timeframe> [days]")
        print("예시: python debug_bb_state_mtf_detailed.py BTC-USDT-SWAP 1m 7")
        sys.exit(1)

    symbol = sys.argv[1]
    timeframe = sys.argv[2]
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 7

    asyncio.run(analyze_bb_state_mtf_detailed(symbol, timeframe, days))
