"""
Core utility functions for technical indicators
"""
from datetime import datetime, timezone


def resample_candles(candles, target_minutes):
    """
    PineScript의 request.security() 동작 모방: 캔들을 더 높은 타임프레임으로 리샘플링

    Args:
        candles: 캔들 리스트 [{"timestamp": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}, ...]
        target_minutes: 목표 타임프레임 (분 단위, 예: 5, 15, 30, 60, 240, 480, 1440)

    Returns:
        리샘플링된 캔들 리스트 (원본과 동일한 길이, forward fill)
    """
    if not candles or target_minutes <= 0:
        return candles

    # 리샘플링 그룹 생성
    resampled = []
    current_group = []
    current_start_ts = None
    target_seconds = target_minutes * 60

    for candle in candles:
        ts = candle["timestamp"]
        if isinstance(ts, str):
            # ISO 문자열을 timestamp로 변환
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            ts_seconds = int(dt.timestamp())
        elif isinstance(ts, datetime):
            ts_seconds = int(ts.timestamp())
        else:
            ts_seconds = int(ts)

        # 그룹 시작 타임스탬프 계산 (타임프레임 정렬)
        group_start = (ts_seconds // target_seconds) * target_seconds

        if current_start_ts is None:
            current_start_ts = group_start

        # 새로운 그룹 시작
        if group_start > current_start_ts:
            if current_group:
                # 이전 그룹 집계
                resampled_candle = _aggregate_candles(current_group)
                resampled.append(resampled_candle)
            current_group = [candle]
            current_start_ts = group_start
        else:
            current_group.append(candle)

    # 마지막 그룹 처리
    if current_group:
        resampled_candle = _aggregate_candles(current_group)
        resampled.append(resampled_candle)

    # Forward fill: 리샘플링된 값을 원래 캔들 인덱스에 맞춰 확장
    result = []
    resampled_idx = 0
    current_resampled = resampled[0] if resampled else None

    for i, candle in enumerate(candles):
        ts = candle["timestamp"]
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            ts_seconds = int(dt.timestamp())
        elif isinstance(ts, datetime):
            ts_seconds = int(ts.timestamp())
        else:
            ts_seconds = int(ts)

        group_start = (ts_seconds // target_seconds) * target_seconds

        # 다음 리샘플링 값으로 이동해야 하는지 체크
        if resampled_idx + 1 < len(resampled):
            next_ts = resampled[resampled_idx + 1]["timestamp"]
            if isinstance(next_ts, str):
                dt = datetime.fromisoformat(next_ts.replace('Z', '+00:00'))
                next_ts_seconds = int(dt.timestamp())
            elif isinstance(next_ts, datetime):
                next_ts_seconds = int(next_ts.timestamp())
            else:
                next_ts_seconds = int(next_ts)

            next_group_start = (next_ts_seconds // target_seconds) * target_seconds

            if group_start >= next_group_start:
                resampled_idx += 1
                current_resampled = resampled[resampled_idx]

        # 현재 캔들에 리샘플링된 값 적용 (forward fill)
        result_candle = candle.copy()
        if current_resampled:
            result_candle["open"] = current_resampled["open"]
            result_candle["high"] = current_resampled["high"]
            result_candle["low"] = current_resampled["low"]
            result_candle["close"] = current_resampled["close"]
            result_candle["volume"] = current_resampled["volume"]

        result.append(result_candle)

    return result


def _aggregate_candles(candles):
    """
    캔들 그룹을 OHLCV로 집계

    Args:
        candles: 같은 타임프레임 그룹의 캔들 리스트

    Returns:
        집계된 캔들 dict
    """
    if not candles:
        return None

    aggregated = {
        "timestamp": candles[0]["timestamp"],  # 그룹의 첫 번째 타임스탬프
        "open": candles[0]["open"],             # 첫 번째 open
        "high": max(c["high"] for c in candles),  # 최대 high
        "low": min(c["low"] for c in candles),    # 최소 low
        "close": candles[-1]["close"],           # 마지막 close
        "volume": sum(c["volume"] for c in candles)  # volume 합계
    }

    return aggregated


def crossover(series_a, series_b, idx):
    """
    PineScript의 ta.crossover(a, b)를 모방한 함수
    - 직전(idx-1)에는 a <= b 이고, 현재(idx)에는 a > b 일 때 True
    - series_a, series_b: 리스트(길이가 동일해야 함)
    - idx: 현재 검사할 인덱스 (최소 1 이상이어야 함)
    """
    if idx < 1:
        return False
    return (series_a[idx] > series_b[idx]) and (series_a[idx - 1] <= series_b[idx - 1])


def crossunder(series_a, series_b, idx):
    """ta.crossunder(a, b) 모방."""
    if idx < 1:
        return False
    return (series_a[idx] < series_b[idx]) and (series_a[idx - 1] >= series_b[idx - 1])


def rising(series, idx, length=1):
    """
    PineScript의 ta.rising(series, length).
    - 직전부터 length개 구간 모두 증가했으면 True
    """
    if idx - length < 0:
        return False
    for i in range(idx, idx - length, -1):
        if series[i] <= series[i - 1]:
            return False
    return True


def falling(series, idx, length=1):
    """
    PineScript의 ta.falling(series, length).
    - 직전부터 length개 구간 모두 하락했으면 True
    """
    if idx - length < 0:
        return False
    for i in range(idx, idx - length, -1):
        if series[i] >= series[i - 1]:
            return False
    return True


def pivothigh(series, left_bars, right_bars):
    """
    PineScript의 ta.pivothigh(source, leftbars, rightbars) 구현.

    각 인덱스에서, 좌측 left_bars개와 우측 right_bars개 범위에서
    해당 값이 최대값이면 그 값을 반환, 아니면 None.

    Args:
        series: 값 리스트
        left_bars: 좌측 비교 기간
        right_bars: 우측 비교 기간

    Returns:
        list: 각 인덱스의 pivot high 값 (없으면 None)
    """
    result = [None] * len(series)

    for i in range(left_bars, len(series) - right_bars):
        current = series[i]

        # NaN 체크
        if current is None or (isinstance(current, float) and current != current):
            continue

        # 좌측 비교
        is_pivot = True
        for j in range(i - left_bars, i):
            if series[j] is None:
                continue
            if series[j] >= current:
                is_pivot = False
                break

        if not is_pivot:
            continue

        # 우측 비교
        for j in range(i + 1, i + right_bars + 1):
            if series[j] is None:
                continue
            if series[j] >= current:
                is_pivot = False
                break

        if is_pivot:
            result[i] = current

    return result


def pivotlow(series, left_bars, right_bars):
    """
    PineScript의 ta.pivotlow(source, leftbars, rightbars) 구현.

    각 인덱스에서, 좌측 left_bars개와 우측 right_bars개 범위에서
    해당 값이 최소값이면 그 값을 반환, 아니면 None.

    Args:
        series: 값 리스트
        left_bars: 좌측 비교 기간
        right_bars: 우측 비교 기간

    Returns:
        list: 각 인덱스의 pivot low 값 (없으면 None)
    """
    result = [None] * len(series)

    for i in range(left_bars, len(series) - right_bars):
        current = series[i]

        # NaN 체크
        if current is None or (isinstance(current, float) and current != current):
            continue

        # 좌측 비교
        is_pivot = True
        for j in range(i - left_bars, i):
            if series[j] is None:
                continue
            if series[j] <= current:
                is_pivot = False
                break

        if not is_pivot:
            continue

        # 우측 비교
        for j in range(i + 1, i + right_bars + 1):
            if series[j] is None:
                continue
            if series[j] <= current:
                is_pivot = False
                break

        if is_pivot:
            result[i] = current

    return result


def dynamic_round(value):
    if value is None:
        return None
    try:
        abs_val = abs(value)
        if abs_val < 0.0001:
            # 0.0001 미만일 때는 소수 여덟째 자리
            return round(value, 8)
        elif abs_val < 0.01:
            # 0.01 미만일 때는 소수 여섯째 자리
            return round(value, 6)
        elif abs_val < 1:
            # 1원 미만일 때는 소수 넷째 자리
            return round(value, 4)
        elif abs_val < 1000:
            # 1,000원 미만일 때는 소수 셋째 자리
            return round(value, 3)
        elif abs_val < 100000:
            # 10만 원 미만일 때는 소수 둘째 자리
            return round(value, 2)
        elif abs_val < 1000000:
            # 100만 원 미만일 때는 소수 첫째 자리
            return round(value, 1)
        else:
            # 그 이상이면 정수
            return round(value)
    except Exception as e:
        return value
