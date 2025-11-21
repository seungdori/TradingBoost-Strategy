"""
BB_State 계산 단계별 디버깅 스크립트
Pine Script와 Python의 pivot array 처리 방식, buzz/squeeze 임계값 차이 분석
"""
import asyncio
import math
from datetime import datetime, timedelta
from BACKTEST.data.timescale_provider import TimescaleProvider
from shared.indicators._all_indicators import calc_sma, calc_stddev
from shared.indicators._core import pivothigh, pivotlow, crossover, falling, rising
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def compute_bb_state_debug(candles):
    """BB_State 계산 과정을 단계별로 디버그"""
    closes = [c.close if hasattr(c, 'close') else c["close"] for c in candles]

    # BB 계산
    length = 20
    mult_bb = 2.0
    ma_length = 40

    basis_list = calc_sma(closes, length)
    std_list = calc_stddev(closes, length)

    upper_list = []
    lower_list = []
    bbw_list = []
    bbr_list = []

    for i in range(len(closes)):
        basis_val = basis_list[i]
        std_val = std_list[i]

        if basis_val is None or std_val is None or math.isnan(basis_val) or math.isnan(std_val):
            upper_list.append(math.nan)
            lower_list.append(math.nan)
            bbw_list.append(math.nan)
            bbr_list.append(math.nan)
            continue

        up = basis_val + mult_bb * std_val
        lo = basis_val - mult_bb * std_val
        upper_list.append(up)
        lower_list.append(lo)

        if basis_val != 0:
            bbw_list.append((up - lo) * 10.0 / basis_val)
        else:
            bbw_list.append(math.nan)

        if (up - lo) != 0:
            bbr_list.append((closes[i] - lo) / (up - lo))
        else:
            bbr_list.append(math.nan)

    # BBW MA
    bbw_ma = calc_sma(bbw_list, ma_length)

    # Pivot High/Low
    pivot_left = 20
    pivot_right = 10
    ph_list = pivothigh(bbw_list, pivot_left, pivot_right)
    pl_list = pivotlow(bbw_list, pivot_left, pivot_right)

    # Pivot Arrays - Python 방식 (빈 리스트로 시작)
    array_size = 50
    ph_array = []
    pl_array = []

    # 각 캔들에서의 pivot array 상태 기록
    ph_array_history = []
    pl_array_history = []

    logger.info("=== Pivot 수집 과정 ===")
    for i in range(len(closes)):
        bbw_val = bbw_list[i]
        ma_val = bbw_ma[i]

        if ma_val is None or math.isnan(ma_val) or math.isnan(bbw_val):
            ph_array_history.append(ph_array.copy())
            pl_array_history.append(pl_array.copy())
            continue

        # bbw > ma일 때만 pivot high 수집
        if bbw_val > ma_val and ph_list[i] is not None:
            ph_array.append(ph_list[i])
            if len(ph_array) > array_size:
                ph_array.pop(0)
            logger.info(f"  idx {i}: Pivot High 감지 {ph_list[i]:.4f} (bbw={bbw_val:.4f} > ma={ma_val:.4f}), array len={len(ph_array)}")

        # bbw < ma일 때만 pivot low 수집
        if bbw_val < ma_val and pl_list[i] is not None:
            pl_array.append(pl_list[i])
            if len(pl_array) > array_size:
                pl_array.pop(0)
            logger.info(f"  idx {i}: Pivot Low 감지 {pl_list[i]:.4f} (bbw={bbw_val:.4f} < ma={ma_val:.4f}), array len={len(pl_array)}")

        ph_array_history.append(ph_array.copy())
        pl_array_history.append(pl_array.copy())

    # ph_avg, pl_avg 계산 (최종 상태)
    if len(ph_array) > 0:
        ph_avg = sum(ph_array) / len(ph_array)
    else:
        ph_avg = max([b for b in bbw_list if not math.isnan(b)] + [5])

    if len(pl_array) > 0:
        pl_avg = sum(pl_array) / len(pl_array)
    else:
        pl_avg = min([b for b in bbw_list if not math.isnan(b)] + [5])

    logger.info(f"\n최종 Pivot Array 상태:")
    logger.info(f"  ph_array: {len(ph_array)}개 값 → ph_avg = {ph_avg:.6f}")
    logger.info(f"  pl_array: {len(pl_array)}개 값 → pl_avg = {pl_avg:.6f}")

    # BBW 2nd
    length_2nd = 60
    use_bbw_2nd = True
    basis_2nd_list = calc_sma(closes, length_2nd)
    stdev_2nd_list = calc_stddev(closes, length_2nd)
    bbw_2nd_list = []

    for i in range(len(closes)):
        basis_val = basis_2nd_list[i]
        stdev_val = stdev_2nd_list[i]
        if basis_val is None or stdev_val is None or math.isnan(basis_val) or math.isnan(stdev_val):
            bbw_2nd_list.append(math.nan)
        else:
            upper_2nd = basis_val + mult_bb * stdev_val
            lower_2nd = basis_val - mult_bb * stdev_val
            if basis_val != 0:
                bbw_2nd_list.append((upper_2nd - lower_2nd) * 10.0 / basis_val)
            else:
                bbw_2nd_list.append(math.nan)

    # Pivot Low for BBW_2nd
    pl_2nd_list = pivotlow(bbw_2nd_list, 30, 10)
    pl_array_2nd = []

    for i in range(len(closes)):
        bbw_2nd_val = bbw_2nd_list[i]
        if not math.isnan(bbw_2nd_val) and bbw_2nd_val < 1 and pl_2nd_list[i] is not None:
            pl_array_2nd.append(pl_2nd_list[i])
            if len(pl_array_2nd) > array_size:
                pl_array_2nd.pop(0)

    if len(pl_array_2nd) > 0:
        pl_avg_2nd = sum(pl_array_2nd) / len(pl_array_2nd)
    else:
        pl_avg_2nd = min([b for b in bbw_2nd_list if not math.isnan(b)] + [5])

    logger.info(f"  pl_array_2nd: {len(pl_array_2nd)}개 값 → pl_avg_2nd = {pl_avg_2nd:.6f}")

    # buzz, squeeze 계산
    mult_plph = 0.7
    buzz = ph_avg * mult_plph
    squeeze = pl_avg * (1 / mult_plph)
    squeeze_2nd = pl_avg_2nd * (1 / mult_plph)

    logger.info(f"\n임계값 계산:")
    logger.info(f"  buzz = {ph_avg:.6f} * {mult_plph} = {buzz:.6f}")
    logger.info(f"  squeeze = {pl_avg:.6f} * {1/mult_plph:.6f} = {squeeze:.6f}")
    logger.info(f"  squeeze_2nd = {pl_avg_2nd:.6f} * {1/mult_plph:.6f} = {squeeze_2nd:.6f}")

    # bbw_2nd_squeeze 상태
    bbw_2nd_squeeze = True
    bbw_2nd_squeeze_history = [True] * len(closes)

    for i in range(len(closes)):
        bbw_2nd_val = bbw_2nd_list[i]
        if not math.isnan(bbw_2nd_val):
            if use_bbw_2nd and bbw_2nd_val > squeeze_2nd:
                bbw_2nd_squeeze = False
            if use_bbw_2nd and bbw_2nd_val < squeeze_2nd:
                bbw_2nd_squeeze = True
        bbw_2nd_squeeze_history[i] = bbw_2nd_squeeze

    # BB_State 계산
    bb_state_list = [0] * len(closes)

    logger.info(f"\n=== BB_State 계산 (idx 0-30) ===")
    for i in range(min(31, len(closes))):
        if i < 1:
            bb_state_list[i] = 0
            continue

        bbw_val = bbw_list[i]
        bbr_val = bbr_list[i]
        prev_bb_state = bb_state_list[i-1]

        if math.isnan(bbw_val) or math.isnan(bbr_val):
            bb_state_list[i] = prev_bb_state
            continue

        current_state = prev_bb_state

        # crossover(bbw, buzz) 체크
        xo = crossover(bbw_list, [buzz]*len(closes), i)
        if xo:
            if bbr_val > 0.5:
                logger.info(f"  idx {i}: crossover(bbw, buzz) + bbr > 0.5 → state = 2 (bbw={bbw_val:.4f}, buzz={buzz:.4f}, bbr={bbr_val:.4f})")
                current_state = 2
            elif bbr_val < 0.5:
                logger.info(f"  idx {i}: crossover(bbw, buzz) + bbr < 0.5 → state = -2 (bbw={bbw_val:.4f}, buzz={buzz:.4f}, bbr={bbr_val:.4f})")
                current_state = -2

        # bbw < squeeze and bbw_2nd_squeeze
        if bbw_val < squeeze and bbw_2nd_squeeze_history[i]:
            logger.info(f"  idx {i}: bbw < squeeze + bbw_2nd_squeeze → state = -1 (bbw={bbw_val:.4f}, squeeze={squeeze:.4f})")
            current_state = -1

        # BBR 기반 상태 전환
        if current_state == 2 and bbr_val < 0.2:
            logger.info(f"  idx {i}: state=2 + bbr < 0.2 → state = -2 (bbr={bbr_val:.4f})")
            current_state = -2
        elif current_state == -2 and bbr_val > 0.8:
            logger.info(f"  idx {i}: state=-2 + bbr > 0.8 → state = 2 (bbr={bbr_val:.4f})")
            current_state = 2

        # falling/rising으로 상태 리셋
        if ((current_state == 2 or current_state == -2) and falling(bbw_list, i, 3)):
            logger.info(f"  idx {i}: state={current_state} + falling(bbw, 3) → state = 0")
            current_state = 0
        elif (bbw_val > pl_avg and current_state == -1 and rising(bbw_list, i, 1)):
            logger.info(f"  idx {i}: state=-1 + bbw > pl_avg + rising(bbw, 1) → state = 0")
            current_state = 0

        if current_state != prev_bb_state:
            logger.info(f"  idx {i}: BB_State 변경: {prev_bb_state} → {current_state}")

        bb_state_list[i] = current_state

    return bb_state_list, bbw_list, bbr_list, buzz, squeeze, ph_avg, pl_avg


