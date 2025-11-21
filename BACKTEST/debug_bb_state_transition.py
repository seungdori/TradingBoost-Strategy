"""
BB_State 전환 과정을 상세 로깅하는 디버그 스크립트

특정 불일치 케이스에서 BBW, BBR, buzz, squeeze 값을 모두 로깅합니다.

실행 방법:
    python BACKTEST/debug_bb_state_transition.py BTC-USDT-SWAP 15m
"""

import asyncio
import sys
import math
from datetime import datetime, timedelta
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._moving_averages import calc_sma
from shared.indicators._bollinger import calc_stddev
from shared.indicators._core import pivothigh, pivotlow, crossover, rising, falling
from shared.logging import get_logger

logger = get_logger(__name__)


async def debug_bb_state_transition(symbol: str, timeframe: str):
    """
    BB_State 전환 과정 상세 디버깅
    """
    logger.info("=" * 100)
    logger.info(f"BB_State 전환 과정 디버깅: {symbol} {timeframe}")
    logger.info("=" * 100)

    try:
        # 1. TimescaleDB 데이터 가져오기
        logger.info(f"\n1️⃣ TimescaleDB에서 30일치 데이터 로드 중...")
        provider = TimescaleProvider()

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)

        candles = await provider.get_candles(symbol, timeframe, start_date, end_date)

        if not candles:
            logger.error(f"❌ 데이터를 찾을 수 없습니다: {symbol} {timeframe}")
            return False

        logger.info(f"✅ {len(candles)}개 캔들 로드 완료")

        # 2. BBW 계산
        logger.info(f"\n2️⃣ BBW 계산 중...")

        closes = [c.close for c in candles]
        length_bb = 15
        mult_bb = 1.5

        basis_list = calc_sma(closes, length_bb)
        stdev_list = calc_stddev(closes, length_bb)

        bbw_list = []
        bbr_list = []
        for i in range(len(closes)):
            basis_val = basis_list[i]
            std_val = stdev_list[i]
            if basis_val is None or std_val is None or math.isnan(basis_val) or math.isnan(std_val):
                bbw_list.append(math.nan)
                bbr_list.append(math.nan)
            else:
                up = basis_val + mult_bb * std_val
                lo = basis_val - mult_bb * std_val
                if basis_val != 0:
                    bbw = (up - lo) * 10.0 / basis_val
                    bbw_list.append(bbw)
                    # BBR: (close - lower) / (upper - lower)
                    bbr = (closes[i] - lo) / (up - lo) if (up - lo) != 0 else 0.5
                    bbr_list.append(bbr)
                else:
                    bbw_list.append(math.nan)
                    bbr_list.append(math.nan)

        # 3. BBW MA
        ma_length = 100
        bbw_ma = calc_sma(bbw_list, ma_length)

        # 4. Pivot 계산
        logger.info(f"\n3️⃣ Pivot High/Low 계산 중...")
        pivot_left = 20
        pivot_right = 10
        ph_list = pivothigh(bbw_list, pivot_left, pivot_right)
        pl_list = pivotlow(bbw_list, pivot_left, pivot_right)

        # 5. Pivot 수집
        logger.info(f"\n4️⃣ Pivot 수집 중...")
        array_size = 50
        ph_array = []
        pl_array = []

        for i in range(len(closes)):
            bbw_val = bbw_list[i]
            ma_val = bbw_ma[i]

            if ma_val is None or math.isnan(ma_val) or math.isnan(bbw_val):
                continue

            if bbw_val > ma_val and ph_list[i] is not None:
                ph_array.append(ph_list[i])
                if len(ph_array) > array_size:
                    ph_array.pop(0)

            if bbw_val < ma_val and pl_list[i] is not None:
                pl_array.append(pl_list[i])
                if len(pl_array) > array_size:
                    pl_array.pop(0)

        # 6. 평균 계산
        if len(ph_array) > 0:
            ph_avg = sum(ph_array) / len(ph_array)
        else:
            ph_avg = max([b for b in bbw_list if not math.isnan(b)] + [5])

        if len(pl_array) > 0:
            pl_avg = sum(pl_array) / len(pl_array)
        else:
            pl_avg = min([b for b in bbw_list if not math.isnan(b)] + [5])

        # 7. buzz, squeeze 계산
        mult_plph = 0.7
        buzz = ph_avg * mult_plph
        squeeze = pl_avg * (1 / mult_plph)

        logger.info(f"\n5️⃣ 임계값:")
        logger.info(f"buzz: {buzz:.6f}")
        logger.info(f"squeeze: {squeeze:.6f}")

        # 8. BB_State 계산 with logging
        logger.info(f"\n6️⃣ BB_State 계산 중... (불일치 케이스만 로깅)")

        bb_state_list = [0] * len(closes)
        buzz_list = [buzz] * len(closes)

        mismatches_logged = 0
        max_log = 30
        start_log_idx = 105  # Index 105부터 로깅 (109-113 불일치 케이스 포함)

        for i in range(len(closes)):
            if i < 1:
                bb_state_list[i] = 0
                continue

            bbw_val = bbw_list[i]
            bbr_val = bbr_list[i]
            prev_bb_state = bb_state_list[i-1]

            if math.isnan(bbw_val) or math.isnan(bbr_val):
                bb_state_list[i] = prev_bb_state
                continue

            # 기본적으로 이전 상태 유지
            current_state = prev_bb_state

            # crossover(bbw, buzz) 체크
            co_buzz = crossover(bbw_list, buzz_list, i)
            if co_buzz:
                if bbr_val > 0.5:
                    current_state = 2
                elif bbr_val < 0.5:
                    current_state = -2

            # bbw < squeeze 체크
            if bbw_val < squeeze:
                current_state = -1

            # Pine Script Line 345-348: BBR 기반 상태 전환
            if current_state == 2 and bbr_val < 0.2:
                current_state = -2
            elif current_state == -2 and bbr_val > 0.8:
                current_state = 2

            # Pine Script Line 351-352: falling/rising으로 상태 리셋
            bbw_rising = rising(bbw_list, i, 1)
            bbw_falling = falling(bbw_list, i, 3)

            if ((current_state == 2 or current_state == -2) and bbw_falling):
                current_state = 0
            elif (bbw_val > pl_avg and current_state == -1 and bbw_rising):
                current_state = 0

            bb_state_list[i] = current_state

            # Pine Script 값과 비교
            pine_bb = candles[i].BB_State if hasattr(candles[i], 'BB_State') and candles[i].BB_State is not None else None

            if i >= start_log_idx and pine_bb is not None:
                if mismatches_logged < max_log and (pine_bb != current_state or i <= start_log_idx + 5):
                    ts_str = candles[i].timestamp.strftime("%Y-%m-%d %H:%M")
                    logger.info(f"\n❌ Index {i} ({ts_str}):")
                    logger.info(f"  Pine_BB: {pine_bb}, Python_BB: {current_state}")
                    logger.info(f"  bbw: {bbw_val:.4f}, squeeze: {squeeze:.4f}, bbw<squeeze: {bbw_val < squeeze}")
                    logger.info(f"  bbw > pl_avg: {bbw_val > pl_avg} (pl_avg={pl_avg:.4f})")
                    logger.info(f"  bbw_rising: {bbw_rising}, bbw_falling: {bbw_falling}")
                    logger.info(f"  bbr: {bbr_val:.4f}")
                    logger.info(f"  crossover(bbw, buzz): {co_buzz}")
                    logger.info(f"  prev_state: {prev_bb_state}")
                    mismatches_logged += 1

        logger.info("\n" + "=" * 100)
        return True

    except Exception as e:
        logger.error(f"❌ 디버깅 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python BACKTEST/debug_bb_state_transition.py <symbol> <timeframe>")
        print("예시: python BACKTEST/debug_bb_state_transition.py BTC-USDT-SWAP 15m")
        sys.exit(1)

    symbol = sys.argv[1]
    timeframe = sys.argv[2]

    success = asyncio.run(debug_bb_state_transition(symbol, timeframe))
    sys.exit(0 if success else 1)
