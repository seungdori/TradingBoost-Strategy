"""
BB_State 계산 과정을 상세히 로깅하는 디버그 스크립트

실행 방법:
    python BACKTEST/check_bb_state_calculation.py BTC-USDT-SWAP 15m
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state, _calc_bb_state
from shared.logging import get_logger

logger = get_logger(__name__)


def parse_timeframe_to_minutes(timeframe: str) -> int:
    """타임프레임 문자열을 분 단위로 변환"""
    timeframe = timeframe.lower()
    if timeframe.endswith('m'):
        return int(timeframe[:-1])
    elif timeframe.endswith('h'):
        return int(timeframe[:-1]) * 60
    elif timeframe.endswith('d'):
        return int(timeframe[:-1]) * 1440
    else:
        raise ValueError(f"지원하지 않는 타임프레임 형식: {timeframe}")


async def check_bb_state_calculation(symbol: str, timeframe: str, lookback_days: int = 90):
    """
    BB_State 계산 과정 디버깅

    Args:
        symbol: 심볼 (예: BTC-USDT-SWAP)
        timeframe: 타임프레임 (예: 15m)
        lookback_days: 테스트할 과거 데이터 일수 (기본: 90일)
    """
    logger.info("=" * 100)
    logger.info(f"BB_State 계산 과정 디버깅: {symbol} {timeframe}")
    logger.info("=" * 100)

    try:
        # 1. TimescaleDB 데이터 가져오기
        logger.info(f"\n1️⃣ TimescaleDB에서 {lookback_days}일치 데이터 로드 중...")
        provider = TimescaleProvider()

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=lookback_days)

        candles = await provider.get_candles(symbol, timeframe, start_date, end_date)

        if not candles:
            logger.error(f"❌ 데이터를 찾을 수 없습니다: {symbol} {timeframe}")
            return False

        logger.info(f"✅ {len(candles)}개 캔들 로드 완료")

        # 2. Candle 객체를 dict로 변환
        candle_dicts = []
        for c in candles:
            candle_dict = {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume
            }
            candle_dicts.append(candle_dict)

        # 3. BB_State 직접 계산
        logger.info(f"\n2️⃣ BB_State 직접 계산 중...")
        bb_state_list = _calc_bb_state(candle_dicts, length_bb=15, mult_bb=1.5, ma_length=100)

        # 4. Pine Script BB_State와 비교
        logger.info(f"\n3️⃣ Pine Script BB_State와 비교:")

        # 초기 100개 캔들 제외 (워밍업 기간)
        skip_initial = 100
        logger.info(f"워밍업 기간 제외: 처음 {skip_initial}개 캔들 스킵")

        mismatches = []
        for i, c in enumerate(candles):
            if i < skip_initial:
                continue

            pine_bb = c.BB_State if hasattr(c, 'BB_State') and c.BB_State is not None else None
            py_bb = bb_state_list[i]

            if pine_bb is not None and pine_bb != py_bb:
                mismatches.append({
                    "index": i,
                    "timestamp": c.timestamp,
                    "close": c.close,
                    "pine_bb": pine_bb,
                    "py_bb": py_bb
                })

        total = len(candles) - skip_initial
        matches = total - len(mismatches)
        accuracy = (matches / total) * 100 if total > 0 else 0

        logger.info(f"BB_State 일치율 (워밍업 제외): {matches}/{total} ({accuracy:.2f}%)")

        if mismatches:
            logger.warning(f"\n⚠️ BB_State 불일치: {len(mismatches)}개")

            # 처음 20개 출력
            logger.info(f"\n처음 20개 불일치:")
            logger.info(f"{'Idx':<6} {'Timestamp':<18} {'Close':<10} {'Pine_BB':<8} {'Py_BB':<8}")
            logger.info("-" * 60)

            for mm in mismatches[:20]:
                ts_str = mm["timestamp"].strftime("%Y-%m-%d %H:%M")
                logger.info(
                    f"{mm['index']:<6} {ts_str:<18} {mm['close']:<10.2f} "
                    f"{mm['pine_bb']:<8} {mm['py_bb']:<8}"
                )

            # 패턴 분석
            logger.info(f"\n불일치 패턴 분석:")
            pattern_counts = {}
            for mm in mismatches:
                pattern = f"Pine={mm['pine_bb']} → Python={mm['py_bb']}"
                pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

            for pattern, count in sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True):
                logger.info(f"  {pattern}: {count}회 ({(count/len(mismatches))*100:.1f}%)")

        else:
            logger.info(f"\n✅ BB_State 완벽 일치!")

        # 5. BB_State 분포 비교 (워밍업 제외)
        logger.info(f"\n4️⃣ BB_State 분포 비교 (워밍업 제외):")

        pine_bb_states = [c.BB_State if hasattr(c, 'BB_State') and c.BB_State is not None else 0 for c in candles[skip_initial:]]
        py_bb_states = bb_state_list[skip_initial:]

        logger.info(f"\nPine Script BB_State 분포:")
        logger.info(f"  - 상방 확장 (2): {pine_bb_states.count(2)} 개 ({pine_bb_states.count(2)/len(pine_bb_states)*100:.1f}%)")
        logger.info(f"  - 중립 (0): {pine_bb_states.count(0)} 개 ({pine_bb_states.count(0)/len(pine_bb_states)*100:.1f}%)")
        logger.info(f"  - 수축 (-1): {pine_bb_states.count(-1)} 개 ({pine_bb_states.count(-1)/len(pine_bb_states)*100:.1f}%)")
        logger.info(f"  - 하방 확장 (-2): {pine_bb_states.count(-2)} 개 ({pine_bb_states.count(-2)/len(pine_bb_states)*100:.1f}%)")

        logger.info(f"\nPython BB_State 분포:")
        logger.info(f"  - 상방 확장 (2): {py_bb_states.count(2)} 개 ({py_bb_states.count(2)/len(py_bb_states)*100:.1f}%)")
        logger.info(f"  - 중립 (0): {py_bb_states.count(0)} 개 ({py_bb_states.count(0)/len(py_bb_states)*100:.1f}%)")
        logger.info(f"  - 수축 (-1): {py_bb_states.count(-1)} 개 ({py_bb_states.count(-1)/len(py_bb_states)*100:.1f}%)")
        logger.info(f"  - 하방 확장 (-2): {py_bb_states.count(-2)} 개 ({py_bb_states.count(-2)/len(py_bb_states)*100:.1f}%)")

        logger.info("\n" + "=" * 100)
        return accuracy >= 95.0

    except Exception as e:
        logger.error(f"❌ 디버깅 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python BACKTEST/check_bb_state_calculation.py <symbol> <timeframe> [lookback_days]")
        print("예시: python BACKTEST/check_bb_state_calculation.py BTC-USDT-SWAP 15m 90")
        sys.exit(1)

    symbol = sys.argv[1]
    timeframe = sys.argv[2]
    lookback_days = int(sys.argv[3]) if len(sys.argv) > 3 else 90

    success = asyncio.run(check_bb_state_calculation(symbol, timeframe, lookback_days))
    sys.exit(0 if success else 1)
