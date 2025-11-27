"""
Trend analysis indicators
"""
import math

from ._bollinger import calc_stddev
from ._core import crossover, rising, falling, pivothigh, pivotlow, resample_candles, resample_candles_raw
from ._moving_averages import calc_sma, get_ma


def _forward_fill_mtf_to_current_tf(candles_current, candles_mtf, mtf_values, is_backtest=True, debug_name=None):
    """
    MTF 값을 현재 타임프레임 길이로 forward fill하고, Pine Script의 f_security() offset 로직 적용

    Args:
        candles_current: 현재 타임프레임 캔들 리스트
        candles_mtf: MTF 캔들 리스트 (진짜 상위 타임프레임 데이터)
        mtf_values: MTF 캔들에서 계산된 값 리스트 (len(candles_mtf)와 동일)
        is_backtest: 백테스트 모드 여부 (True: 1-offset 적용)
        debug_name: 디버그용 변수 이름 (None이면 디버그 출력 안 함)

    Returns:
        현재 타임프레임 길이로 확장된 값 리스트 (len(candles_current)와 동일)

    Note:
        Pine Script의 f_security() 동작:
        - Line 13: request.security(...)[barstate.isrealtime ? 0 : 1]
        - 백테스트 모드에서는 이전 MTF 값 사용 (lookahead bias 방지)
    """
    from datetime import datetime

    # 결과 리스트 초기화
    result = [0] * len(candles_current)

    # MTF 캔들의 timestamp 추출
    mtf_timestamps = []
    for c in candles_mtf:
        ts = c.get('timestamp')
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            mtf_timestamps.append(dt)
        elif isinstance(ts, datetime):
            mtf_timestamps.append(ts)
        else:
            mtf_timestamps.append(datetime.fromtimestamp(ts))

    # 현재 TF 각 캔들에 대해 적절한 MTF 값 매핑
    mtf_idx = 0
    for i, candle in enumerate(candles_current):
        ts = candle.get('timestamp')
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        elif isinstance(ts, datetime):
            dt = ts
        else:
            dt = datetime.fromtimestamp(ts)

        # 현재 캔들 timestamp보다 작은 가장 최근 MTF 인덱스 찾기
        # Pine Script: 현재 캔들과 같은 timestamp의 MTF 캔들은 "아직 시작된" 것으로 처리
        # 따라서 현재 캔들이 MTF 캔들 시작점과 정확히 일치하면, 이전 MTF 캔들이 "방금 완료된" 것
        while mtf_idx + 1 < len(mtf_timestamps) and mtf_timestamps[mtf_idx + 1] < dt:
            mtf_idx += 1

        # Pine Script의 request.security() 동작:
        # - 현재 캔들이 첫 MTF 캔들보다 이전이면 na (0) 리턴
        # - mtf_idx = 0이면서 현재 캔들 timestamp < 첫 MTF timestamp인 경우
        if mtf_idx == 0 and dt < mtf_timestamps[0]:
            result[i] = 0
            continue

        # 현재 MTF 값 저장 (나중에 [1] offset 적용)
        result[i] = mtf_values[mtf_idx] if mtf_idx < len(mtf_values) else 0

    # Pine Script f_security의 [1] offset 적용:
    # f_security(_sym, _res, _src) => request.security(...)[barstate.isrealtime ? 0 : 1]
    # 백테스트에서 [1] = "이전 15분봉 시점의 결과" 사용
    if is_backtest:
        # 1개 shift: 이전 캔들의 값 사용
        # [0] + result[:-1] → 첫 번째 값은 0, 마지막 원본 값은 제거됨
        # 하지만 Pine Script에서 마지막 캔들도 [1] offset이 적용됨
        shifted_result = [0] + result[:-1]

        return shifted_result

    return result


