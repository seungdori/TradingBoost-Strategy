"""
Pine Script의 trend_state와 Python 계산 결과를 비교하는 스크립트

TimescaleDB에 저장된 Pine Script 계산 결과(candle_history.trend_state)와
Python shared/indicators/_trend.py의 compute_trend_state() 결과를 비교합니다.

실행 방법:
    python BACKTEST/compare_trend_state_with_pinescript.py BTC-USDT-SWAP 15m
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state
from shared.logging import get_logger

logger = get_logger(__name__)


def parse_timeframe_to_minutes(timeframe: str) -> int:
    """
    타임프레임 문자열을 분 단위로 변환

    Args:
        timeframe: "1m", "5m", "15m", "1h", "4h", "1d" 등

    Returns:
        분 단위 int
    """
    timeframe = timeframe.lower()
    if timeframe.endswith('m'):
        return int(timeframe[:-1])
    elif timeframe.endswith('h'):
        return int(timeframe[:-1]) * 60
    elif timeframe.endswith('d'):
        return int(timeframe[:-1]) * 1440
    else:
        raise ValueError(f"지원하지 않는 타임프레임 형식: {timeframe}")


async def compare_trend_state(symbol: str, timeframe: str, lookback_days: int = 30):
    """
    Pine Script와 Python의 trend_state 계산 결과를 비교

    Args:
        symbol: 심볼 (예: BTC-USDT-SWAP)
        timeframe: 타임프레임 (예: 15m, 1h)
        lookback_days: 비교할 과거 데이터 일수
    """
    logger.info("=" * 100)
    logger.info(f"Pine Script vs Python trend_state 비교: {symbol} {timeframe}")
    logger.info("=" * 100)

    try:
        # 1. TimescaleDB 데이터 가져오기
        logger.info(f"\n1️⃣ TimescaleDB에서 {lookback_days}일치 데이터 로드 중...")
        provider = TimescaleProvider()

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=lookback_days)

        candles = await provider.get_candles(symbol, timeframe, start_date, end_date)

        if not candles:
            logger.error(f"❌ 데이터를 찾을 수 없습니다: {symbol} {timeframe}")
            return False

        logger.info(f"✅ {len(candles)}개 캔들 로드 완료")

        # Pine Script가 계산한 trend_state 추출
        pinescript_trend_states = [c.trend_state if hasattr(c, 'trend_state') and c.trend_state is not None else 0 for c in candles]

        # 2. Python compute_trend_state() 실행
        logger.info(f"\n2️⃣ Python compute_trend_state() 실행 중...")

        # Candle 객체를 dict로 변환
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

        # 타임프레임을 분 단위로 변환
        timeframe_minutes = parse_timeframe_to_minutes(timeframe)

        # MTF 타임프레임 결정 (Pine Script 로직과 동일)
        # res_ (CYCLE용)
        if timeframe_minutes <= 3:
            res_minutes = 15
        elif timeframe_minutes <= 30:
            res_minutes = 30
        elif timeframe_minutes < 240:
            res_minutes = 60
        else:
            res_minutes = 480

        # bb_mtf (BB_State용)
        if timeframe_minutes <= 3:
            bb_mtf_minutes = 5
        elif timeframe_minutes <= 15:
            bb_mtf_minutes = 15
        else:
            bb_mtf_minutes = 60

        # MTF 데이터 수집 (진짜 데이터!)
        logger.info(f"   - CYCLE MTF: {res_minutes}분")
        logger.info(f"   - BB_State MTF: {bb_mtf_minutes}분")
        logger.info(f"   - CYCLE_2nd MTF: 240분")

        # res_ 타임프레임 변환
        res_tf = f"{res_minutes}m" if res_minutes < 60 else f"{res_minutes//60}h"
        bb_mtf_tf = f"{bb_mtf_minutes}m" if bb_mtf_minutes < 60 else f"{bb_mtf_minutes//60}h"

        candles_higher_tf_raw = await provider.get_candles(symbol, res_tf, start_date, end_date)
        candles_bb_mtf_raw = await provider.get_candles(symbol, bb_mtf_tf, start_date, end_date)
        candles_4h_raw = await provider.get_candles(symbol, "4h", start_date, end_date)

        # Candle 객체를 dict로 변환 (MTF)
        candles_higher_tf = [{"timestamp": c.timestamp, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume} for c in candles_higher_tf_raw]
        candles_bb_mtf = [{"timestamp": c.timestamp, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume} for c in candles_bb_mtf_raw]
        candles_4h = [{"timestamp": c.timestamp, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume} for c in candles_4h_raw]

        logger.info(f"   - {res_tf} 캔들: {len(candles_higher_tf)}개")
        logger.info(f"   - {bb_mtf_tf} 캔들: {len(candles_bb_mtf)}개")
        logger.info(f"   - 4h 캔들: {len(candles_4h)}개")

        # Python으로 trend_state 계산 (진짜 MTF 데이터 전달!)
        result_candles = compute_trend_state(
            candles=candle_dicts,
            use_longer_trend=False,
            use_custom_length=False,
            current_timeframe_minutes=timeframe_minutes,
            candles_higher_tf=candles_higher_tf,
            candles_bb_mtf=candles_bb_mtf,
            candles_4h=candles_4h
        )

        python_trend_states = [c.get("trend_state", 0) for c in result_candles]

        logger.info(f"✅ Python trend_state 계산 완료")

        # 3. 결과 비교
        logger.info(f"\n3️⃣ 결과 비교:")

        if len(pinescript_trend_states) != len(python_trend_states):
            logger.error(f"❌ 데이터 길이 불일치: Pine={len(pinescript_trend_states)}, Python={len(python_trend_states)}")
            return False

        # 일치율 계산
        matches = sum(1 for ps, py in zip(pinescript_trend_states, python_trend_states) if ps == py)
        total = len(pinescript_trend_states)
        accuracy = (matches / total) * 100 if total > 0 else 0

        logger.info(f"✅ 일치율: {matches}/{total} ({accuracy:.2f}%)")

        # 불일치 분석
        mismatches = []
        for i, (ps, py) in enumerate(zip(pinescript_trend_states, python_trend_states)):
            if ps != py:
                mismatches.append({
                    "index": i,
                    "timestamp": candles[i].timestamp,
                    "close": candles[i].close,
                    "pinescript": ps,
                    "python": py
                })

        if mismatches:
            logger.warning(f"\n⚠️ 불일치 발견: {len(mismatches)}개 ({(len(mismatches)/total)*100:.2f}%)")

            # 처음 10개 불일치 사례 출력
            logger.info(f"\n처음 10개 불일치 사례:")
            logger.info(f"{'Index':<8} {'Timestamp':<20} {'Close':<12} {'PineScript':<12} {'Python':<12}")
            logger.info("-" * 100)

            for mm in mismatches[:10]:
                timestamp_str = mm["timestamp"].strftime("%Y-%m-%d %H:%M")
                logger.info(
                    f"{mm['index']:<8} {timestamp_str:<20} {mm['close']:<12.2f} "
                    f"{mm['pinescript']:<12} {mm['python']:<12}"
                )

            # 불일치 패턴 분석
            logger.info(f"\n불일치 패턴 분석:")
            pattern_counts = {}
            for mm in mismatches:
                pattern = f"Pine={mm['pinescript']} → Python={mm['python']}"
                pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1

            for pattern, count in sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True):
                logger.info(f"  {pattern}: {count}회 ({(count/len(mismatches))*100:.1f}%)")

        else:
            logger.info(f"\n✅ 완벽한 일치! Pine Script와 Python 계산 결과가 100% 동일합니다.")

        # 4. 상태 분포 비교
        logger.info(f"\n4️⃣ 상태 분포 비교:")

        logger.info(f"\nPine Script trend_state 분포:")
        logger.info(f"  - 강한 상승 (2): {pinescript_trend_states.count(2)} 개 ({pinescript_trend_states.count(2)/total*100:.1f}%)")
        logger.info(f"  - 중립 (0): {pinescript_trend_states.count(0)} 개 ({pinescript_trend_states.count(0)/total*100:.1f}%)")
        logger.info(f"  - 강한 하락 (-2): {pinescript_trend_states.count(-2)} 개 ({pinescript_trend_states.count(-2)/total*100:.1f}%)")

        logger.info(f"\nPython trend_state 분포:")
        logger.info(f"  - 강한 상승 (2): {python_trend_states.count(2)} 개 ({python_trend_states.count(2)/total*100:.1f}%)")
        logger.info(f"  - 중립 (0): {python_trend_states.count(0)} 개 ({python_trend_states.count(0)/total*100:.1f}%)")
        logger.info(f"  - 강한 하락 (-2): {python_trend_states.count(-2)} 개 ({python_trend_states.count(-2)/total*100:.1f}%)")

        # 5. 최종 결과
        logger.info("\n" + "=" * 100)
        if accuracy >= 99.0:
            logger.info("✅ **검증 성공**: Pine Script와 Python 구현이 거의 완벽하게 일치합니다!")
        elif accuracy >= 95.0:
            logger.info("⚠️ **검증 주의**: 일치율이 높지만 일부 불일치가 있습니다. 미세 조정이 필요할 수 있습니다.")
        else:
            logger.error("❌ **검증 실패**: 일치율이 낮습니다. 로직 재검토가 필요합니다.")
        logger.info("=" * 100)

        return accuracy >= 95.0

    except Exception as e:
        logger.error(f"❌ 비교 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python BACKTEST/compare_trend_state_with_pinescript.py <symbol> <timeframe> [lookback_days]")
        print("예시: python BACKTEST/compare_trend_state_with_pinescript.py BTC-USDT-SWAP 15m 30")
        sys.exit(1)

    symbol = sys.argv[1]
    timeframe = sys.argv[2]
    lookback_days = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    success = asyncio.run(compare_trend_state(symbol, timeframe, lookback_days))
    sys.exit(0 if success else 1)