async def main():
    symbol = "BTC-USDT-SWAP"
    timeframe = "15m"

    logger.info("="*100)
    logger.info(f"BB_State 단계별 디버깅: {symbol} {timeframe}")
    logger.info("="*100)

    # 30일치 데이터 로드
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=30)

    provider = TimescaleProvider()
    candles = await provider.get_candles(symbol, timeframe, start_date, end_date)
    logger.info(f"\n✅ {len(candles)}개 캔들 로드 완료")

    # Pine Script 결과는 TimescaleDB의 bb_state 컬럼에서 로드
    pine_bb_states = [c.bb_state if hasattr(c, 'bb_state') and c.bb_state is not None else 0 for c in candles]
    logger.info(f"✅ Pine Script BB_State {len(pine_bb_states)}개 로드 완료")

    # Python 계산
    logger.info("\n" + "="*100)
    bb_state_list, bbw_list, bbr_list, buzz, squeeze, ph_avg, pl_avg = compute_bb_state_debug(candles)
    logger.info("="*100)

    # 비교
    logger.info(f"\n=== Pine Script vs Python 비교 (첫 30개 불일치) ===")
    mismatches = 0
    matches = 0
    for i in range(len(candles)):
        pine_bb = pine_bb_states[i]
        py_bb = bb_state_list[i]

        if pine_bb == py_bb:
            matches += 1
        else:
            mismatches += 1
            if mismatches <= 30:
                close_val = candles[i].close if hasattr(candles[i], 'close') else candles[i]["close"]
                ts = candles[i].timestamp if hasattr(candles[i], 'timestamp') else candles[i]["timestamp"]
                logger.info(f"  idx {i}: {ts} | close={close_val:.2f} | Pine={pine_bb}, Py={py_bb} | bbw={bbw_list[i]:.4f}, bbr={bbr_list[i]:.4f}")

    logger.info(f"\n일치율: {matches}/{len(candles)} ({100*matches/len(candles):.2f}%)")
    logger.info(f"불일치: {mismatches}개")


if __name__ == "__main__":
    asyncio.run(main())