def _calc_bb_state(candle_data, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=True, debug=False):
    """
    BB_State 계산 - PineScript 완전 일치 버전

    주요 변경사항:
    - pivot array를 각 캔들마다 업데이트하면서 avg 계산
    - 배열이 비어있을 때는 현재 캔들의 bbw 값 사용
    """
    closes = [c["close"] for c in candle_data]

    # BBW 1st 계산
    basis_list = calc_sma(closes, length_bb)
    std_list = calc_stddev(closes, length_bb)
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

    # Pivot High/Low 계산
    pivot_left = 20
    pivot_right = 10
    ph_list = pivothigh(bbw_list, pivot_left, pivot_right)
    pl_list = pivotlow(bbw_list, pivot_left, pivot_right)

    # BBW 2nd 계산
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

    # 각 캔들마다 계산할 값들을 저장할 리스트
    array_size = 50
    mult_plph = 0.7

    # bbw_2nd_squeeze 초기값
    bbw_2nd_squeeze_history = []

    # BB_State 계산 - 각 캔들마다 처리
    bb_state_list = []

    # PineScript와 동일하게 고정 크기 배열로 초기화 (nan으로 채움)
    # PineScript: var float[] pl_array = array.new_float(array_size, na)
    ph_array = [math.nan] * array_size
    pl_array = [math.nan] * array_size
    pl_array_2nd = [math.nan] * array_size

    for i in range(len(closes)):
        # 현재 캔들의 값들
        bbw_val = bbw_list[i]
        bbr_val = bbr_list[i]
        ma_val = bbw_ma[i]
        bbw_2nd_val = bbw_2nd_list[i]

        # ===== PineScript ta.pivothigh 동작 구현 =====
        # PineScript: ph = ta.pivothigh(bbw, leftbars=20, rightbars=10)
        # → 현재 바(i)에서 i-leftbars 위치의 pivot을 반환 (leftbars만큼 지연!)
        # → i-20 위치가 pivot이면 그 값, 아니면 na
        # → Python: ph_list[i-20]을 사용 (20개 지연)

        # pivot high (PineScript: ph = ta.pivothigh(bbw, 20, 10))
        # PineScript 방식: 인덱스 i에 i-leftbars 위치의 pivot 값 저장
        # → ph_list[i]를 직접 사용 (이미 확정된 pivot)
        recent_ph = None
        if i >= pivot_left + pivot_right:  # i >= 30 (충분한 데이터)
            if ph_list[i] is not None:
                recent_ph = ph_list[i]

        # pivot low (동일한 로직)
        recent_pl = None
        if i >= pivot_left + pivot_right:  # i >= 30
            if pl_list[i] is not None:
                recent_pl = pl_list[i]

        # pivot low 2nd (leftbars=30, rightbars=10)
        recent_pl_2nd = None
        if i >= 30 + 10:  # i >= 40
            if pl_2nd_list[i] is not None:
                recent_pl_2nd = pl_2nd_list[i]

        # ===== Pivot Array 업데이트 (PineScript 로직) =====
        # PineScript ph_array: array.push() → array.shift() (append → pop)
        # PineScript pl_array: array.shift() → array.push() (pop → append)

        # ph_array: 현재 바에서 bbw > ma이고, 최근 pivot이 있으면 추가
        # PineScript: if bbw > ma and ph > 0
        # Pine 순서: push → shift
        if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
            if bbw_val > ma_val and recent_ph is not None and recent_ph > 0:
                ph_array.append(recent_ph)  # push 먼저!
                ph_array.pop(0)             # shift 나중!

        # pl_array: 현재 바에서 bbw < ma이고, 최근 pivot이 있으면 추가
        # PineScript: if bbw < ma and pl > 0
        # Pine 순서: shift → push
        if ma_val is not None and not math.isnan(ma_val) and not math.isnan(bbw_val):
            if bbw_val < ma_val and recent_pl is not None and recent_pl > 0:
                pl_array.pop(0)      # shift 먼저!
                pl_array.append(recent_pl)  # push 나중!

        # pl_array_2nd: 현재 바에서 bbw_2nd < 1이고, 최근 pivot이 있으면 추가
        # PineScript: if bbw_2nd < 1 and pl_2nd > 0
        if not math.isnan(bbw_2nd_val) and bbw_2nd_val < 1 and recent_pl_2nd is not None and recent_pl_2nd > 0:
            pl_array_2nd.pop(0)  # 항상 shift 실행
            pl_array_2nd.append(recent_pl_2nd)

        # ===== 현재 캔들의 avg 값 계산 (PineScript와 동일) =====
        # PineScript: ph_count = count_not_na(ph_array), ph_sum = array.sum(ph_array)
        # PineScript array.sum()은 na를 제외하고 합계 계산

        # ph_avg: Pine 방식으로 계산 (유효한 값의 개수로 나눔)
        # PineScript: ph_count = count_not_na(ph_array), ph_sum = array.sum(ph_array)
        #             ph_avg = ph_count != 0 ? ph_sum / ph_count : math.max(bbw, 5)
        valid_ph = [v for v in ph_array if not math.isnan(v)]
        if len(valid_ph) > 0:
            ph_avg = sum(valid_ph) / len(valid_ph)  # ← 유효한 값의 개수로 나눔
        else:
            ph_avg = max(bbw_val if not math.isnan(bbw_val) else 0, 5)

        # pl_avg: Pine 방식으로 계산 (유효한 값의 개수로 나눔)
        # PineScript: pl_count = count_not_na(pl_array), pl_sum = array.sum(pl_array)
        #             pl_avg = pl_count != 0 ? pl_sum / pl_count : math.min(bbw, 5)
        valid_pl = [v for v in pl_array if not math.isnan(v)]
        if len(valid_pl) > 0:
            pl_avg = sum(valid_pl) / len(valid_pl)  # ← 유효한 값의 개수로 나눔
        else:
            pl_avg = min(bbw_val if not math.isnan(bbw_val) else 999, 5)

        # pl_avg_2nd: Pine 방식으로 계산 (유효한 값의 개수로 나눔)
        # PineScript: pl_count_2nd = count_not_na(pl_array_2nd), pl_sum_2nd = array.sum(pl_array_2nd)
        #             pl_avg_2nd = pl_count_2nd != 0 ? pl_sum_2nd / pl_count_2nd : math.min(bbw_2nd, 5)
        valid_pl_2nd = [v for v in pl_array_2nd if not math.isnan(v)]
        if len(valid_pl_2nd) > 0:
            pl_avg_2nd = sum(valid_pl_2nd) / len(valid_pl_2nd)  # ← 유효한 값의 개수로 나눔
        else:
            pl_avg_2nd = min(bbw_2nd_val if not math.isnan(bbw_2nd_val) else 999, 5)

        # buzz, squeeze 계산
        buzz = ph_avg * mult_plph
        squeeze = pl_avg * (1 / mult_plph)
        squeeze_2nd = pl_avg_2nd * (1 / mult_plph)

        # ===== bbw_2nd_squeeze 상태 업데이트 =====
        # PineScript: bbw_2nd_squeeze := use_BBW_2nd ? (BBW_2nd > squeeze_2nd ? false : BBW_2nd < squeeze_2nd ? true : bbw_2nd_squeeze) : true
        prev_squeeze = bbw_2nd_squeeze_history[-1] if bbw_2nd_squeeze_history else True
        current_squeeze = prev_squeeze

        if use_bbw_2nd:
            if not math.isnan(bbw_2nd_val):
                if bbw_2nd_val > squeeze_2nd:
                    current_squeeze = False
                elif bbw_2nd_val < squeeze_2nd:
                    current_squeeze = True
                # else: current_squeeze 유지 (bbw_2nd_val == squeeze_2nd)
        else:
            current_squeeze = True

        bbw_2nd_squeeze_history.append(current_squeeze)

        # ===== BB_State 계산 =====
        if i < 1:
            bb_state_list.append(0)
            continue

        prev_bb_state = bb_state_list[i-1]
        is_confirmed = True  # 백테스트 모드: 모든 캔들 확정

        # 기본값: 이전 상태 유지
        new_bb_state = prev_bb_state

        if math.isnan(bbw_val) or math.isnan(bbr_val):
            bb_state_list.append(new_bb_state)
            continue

        # BBW falling/rising 계산
        bbw_falling = False
        bbw_rising = False
        if i >= 2:
            if not math.isnan(bbw_list[i-1]) and not math.isnan(bbw_list[i-2]):
                bbw_falling = (bbw_val < bbw_list[i-1] and bbw_list[i-1] < bbw_list[i-2])
                bbw_rising = (bbw_val > bbw_list[i-1])

        # Pine Script Line 338-342: Crossover 조건
        bbw_prev = bbw_list[i-1] if i > 0 else math.nan
        if not math.isnan(bbw_prev):
            # Crossover: 이전 캔들은 buzz 이하, 현재 캔들은 buzz 초과
            if bbw_prev <= buzz and bbw_val > buzz and is_confirmed:
                if bbr_val > 0.5:
                    new_bb_state = 2
                elif bbr_val < 0.5:
                    new_bb_state = -2

        # Pine Script Line 342-343: Squeeze 조건 (barstate.isconfirmed 없음!)
        if bbw_val < squeeze and current_squeeze:
            new_bb_state = -1

        # Debug output
        if debug and 20 <= i <= 30:
            valid_ph = [v for v in ph_array if not math.isnan(v)]
            valid_pl = [v for v in pl_array if not math.isnan(v)]
            bbw_prev_str = f"{bbw_prev:.4f}" if not math.isnan(bbw_prev) else "NaN"
            print(f"[DEBUG i={i}] bbw={bbw_val:.4f}, bbr={bbr_val:.4f}, ma={ma_val:.4f}")
            print(f"  ph_array valid={len(valid_ph)}, pl_array valid={len(valid_pl)}")
            print(f"  ph_avg={ph_avg:.4f}, pl_avg={pl_avg:.4f}, buzz={buzz:.4f}, squeeze={squeeze:.4f}")
            print(f"  bbw_prev={bbw_prev_str}, new_bb_state={new_bb_state}")

        # Pine Script Line 345-348: BBR 조건
        if new_bb_state == 2 and bbr_val < 0.2 and is_confirmed:
            new_bb_state = -2
        if new_bb_state == -2 and bbr_val > 0.8 and is_confirmed:
            new_bb_state = 2

        # Pine Script Line 351-352: 상태 리셋 조건
        # 조건 A: (BB_State == 2 or BB_State == -2) and bbw_falling → barstate.isconfirmed 없음!
        # 조건 B: (bbw > pl_avg and BB_State == -1 and bbw_rising) and barstate.isconfirmed
        if ((new_bb_state == 2 or new_bb_state == -2) and bbw_falling):
            new_bb_state = 0
        if (bbw_val > pl_avg and new_bb_state == -1 and bbw_rising) and is_confirmed:
            new_bb_state = 0

        bb_state_list.append(new_bb_state)

    return bb_state_list


