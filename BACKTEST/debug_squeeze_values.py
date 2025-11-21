"""
squeeze 값을 상세히 로깅하는 디버그 스크립트

실행 방법:
    python BACKTEST/debug_squeeze_values.py BTC-USDT-SWAP 15m
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
from shared.indicators._core import pivothigh, pivotlow
from shared.logging import get_logger

logger = get_logger(__name__)


async def debug_squeeze_values(symbol: str, timeframe: str):
    """
    squeeze 값 계산 과정 디버깅
    """
    logger.info("=" * 100)
    logger.info(f"squeeze 값 디버깅: {symbol} {timeframe}")
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
        for i in range(len(closes)):
            basis_val = basis_list[i]
            std_val = stdev_list[i]
            if basis_val is None or std_val is None or math.isnan(basis_val) or math.isnan(std_val):
                bbw_list.append(math.nan)
            else:
                up = basis_val + mult_bb * std_val
                lo = basis_val - mult_bb * std_val
                if basis_val != 0:
                    bbw_list.append((up - lo) * 10.0 / basis_val)
                else:
                    bbw_list.append(math.nan)

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
        logger.info(f"\n5️⃣ 평균 계산:")
        logger.info(f"ph_array 크기: {len(ph_array)}")
        logger.info(f"pl_array 크기: {len(pl_array)}")

        if len(ph_array) > 0:
            ph_avg = sum(ph_array) / len(ph_array)
        else:
            ph_avg = max([b for b in bbw_list if not math.isnan(b)] + [5])

        if len(pl_array) > 0:
            pl_avg = sum(pl_array) / len(pl_array)
        else:
            pl_avg = min([b for b in bbw_list if not math.isnan(b)] + [5])

        logger.info(f"ph_avg: {ph_avg:.6f}")
        logger.info(f"pl_avg: {pl_avg:.6f}")

        # 7. buzz, squeeze 계산
        mult_plph = 0.7
        buzz = ph_avg * mult_plph
        squeeze = pl_avg * (1 / mult_plph)

        logger.info(f"\n6️⃣ 임계값 계산:")
        logger.info(f"buzz (ph_avg * 0.7): {buzz:.6f}")
        logger.info(f"squeeze (pl_avg / 0.7): {squeeze:.6f}")

        # 8. Index 7-16 구간 상세 분석
        logger.info(f"\n7️⃣ Index 7-16 구간 상세 (Pine=-2, Python=0 불일치):")
        logger.info(f"{'Idx':<6} {'Timestamp':<18} {'bbw':<10} {'squeeze':<10} {'bbw<sq':<8} {'Pine_BB':<8} {'Py_BB':<8}")
        logger.info("-" * 80)

        for i in range(7, min(17, len(candles))):
            c = candles[i]
            bbw_val = bbw_list[i]
            pine_bb = c.BB_State if hasattr(c, 'BB_State') and c.BB_State is not None else None

            # Python BB_State는 다시 계산해야 하므로 간단히 조건만 확인
            bbw_less_squeeze = bbw_val < squeeze if not math.isnan(bbw_val) else False

            ts_str = c.timestamp.strftime("%Y-%m-%d %H:%M")
            logger.info(
                f"{i:<6} {ts_str:<18} {bbw_val:<10.4f} {squeeze:<10.4f} "
                f"{str(bbw_less_squeeze):<8} {str(pine_bb):<8} {'?':<8}"
            )

        logger.info("\n" + "=" * 100)
        return True

    except Exception as e:
        logger.error(f"❌ 디버깅 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python BACKTEST/debug_squeeze_values.py <symbol> <timeframe>")
        print("예시: python BACKTEST/debug_squeeze_values.py BTC-USDT-SWAP 15m")
        sys.exit(1)

    symbol = sys.argv[1]
    timeframe = sys.argv[2]

    success = asyncio.run(debug_squeeze_values(symbol, timeframe))
    sys.exit(0 if success else 1)
