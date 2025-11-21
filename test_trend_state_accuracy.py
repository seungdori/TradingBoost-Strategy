"""
Pine Script trend_state와 Python 구현 비교 테스트

이 스크립트는 Pine Script의 trend_state 계산 결과와
Python shared/indicators/_trend.py의 compute_trend_state() 결과를 비교합니다.

실행 방법:
    python test_trend_state_accuracy.py
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from shared.indicators._trend import compute_trend_state
from shared.logging import get_logger

logger = get_logger(__name__)


def create_sample_candles(num_candles=500):
    """
    테스트용 샘플 캔들 데이터 생성

    실제로는 TimescaleDB 또는 Redis에서 가져온 데이터를 사용해야 합니다.
    """
    candles = []
    base_price = 50000.0
    base_time = datetime.utcnow() - timedelta(minutes=num_candles)

    for i in range(num_candles):
        # 간단한 트렌드 시뮬레이션 (상승 -> 횡보 -> 하락)
        if i < num_candles // 3:
            # 상승 구간
            trend_factor = 1.0 + (i / num_candles) * 0.1
        elif i < 2 * num_candles // 3:
            # 횡보 구간
            trend_factor = 1.05
        else:
            # 하락 구간
            trend_factor = 1.05 - ((i - 2 * num_candles // 3) / num_candles) * 0.15

        price = base_price * trend_factor
        volatility = price * 0.01  # 1% 변동성

        candle = {
            "timestamp": base_time + timedelta(minutes=i),
            "open": price + (volatility * 0.5),
            "high": price + volatility,
            "low": price - volatility,
            "close": price,
            "volume": 1000.0 + (i % 100) * 10
        }
        candles.append(candle)

    return candles


async def test_trend_state_calculation():
    """
    trend_state 계산 테스트
    """
    logger.info("=" * 80)
    logger.info("Pine Script vs Python trend_state 비교 테스트")
    logger.info("=" * 80)

    # 1. 샘플 캔들 데이터 생성
    logger.info("\n1️⃣ 샘플 캔들 데이터 생성 중...")
    candles = create_sample_candles(num_candles=500)
    logger.info(f"✅ {len(candles)}개 캔들 생성 완료")

    # 2. Python compute_trend_state() 실행
    logger.info("\n2️⃣ Python compute_trend_state() 실행 중...")

    try:
        # 기본 설정 (use_longer_trend=False)
        result_candles = compute_trend_state(
            candles=candles.copy(),
            use_longer_trend=False,
            use_custom_length=False,
            current_timeframe_minutes=15  # 15분 타임프레임
        )

        # 결과 추출
        trend_states = [c.get("trend_state", 0) for c in result_candles]
        bb_states = [c.get("BB_State", 0) for c in result_candles]
        cycle_bulls = [c.get("CYCLE_Bull", False) for c in result_candles]
        cycle_bears = [c.get("CYCLE_Bear", False) for c in result_candles]

        logger.info(f"✅ trend_state 계산 완료")

        # 3. 결과 통계
        logger.info("\n3️⃣ 결과 통계:")
        logger.info(f"trend_state 분포:")
        logger.info(f"  - 강한 상승 (2): {trend_states.count(2)} 개 ({trend_states.count(2)/len(trend_states)*100:.1f}%)")
        logger.info(f"  - 중립 (0): {trend_states.count(0)} 개 ({trend_states.count(0)/len(trend_states)*100:.1f}%)")
        logger.info(f"  - 강한 하락 (-2): {trend_states.count(-2)} 개 ({trend_states.count(-2)/len(trend_states)*100:.1f}%)")

        logger.info(f"\nBB_State 분포:")
        logger.info(f"  - 상방 확장 (2): {bb_states.count(2)} 개 ({bb_states.count(2)/len(bb_states)*100:.1f}%)")
        logger.info(f"  - 중립 (0): {bb_states.count(0)} 개 ({bb_states.count(0)/len(bb_states)*100:.1f}%)")
        logger.info(f"  - 수축 (-1): {bb_states.count(-1)} 개 ({bb_states.count(-1)/len(bb_states)*100:.1f}%)")
        logger.info(f"  - 하방 확장 (-2): {bb_states.count(-2)} 개 ({bb_states.count(-2)/len(bb_states)*100:.1f}%)")

        logger.info(f"\nCYCLE 상태:")
        logger.info(f"  - CYCLE_Bull: {sum(cycle_bulls)} 개 ({sum(cycle_bulls)/len(cycle_bulls)*100:.1f}%)")
        logger.info(f"  - CYCLE_Bear: {sum(cycle_bears)} 개 ({sum(cycle_bears)/len(cycle_bears)*100:.1f}%)")

        # 4. 마지막 10개 캔들 상세 출력
        logger.info("\n4️⃣ 마지막 10개 캔들 상세:")
        logger.info(f"{'Index':<8} {'Timestamp':<20} {'Close':<10} {'CYCLE_Bull':<12} {'BB_State':<10} {'trend_state':<12}")
        logger.info("-" * 80)

        for i in range(max(0, len(result_candles) - 10), len(result_candles)):
            c = result_candles[i]
            timestamp_str = c["timestamp"].strftime("%Y-%m-%d %H:%M") if isinstance(c["timestamp"], datetime) else str(c["timestamp"])
            logger.info(
                f"{i:<8} {timestamp_str:<20} {c['close']:<10.2f} "
                f"{str(c.get('CYCLE_Bull', False)):<12} "
                f"{c.get('BB_State', 0):<10} "
                f"{c.get('trend_state', 0):<12}"
            )

        # 5. use_longer_trend=True로 재계산
        logger.info("\n5️⃣ use_longer_trend=True로 재계산 중...")
        result_candles_long = compute_trend_state(
            candles=candles.copy(),
            use_longer_trend=True,
            use_custom_length=False,
            current_timeframe_minutes=15
        )

        trend_states_long = [c.get("trend_state", 0) for c in result_candles_long]

        logger.info(f"✅ 장기 트렌드 계산 완료")
        logger.info(f"trend_state 분포 (use_longer_trend=True):")
        logger.info(f"  - 강한 상승 (2): {trend_states_long.count(2)} 개 ({trend_states_long.count(2)/len(trend_states_long)*100:.1f}%)")
        logger.info(f"  - 중립 (0): {trend_states_long.count(0)} 개 ({trend_states_long.count(0)/len(trend_states_long)*100:.1f}%)")
        logger.info(f"  - 강한 하락 (-2): {trend_states_long.count(-2)} 개 ({trend_states_long.count(-2)/len(trend_states_long)*100:.1f}%)")

        # 6. 검증 결과
        logger.info("\n" + "=" * 80)
        logger.info("✅ **테스트 완료**")
        logger.info("=" * 80)
        logger.info("\n📝 **다음 단계**:")
        logger.info("1. TimescaleDB에서 실제 candle_history 데이터를 가져와 테스트")
        logger.info("2. Pine Script가 계산한 trend_state 값과 비교 (candle_history.trend_state)")
        logger.info("3. 불일치하는 경우 원인 분석 및 디버깅")

        logger.info("\n🔧 **실제 데이터로 테스트하려면**:")
        logger.info("python -c \"from BACKTEST.check_trend_state import check_trend_state; check_trend_state('BTC-USDT-SWAP', '15m')\"")

    except Exception as e:
        logger.error(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = asyncio.run(test_trend_state_calculation())
    sys.exit(0 if success else 1)
