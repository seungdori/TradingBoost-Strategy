"""
Pine Script vs Python trend_state 상세 디버깅 스크립트

CYCLE_Bull, CYCLE_Bear, BB_State_MTF 값까지 비교하여 불일치 원인을 파악합니다.

실행 방법:
    python BACKTEST/debug_trend_state_details.py BTC-USDT-SWAP 15m
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._trend import compute_trend_state
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


async def debug_trend_state_details(symbol: str, timeframe: str, lookback_days: int = 7):
    """
    Pine Script와 Python의 trend_state 계산 과정을 상세히 비교

    Args:
        symbol: 심볼 (예: BTC-USDT-SWAP)
        timeframe: 타임프레임 (예: 15m, 1h)
        lookback_days: 비교할 과거 데이터 일수 (디버깅용이므로 짧게)
    """
    logger.info("=" * 100)
    logger.info(f"Pine Script vs Python 상세 디버깅: {symbol} {timeframe}")
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

        # Pine Script가 계산한 값들 추출
        pinescript_data = []
        for c in candles:
            pinescript_data.append({
                "timestamp": c.timestamp,
                "close": c.close,
                "trend_state": c.trend_state if hasattr(c, 'trend_state') and c.trend_state is not None else 0,
                # Candle 객체는 대문자 속성 사용 (CYCLE_Bull, CYCLE_Bear, BB_State)
                "cycle_bull": c.CYCLE_Bull if hasattr(c, 'CYCLE_Bull') else None,
                "cycle_bear": c.CYCLE_Bear if hasattr(c, 'CYCLE_Bear') else None,
                "bb_state": c.BB_State if hasattr(c, 'BB_State') else None,
            })

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

        # Python으로 trend_state 계산
        result_candles = compute_trend_state(
            candles=candle_dicts,
            use_longer_trend=False,
            use_custom_length=False,
            current_timeframe_minutes=timeframe_minutes
        )

        python_data = []
        for c in result_candles:
            python_data.append({
                "timestamp": c.get("timestamp"),
                "close": c.get("close"),
                "trend_state": c.get("trend_state", 0),
                "cycle_bull": c.get("CYCLE_Bull", False),
                "cycle_bear": c.get("CYCLE_Bear", False),
                "bb_state_mtf": c.get("BB_State_MTF", 0),
            })

        logger.info(f"✅ Python trend_state 계산 완료")

        # 3. 상세 비교
        logger.info(f"\n3️⃣ 상세 비교 분석:")

        mismatches = []
        for i, (ps_data, py_data) in enumerate(zip(pinescript_data, python_data)):
            if ps_data["trend_state"] != py_data["trend_state"]:
                mismatch = {
                    "index": i,
                    "timestamp": ps_data["timestamp"],
                    "close": ps_data["close"],
                    "pine_trend_state": ps_data["trend_state"],
                    "py_trend_state": py_data["trend_state"],
                    "pine_cycle_bull": ps_data["cycle_bull"],
                    "py_cycle_bull": py_data["cycle_bull"],
                    "pine_cycle_bear": ps_data["cycle_bear"],
                    "py_cycle_bear": py_data["cycle_bear"],
                    "pine_bb_state": ps_data["bb_state"],
                    "py_bb_state_mtf": py_data["bb_state_mtf"],
                }
                mismatches.append(mismatch)

        total = len(pinescript_data)
        matches = total - len(mismatches)
        accuracy = (matches / total) * 100 if total > 0 else 0

        logger.info(f"일치율: {matches}/{total} ({accuracy:.2f}%)")

        if mismatches:
            logger.warning(f"\n⚠️ 불일치 발견: {len(mismatches)}개")

            # 상세 출력 (처음 20개)
            logger.info(f"\n처음 20개 불일치 상세:")
            logger.info(
                f"{'Idx':<6} {'Timestamp':<18} {'Close':<10} "
                f"{'Pine_TS':<8} {'Py_TS':<8} "
                f"{'Pine_Bull':<10} {'Py_Bull':<10} "
                f"{'Pine_Bear':<10} {'Py_Bear':<10} "
                f"{'Pine_BB':<8} {'Py_BB_MTF':<8}"
            )
            logger.info("-" * 130)

            for mm in mismatches[:20]:
                ts_str = mm["timestamp"].strftime("%Y-%m-%d %H:%M")
                logger.info(
                    f"{mm['index']:<6} {ts_str:<18} {mm['close']:<10.2f} "
                    f"{mm['pine_trend_state']:<8} {mm['py_trend_state']:<8} "
                    f"{str(mm['pine_cycle_bull']):<10} {str(mm['py_cycle_bull']):<10} "
                    f"{str(mm['pine_cycle_bear']):<10} {str(mm['py_cycle_bear']):<10} "
                    f"{str(mm['pine_bb_state']):<8} {str(mm['py_bb_state_mtf']):<8}"
                )

            # 패턴 분석
            logger.info(f"\n불일치 원인 분석:")

            # CYCLE_Bull 불일치
            cycle_bull_mismatch = sum(1 for mm in mismatches if mm['pine_cycle_bull'] != mm['py_cycle_bull'])
            logger.info(f"  - CYCLE_Bull 불일치: {cycle_bull_mismatch}개 ({cycle_bull_mismatch/len(mismatches)*100:.1f}%)")

            # CYCLE_Bear 불일치
            cycle_bear_mismatch = sum(1 for mm in mismatches if mm['pine_cycle_bear'] != mm['py_cycle_bear'])
            logger.info(f"  - CYCLE_Bear 불일치: {cycle_bear_mismatch}개 ({cycle_bear_mismatch/len(mismatches)*100:.1f}%)")

            # BB_State 불일치
            bb_state_mismatch = sum(1 for mm in mismatches if mm['pine_bb_state'] != mm['py_bb_state_mtf'])
            logger.info(f"  - BB_State 불일치: {bb_state_mismatch}개 ({bb_state_mismatch/len(mismatches)*100:.1f}%)")

            # 가장 흔한 불일치 패턴
            logger.info(f"\n가장 흔한 불일치 시나리오:")

            # Pine=2, Python=0 케이스 분석
            pine2_py0 = [mm for mm in mismatches if mm['pine_trend_state'] == 2 and mm['py_trend_state'] == 0]
            if pine2_py0:
                logger.info(f"\n  Pine=2 → Python=0 ({len(pine2_py0)}개):")
                bull_diff = sum(1 for mm in pine2_py0 if mm['pine_cycle_bull'] != mm['py_cycle_bull'])
                bb_diff = sum(1 for mm in pine2_py0 if mm['pine_bb_state'] != mm['py_bb_state_mtf'])
                logger.info(f"    - CYCLE_Bull 차이: {bull_diff}개")
                logger.info(f"    - BB_State 차이: {bb_diff}개")

            # Pine=-2, Python=0 케이스 분석
            pinem2_py0 = [mm for mm in mismatches if mm['pine_trend_state'] == -2 and mm['py_trend_state'] == 0]
            if pinem2_py0:
                logger.info(f"\n  Pine=-2 → Python=0 ({len(pinem2_py0)}개):")
                bear_diff = sum(1 for mm in pinem2_py0 if mm['pine_cycle_bear'] != mm['py_cycle_bear'])
                bb_diff = sum(1 for mm in pinem2_py0 if mm['pine_bb_state'] != mm['py_bb_state_mtf'])
                logger.info(f"    - CYCLE_Bear 차이: {bear_diff}개")
                logger.info(f"    - BB_State 차이: {bb_diff}개")

        else:
            logger.info(f"\n✅ 완벽한 일치! Pine Script와 Python 계산 결과가 100% 동일합니다.")

        logger.info("\n" + "=" * 100)
        return accuracy >= 95.0

    except Exception as e:
        logger.error(f"❌ 디버깅 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python BACKTEST/debug_trend_state_details.py <symbol> <timeframe> [lookback_days]")
        print("예시: python BACKTEST/debug_trend_state_details.py BTC-USDT-SWAP 15m 7")
        sys.exit(1)

    symbol = sys.argv[1]
    timeframe = sys.argv[2]
    lookback_days = int(sys.argv[3]) if len(sys.argv) > 3 else 7

    success = asyncio.run(debug_trend_state_details(symbol, timeframe, lookback_days))
    sys.exit(0 if success else 1)