def rational_quadratic(series, lookback=30, relative_weight=0.5, start_at_bar=5):
    """
    PineScript rationalQuadratic() 정확한 구현

    Pine Script 로직 (Line 180-190):
    - _size = array.size(array.from(_src)) → 항상 1 (스칼라를 배열로 변환)
    - for i = 0 to _size + startAtBar → for i = 0 to 1 + 5 = 0 to 6 (7개 반복)
    - _src[i]: i 바 뒤를 봄 (lag)

    중요: Pine Script에서 _size는 항상 1! lookback이 아님!
    """
    import math
    N = len(series)
    out = []

    # Pine Script의 _size = array.size(array.from(_src)) = 1
    _size = 1

    for curr_idx in range(N):
        w_sum = 0.0
        val_sum = 0.0

        # Pine: for i = 0 to _size + startAtBar = for i = 0 to 6 (7개 반복: i=0,1,2,3,4,5,6)
        for lag in range(_size + start_at_bar + 1):  # +1 because "to" is inclusive in Pine
            look_back_idx = curr_idx - lag

            # 인덱스 범위 체크
            if look_back_idx < 0:
                break

            y = series[look_back_idx]

            # NaN 처리 (Pine의 nz() 동작)
            if math.isnan(y):
                continue

            # Weight: (1 + (lag^2 / (lookback^2 * 2 * relative_weight)))^(-relative_weight)
            w = (1.0 + (lag**2) / ((lookback**2) * 2 * relative_weight))**(-relative_weight)
            w_sum += w
            val_sum += y * w

        # 가중치 합이 0이면 현재 값 사용 (데이터 부족)
        if w_sum > 0:
            out.append(val_sum / w_sum)
        else:
            out.append(series[curr_idx] if curr_idx < len(series) else 0)

    return out


