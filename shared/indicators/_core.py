"""
Core utility functions for technical indicators
"""

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
    except:
        return value