def compute_trend_state(
    candles,
    use_longer_trend=False,
    use_custom_length=False,
    custom_length=10,
    lookback=30,
    relative_weight=0.5,
    start_at_bar=5,
    candles_higher_tf=None,      # CYCLE용 MTF 데이터 (res_)
    candles_4h=None,              # CYCLE_2nd용 MTF 데이터 (240분)
    candles_bb_mtf=None,          # BB_State용 MTF 데이터 (bb_mtf)
    current_timeframe_minutes=None,  # 현재 타임프레임 (분), 리샘플링용
    is_confirmed_only=False,     # barstate.isconfirmed 시뮬레이션 (백테스트/히스토리: False, 실시간: True)
    external_bb_state_list=None,     # 외부 BB_State 리스트 (검증용)
    external_bb_state_mtf_list=None, # 외부 BB_State_MTF 리스트 (검증용)
):
    """
    TradingView PineScript의 CYCLE_Bull/Bear, BBW, trend_state 등을
    Multi-Timeframe (MTF) 로직 포함하여 정확하게 구현.

    Pine Script의 request.security() (f_security) 동작을 구현:
    - candles_higher_tf: CYCLE_Bull/Bear 계산용 (현재 TF에 따라 15m/30m/60m/480m)
    - candles_4h: CYCLE_Bull_2nd/Bear_2nd 계산용 (항상 240분)
    - is_confirmed_only: barstate.isconfirmed 시뮬레이션 (마지막 캔들 미확정 처리)
    - candles_bb_mtf: BB_State_MTF 계산용 (현재 TF에 따라 5m/15m/60m)

    MTF 데이터가 제공되지 않으면 current_timeframe_minutes 기반으로 리샘플링.
    """
    closes = [c["close"] for c in candles]

    ##################################################
    # 0) MTF 타임프레임 결정 및 데이터 준비
    ##################################################
    # Pine Script Line 32: res_ 결정
    # res_ = timeframe.multiplier <= 3 ? '15' : timeframe.multiplier <= 30 ? '30' : timeframe.multiplier < 240 ? '60' : '480'
    if current_timeframe_minutes is not None:
        if current_timeframe_minutes <= 3:
            res_minutes = 15
        elif current_timeframe_minutes <= 30:
            res_minutes = 30
        elif current_timeframe_minutes < 240:
            res_minutes = 60
        else:
            res_minutes = 480
    else:
        res_minutes = None

    # Pine Script Line 355: bb_mtf 결정
    # bb_mtf = timeframe.multiplier <= 3 ? '5' : timeframe.multiplier <= 15 ? '15' : '60'
    if current_timeframe_minutes is not None:
        if current_timeframe_minutes <= 3:
            bb_mtf_minutes = 5
        elif current_timeframe_minutes <= 15:
            bb_mtf_minutes = 15
        else:
            bb_mtf_minutes = 60
    else:
        bb_mtf_minutes = None

    # Pine Script Line 212: CYCLE_RES_2nd = '240' (항상 240분)
    cycle_2nd_minutes = 240

    # MTF 데이터 준비: 제공되지 않으면 리샘플링
    # CRITICAL: resample_candles_raw 사용 - 실제 MTF 캔들로 MA 계산 후 forward fill 해야 함
    if candles_higher_tf is None and res_minutes is not None:
        candles_higher_tf = resample_candles_raw(candles, res_minutes)

    if candles_4h is None:
        candles_4h = resample_candles_raw(candles, cycle_2nd_minutes)

    if candles_bb_mtf is None and bb_mtf_minutes is not None:
        candles_bb_mtf = resample_candles_raw(candles, bb_mtf_minutes)

    # MTF 데이터가 없으면 현재 타임프레임 사용 (fallback)
    if candles_higher_tf is None:
        candles_higher_tf = candles
    if candles_4h is None:
        candles_4h = candles
    if candles_bb_mtf is None:
        candles_bb_mtf = candles

    ##################################################
    # 1) 파라미터 세팅 (원본 코드 참조)
    ##################################################
    # 기본 빠른중간느린 길이
    lenF, lenM, lenS = 5, 10, 20
    CYCLE_TYPE = "JMA"

    if use_longer_trend:
        # 예: PineScript에서는 res_='D' 로 바꾸고, 길이를 20,40,120 등으로 세팅
        lenF, lenM, lenS = 20, 40, 120
        CYCLE_TYPE = "T3"

    if use_custom_length:
        lenF = max(custom_length+1, 1)
        lenM = round(custom_length*2.6)
        lenS = round(custom_length*4.8)
        CYCLE_TYPE = "T3"

    # 2번째 cycle (VIDYA 고정)
    lenF_2nd, lenM_2nd, lenS_2nd = 3, 9, 21

    ##################################################
    # 2) MA들 계산 (MTF 데이터 사용)
    ##################################################
    # Pine Script Line 197-204: MA (Cycle 1) - MTF (res_) 데이터로 계산
    # Pine Script Line 232-233: CYCLE_Bull/Bear = f_security(..., res_, ...)
    closes_htf = [c["close"] for c in candles_higher_tf]
    MA1_htf = get_ma(closes_htf, CYCLE_TYPE, length=lenF, phase_jma=50, power_jma=2)
    MA2_htf = get_ma(closes_htf, CYCLE_TYPE, length=lenM, phase_jma=50, power_jma=2)
    MA3_htf = get_ma(closes_htf, CYCLE_TYPE, length=lenS, phase_jma=50, power_jma=2)

    # rationalQuadratic 보정 (Pine Script Line 202-204)
    MA1_adj_htf = rational_quadratic(MA1_htf, lookback=lookback, relative_weight=relative_weight, start_at_bar=start_at_bar)
    MA2_adj_htf = rational_quadratic(MA2_htf, lookback=lookback, relative_weight=relative_weight, start_at_bar=start_at_bar)
    MA3_adj_htf = rational_quadratic(MA3_htf, lookback=lookback, relative_weight=relative_weight, start_at_bar=start_at_bar)

    # Forward fill: MTF MA 값을 현재 타임프레임 길이로 확장
    MA1_adj = _forward_fill_mtf_to_current_tf(candles, candles_higher_tf, MA1_adj_htf, is_backtest=True)
    MA2_adj = _forward_fill_mtf_to_current_tf(candles, candles_higher_tf, MA2_adj_htf, is_backtest=True)
    MA3_adj = _forward_fill_mtf_to_current_tf(candles, candles_higher_tf, MA3_adj_htf, is_backtest=True)

    # Pine Script Line 213-225: MA (Cycle 2, VIDYA) - 4시간 MTF 데이터로 계산
    # Pine Script Line 224-225: CYCLE_Bull_2nd/Bear_2nd = f_security(..., '240', ...)
    closes_4h = [c["close"] for c in candles_4h]
    MA1_2nd_4h = get_ma(closes_4h, "VIDYA", length=lenF_2nd)
    MA2_2nd_4h = get_ma(closes_4h, "VIDYA", length=lenM_2nd)
    MA3_2nd_4h = get_ma(closes_4h, "VIDYA", length=lenS_2nd)

    # Forward fill: 4h MA 값을 현재 타임프레임 길이로 확장
    MA1_2nd = _forward_fill_mtf_to_current_tf(candles, candles_4h, MA1_2nd_4h, is_backtest=True)
    MA2_2nd = _forward_fill_mtf_to_current_tf(candles, candles_4h, MA2_2nd_4h, is_backtest=True)
    MA3_2nd = _forward_fill_mtf_to_current_tf(candles, candles_4h, MA3_2nd_4h, is_backtest=True)

    ##################################################
    # 3) CYCLE_Bull / CYCLE_Bear (MTF - res_)
    ##################################################
    # Pine Script Line 229-233: MTF 타임프레임에서 계산 → f_security로 forward fill
    # 중요: MTF 타임프레임(15m)에서 먼저 계산한 다음 1분봉으로 forward fill

    # Step 1: MTF 타임프레임에서 CYCLE_Bull_og/Bear_og 계산
    closes_htf = [c["close"] for c in candles_higher_tf]
    CYCLE_Bull_htf = []
    CYCLE_Bear_htf = []

    for i in range(len(closes_htf)):
        m1 = MA1_adj_htf[i]
        m2 = MA2_adj_htf[i]
        m3 = MA3_adj_htf[i]

        # 단순 NaN 체크
        if math.isnan(m1) or math.isnan(m2) or math.isnan(m3):
            CYCLE_Bull_htf.append(False)
            CYCLE_Bear_htf.append(False)
            continue

        # Pine Script Line 229-230: CYCLE는 항상 barstate.isconfirmed 조건 포함
        # 백테스트 모드: 모든 과거 캔들은 확정됨 → 항상 조건 체크
        # 실시간 모드: is_confirmed_only=True이면 마지막 캔들만 미확정
        # 하지만 CYCLE는 Pine Script에서 항상 barstate.isconfirmed를 포함하므로
        # 백테스트에서는 모든 캔들이 확정으로 처리됨
        # Bull 조건
        is_bull = ((m1 > m2 and m2 > m3) or (m2 > m1 and m1 > m3))
        # Bear 조건
        is_bear = (m3 > m2 and m2 > m1)

        # 디버그: CYCLE_Bear가 False가 되는 지점 찾기
        CYCLE_Bull_htf.append(is_bull)
        CYCLE_Bear_htf.append(is_bear)

    # Step 2: f_security - forward fill to current timeframe (Pine Script Line 232-233)
    CYCLE_Bull_list = _forward_fill_mtf_to_current_tf(candles, candles_higher_tf, CYCLE_Bull_htf, is_backtest=True)
    CYCLE_Bear_list = _forward_fill_mtf_to_current_tf(candles, candles_higher_tf, CYCLE_Bear_htf, is_backtest=True)

    ##################################################
    # 4) CYCLE_Bull_2nd / CYCLE_Bear_2nd
    ##################################################
    # Pine Script Line 221-222: barstate.isconfirmed 조건 포함
    CYCLE_Bull_2nd_list = []
    CYCLE_Bear_2nd_list = []
    for i in range(len(closes)):
        m1_2 = MA1_2nd[i]
        m2_2 = MA2_2nd[i]
        m3_2 = MA3_2nd[i]

        # barstate.isconfirmed 시뮬레이션: 마지막 캔들은 미확정
        is_confirmed = (i < len(closes) - 1) if is_confirmed_only else True

        if math.isnan(m1_2) or math.isnan(m2_2) or math.isnan(m3_2):
            CYCLE_Bull_2nd_list.append(False)
            CYCLE_Bear_2nd_list.append(False)
            continue

        # Pine Script Line 221: CYCLE_Bull_2nd_og = (...) and barstate.isconfirmed
        # Pine Script Line 222: CYCLE_Bear_2nd_og = (...) and barstate.isconfirmed
        if is_confirmed:
            is_bull_2nd = (
                (m1_2 > m3_2 and m3_2 > m2_2) or
                (m1_2 > m2_2 and m2_2 > m3_2) or
                (m2_2 > m1_2 and m1_2 > m3_2)
            )
            is_bear_2nd = (
                (m3_2 > m2_2 and m2_2 > m1_2) or
                (m2_2 > m3_2 and m3_2 > m1_2) or
                (m3_2 > m1_2 and m1_2 > m2_2)
            )
        else:
            # 미확정 캔들: 이전 상태 유지
            is_bull_2nd = CYCLE_Bull_2nd_list[i-1] if i > 0 else False
            is_bear_2nd = CYCLE_Bear_2nd_list[i-1] if i > 0 else False

        CYCLE_Bull_2nd_list.append(is_bull_2nd)
        CYCLE_Bear_2nd_list.append(is_bear_2nd)

    ##################################################
    # 5) use_longer_trend 옵션 적용
    ##################################################
    final_bull = []
    final_bear = []
    for i in range(len(closes)):
        bull = CYCLE_Bull_list[i]
        bear = CYCLE_Bear_list[i]
        bull2 = CYCLE_Bull_2nd_list[i]
        bear2 = CYCLE_Bear_2nd_list[i]
        if use_longer_trend:
            bull = bull and bull2
            bear = bear and bear2
        final_bull.append(bull)
        final_bear.append(bear)

    ##################################################
    # 6) BBW / BB_State - Pine Script 원본 로직 (헬퍼 함수 사용)
    ##################################################
    # 외부 BB_State 사용 (검증용) 또는 자체 계산
    if external_bb_state_list is not None:
        bb_state_list = external_bb_state_list
    else:
        # Pine Script Line 261-352: BB_State 계산 (현재 타임프레임)
        bb_state_list = _calc_bb_state(candles, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=is_confirmed_only, debug=False)

    # 외부 BB_State_MTF 사용 (검증용) 또는 자체 계산
    if external_bb_state_mtf_list is not None:
        bb_state_mtf_list = external_bb_state_mtf_list
    else:
        # Pine Script Line 358: BB_State_MTF = f_security(..., bb_mtf, BB_State)
        # CRITICAL: bb_mtf가 현재 타임프레임과 동일하면 리샘플링/offset 없이 BB_State 직접 사용
        # Pine Script에서 f_security()는 동일 타임프레임 요청 시 현재 값 반환
        if bb_mtf_minutes is not None and current_timeframe_minutes is not None and bb_mtf_minutes == current_timeframe_minutes:
            # 동일 타임프레임: BB_State 직접 사용 (f_security offset 적용)
            # Pine Script: f_security(...)[barstate.isrealtime ? 0 : 1]
            # 백테스트 모드: 이전 캔들의 BB_State 사용 (1-offset)
            bb_state_mtf_list = [0] * len(candles)
            for i in range(len(candles)):
                if i > 0:
                    bb_state_mtf_list[i] = bb_state_list[i - 1]  # 1-offset (백테스트)
                else:
                    bb_state_mtf_list[i] = 0
        else:
            # 다른 타임프레임: MTF 데이터로 BB_State 계산 후 forward fill
            bb_state_mtf_raw = _calc_bb_state(candles_bb_mtf, length_bb=15, mult_bb=1.5, ma_length=100, is_confirmed_only=is_confirmed_only)

            # Forward fill: MTF BB_State를 현재 타임프레임 길이로 확장 + offset 적용
            bb_state_mtf_list = _forward_fill_mtf_to_current_tf(
                candles_current=candles,
                candles_mtf=candles_bb_mtf,
                mtf_values=bb_state_mtf_raw,
                is_backtest=True  # 백테스트 모드에서는 1-offset 적용
            )

    ##################################################
    # 7) Trend State (Pine Script Line 364-374, MTF 사용)
    ##################################################
    # Pine Script Line 364, 367, 370, 373: barstate.isconfirmed 조건 포함
    trend_state_list = [0]*len(closes)
    for i in range(len(closes)):
        bull = final_bull[i]
        bear = final_bear[i]
        # Pine Script Line 358, 364, 370: BB_State_MTF 사용 (현재 TF의 BB_State 아님!)
        bb_st_mtf = bb_state_mtf_list[i]

        # barstate.isconfirmed 시뮬레이션: 마지막 캔들은 미확정
        is_confirmed = (i < len(closes) - 1) if is_confirmed_only else True

        # 이전 상태 가져오기 (PineScript의 var 동작 모방)
        prev_state = trend_state_list[i-1] if i > 0 else 0

        # Pine Script Line 364: if barstate.isconfirmed and CYCLE_Bull and (...)
        # Pine Script Line 367: if barstate.isconfirmed and trend_state == 2 and not CYCLE_Bull
        # Pine Script Line 370: if barstate.isconfirmed and CYCLE_Bear and (...)
        # Pine Script Line 373: if barstate.isconfirmed and trend_state == -2 and not CYCLE_Bear
        if is_confirmed:
            # Pine Script Line 364-374: 정확한 로직 (CYCLE_2nd는 use_longer_trend 때만 사용)
            # IMPORTANT: use_longer_trend=False일 때는 CYCLE_2nd가 trend_state 진입에 영향을 주지 않음!

            # Bull 조건 (Pine Script Line 364-365)
            # if barstate.isconfirmed and CYCLE_Bull and (use_longer_trend ? true : BB_State_MTF == 2)
            if bull and (use_longer_trend or bb_st_mtf == 2):
                trend_state_list[i] = 2
            # Bull 종료 조건 (Pine Script Line 367-368)
            # if barstate.isconfirmed and trend_state == 2 and not CYCLE_Bull
            elif prev_state == 2 and not bull:
                trend_state_list[i] = 0
            # Bear 조건 (Pine Script Line 370-371)
            # if barstate.isconfirmed and CYCLE_Bear and (use_longer_trend ? true : BB_State_MTF == -2)
            elif bear and (use_longer_trend or bb_st_mtf == -2):
                trend_state_list[i] = -2
            # Bear 종료 조건 (Pine Script Line 373-374)
            # if barstate.isconfirmed and trend_state == -2 and not CYCLE_Bear
            elif prev_state == -2 and not bear:
                trend_state_list[i] = 0
            # 상태 유지 (PineScript의 var 동작)
            else:
                trend_state_list[i] = prev_state
        else:
            # 미확정 캔들: 이전 상태 유지
            trend_state_list[i] = prev_state

    ##################################################
    # 계산 결과를 candles에 저장
    ##################################################
    for i in range(len(candles)):
        candles[i]["CYCLE_Bull"] = final_bull[i]
        candles[i]["CYCLE_Bear"] = final_bear[i]
        candles[i]["CYCLE_Bull_2nd"] = CYCLE_Bull_2nd_list[i]
        candles[i]["CYCLE_Bear_2nd"] = CYCLE_Bear_2nd_list[i]
        candles[i]["BB_State"]   = bb_state_list[i]
        candles[i]["BB_State_MTF"] = bb_state_mtf_list[i]
        candles[i]["trend_state"] = trend_state_list[i]

    return candles
