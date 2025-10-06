"""
시간 및 타임프레임 계산 유틸리티

트레이딩에서 자주 사용되는 시간프레임 파싱 및 계산 함수들
"""

from datetime import datetime, timedelta
from typing import Literal
import pytz  # type: ignore[import-untyped]


def parse_timeframe(timeframe: str) -> tuple[Literal['minutes', 'hours', 'days'], int]:
    """
    시간프레임 문자열을 파싱합니다.

    Args:
        timeframe: 시간프레임 문자열 (예: '15m', '1h', '1d')

    Returns:
        tuple: (단위, 값) - ('minutes', 15), ('hours', 1), ('days', 1)

    Examples:
        >>> parse_timeframe('15m')
        ('minutes', 15)
        >>> parse_timeframe('1h')
        ('hours', 1)
        >>> parse_timeframe('1d')
        ('days', 1)
    """
    timeframe = timeframe.lower().strip()

    if 'd' in timeframe:
        return 'days', int(timeframe.replace('d', ''))
    elif 'h' in timeframe:
        return 'hours', int(timeframe.replace('h', ''))
    elif 'm' in timeframe:
        return 'minutes', int(timeframe.replace('m', ''))
    else:
        # 기본값: 15분
        return 'minutes', 15


def calculate_current_timeframe_start(
    timeframe: str,
    timezone: str = "Asia/Seoul"
) -> datetime:
    """
    현재 시간프레임의 시작 시간을 계산합니다.

    Args:
        timeframe: 시간프레임 문자열 (예: '15m', '1h')
        timezone: 타임존 (기본값: 'Asia/Seoul')

    Returns:
        datetime: 시간프레임 시작 시간

    Examples:
        >>> # 현재 시각이 14:37인 경우
        >>> calculate_current_timeframe_start('15m')
        # 14:30 반환
    """
    now = datetime.now(pytz.timezone(timezone))
    timeframe_unit, timeframe_value = parse_timeframe(timeframe)

    if timeframe_unit == 'minutes':
        # 현재 분을 timeframe_value로 나눈 나머지만큼 빼기
        current_timeframe_start = now.replace(second=0, microsecond=0) - timedelta(
            minutes=now.minute % timeframe_value
        )
    elif timeframe_unit == 'hours':
        # 현재 시간을 timeframe_value로 나눈 나머지만큼 빼기
        current_timeframe_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(
            hours=now.hour % timeframe_value
        )
    else:  # days
        # 당일 00:00:00
        current_timeframe_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    return current_timeframe_start


def calculate_next_timeframe_start(
    now: datetime,
    timeframe: str
) -> datetime:
    """
    다음 시간프레임의 시작 시간을 계산합니다.

    Args:
        now: 현재 시간
        timeframe: 시간프레임 문자열 (예: '15m', '1h')

    Returns:
        datetime: 다음 시간프레임 시작 시간

    Examples:
        >>> now = datetime(2025, 1, 1, 14, 37)
        >>> calculate_next_timeframe_start(now, '15m')
        # 14:45 반환
    """
    timeframe_unit, timeframe_value = parse_timeframe(timeframe)

    next_minute, next_hour = now.minute, now.hour
    next_day = now.day

    if timeframe_unit == 'minutes':
        # 다음 시간프레임의 분 계산
        next_minute = ((now.minute // timeframe_value + 1) * timeframe_value) % 60
        if next_minute <= now.minute:
            next_hour = (now.hour + 1) % 24
            if next_hour == 0:
                next_day = now.day + 1

    elif timeframe_unit == 'hours':
        next_hour = (now.hour + timeframe_value) % 24
        next_minute = 0
        if next_hour < now.hour:
            next_day = now.day + 1

    elif timeframe_unit == 'days':
        next_day = now.day + timeframe_value
        next_hour = 0
        next_minute = 0

    try:
        next_timeframe_start = now.replace(
            day=next_day,
            hour=next_hour,
            minute=next_minute,
            second=0,
            microsecond=0
        )
    except ValueError:
        # 월 경계 처리
        next_timeframe_start = now.replace(second=0, microsecond=0) + timedelta(
            days=1 if timeframe_unit == 'days' else 0,
            hours=timeframe_value if timeframe_unit == 'hours' else 0,
            minutes=timeframe_value if timeframe_unit == 'minutes' else 0
        )

    return next_timeframe_start


def calculate_sleep_duration(
    now: datetime,
    next_timeframe_start: datetime,
    minimum_sleep: int = 15
) -> float:
    """
    다음 시간프레임까지의 대기 시간을 계산합니다.

    Args:
        now: 현재 시간
        next_timeframe_start: 다음 시간프레임 시작 시간
        minimum_sleep: 최소 대기 시간 (초, 기본값: 15)

    Returns:
        float: 대기 시간 (초)

    Examples:
        >>> now = datetime(2025, 1, 1, 14, 37, 30)
        >>> next_start = datetime(2025, 1, 1, 14, 45, 0)
        >>> calculate_sleep_duration(now, next_start)
        450.0  # 7분 30초 = 450초
    """
    delta = next_timeframe_start - now
    sleep_seconds = delta.total_seconds()

    # 최소 대기 시간 보장
    return max(minimum_sleep, sleep_seconds)


def timeframe_to_seconds(timeframe: str) -> int:
    """
    시간프레임을 초 단위로 변환합니다.

    Args:
        timeframe: 시간프레임 문자열 (예: '15m', '1h', '1d')

    Returns:
        int: 초 단위 시간

    Examples:
        >>> timeframe_to_seconds('15m')
        900
        >>> timeframe_to_seconds('1h')
        3600
        >>> timeframe_to_seconds('1d')
        86400
    """
    unit, value = parse_timeframe(timeframe)

    if unit == 'minutes':
        return value * 60
    elif unit == 'hours':
        return value * 3600
    else:  # days
        return value * 86400


def timeframe_to_timedelta(timeframe: str) -> timedelta:
    """
    시간프레임을 timedelta 객체로 변환합니다.

    Args:
        timeframe: 시간프레임 문자열 (예: '15m', '1h', '1d')

    Returns:
        timedelta: 시간 간격

    Examples:
        >>> timeframe_to_timedelta('15m')
        timedelta(minutes=15)
        >>> timeframe_to_timedelta('1h')
        timedelta(hours=1)
    """
    unit, value = parse_timeframe(timeframe)

    if unit == 'minutes':
        return timedelta(minutes=value)
    elif unit == 'hours':
        return timedelta(hours=value)
    else:  # days
        return timedelta(days=value)


def get_timeframe_boundaries(
    dt: datetime,
    timeframe: str,
    timezone: str = "Asia/Seoul"
) -> tuple[datetime, datetime]:
    """
    주어진 시간이 속한 시간프레임의 시작과 끝 시간을 반환합니다.

    Args:
        dt: 기준 시간
        timeframe: 시간프레임 문자열
        timezone: 타임존

    Returns:
        tuple: (시작 시간, 끝 시간)

    Examples:
        >>> dt = datetime(2025, 1, 1, 14, 37)
        >>> start, end = get_timeframe_boundaries(dt, '15m')
        # (14:30, 14:45) 반환
    """
    if dt.tzinfo is None:
        dt = pytz.timezone(timezone).localize(dt)

    # 현재 시간프레임의 시작 계산
    unit, value = parse_timeframe(timeframe)

    if unit == 'minutes':
        start = dt.replace(second=0, microsecond=0) - timedelta(
            minutes=dt.minute % value
        )
    elif unit == 'hours':
        start = dt.replace(minute=0, second=0, microsecond=0) - timedelta(
            hours=dt.hour % value
        )
    else:  # days
        start = dt.replace(hour=0, minute=0, second=0, microsecond=0)

    # 끝 시간 = 시작 + 시간프레임
    end = start + timeframe_to_timedelta(timeframe)

    return start, end


# ============================================================================
# 추가 타임프레임 유틸리티 (GRID에서 통합)
# ============================================================================

from functools import lru_cache
from typing import Any
import pandas as pd  # type: ignore[import-untyped]


@lru_cache(maxsize=50)
def parse_timeframe_to_ms(timeframe: str) -> int:
    """
    타임프레임 문자열을 밀리초로 변환합니다.

    Args:
        timeframe: 타임프레임 문자열 (예: '15m', '1h', '1d', '1w')

    Returns:
        int: 밀리초 단위 시간

    Examples:
        >>> parse_timeframe_to_ms('15m')
        900000
        >>> parse_timeframe_to_ms('1h')
        3600000
    """
    if timeframe.endswith('m'):
        return int(timeframe[:-1]) * 60 * 1000
    elif timeframe.endswith('h'):
        return int(timeframe[:-1]) * 60 * 60 * 1000
    elif timeframe.endswith('d'):
        return int(timeframe[:-1]) * 24 * 60 * 60 * 1000
    elif timeframe.endswith('w'):
        return int(timeframe[:-1]) * 7 * 24 * 60 * 60 * 1000
    else:
        raise ValueError(f"지원하지 않는 타임프레임 형식: {timeframe}")


def convert_timestamp_millis_to_readable(timestamp_millis: int) -> str:
    """
    밀리초 타임스탬프를 읽기 쉬운 형식으로 변환합니다.

    Args:
        timestamp_millis: 밀리초 단위 타임스탬프

    Returns:
        str: 읽기 쉬운 형식의 날짜/시간 문자열

    Examples:
        >>> convert_timestamp_millis_to_readable(1609459200000)
        '2021-01-01 00:00:00'
    """
    timestamp_seconds = timestamp_millis / 1000
    date_time = datetime.fromtimestamp(timestamp_seconds)
    return date_time.strftime('%Y-%m-%d %H:%M:%S')


def ensure_kst_timestamp(ts: Any) -> Any:
    """
    타임스탬프를 KST (Asia/Seoul)로 변환합니다.

    Args:
        ts: 타임스탬프 (pandas.Timestamp)

    Returns:
        Any: KST로 변환된 타임스탬프

    Examples:
        >>> import pandas as pd
        >>> ts = pd.Timestamp('2021-01-01 00:00:00', tz='UTC')
        >>> kst_ts = ensure_kst_timestamp(ts)
        >>> kst_ts.tz
        <DstTzInfo 'Asia/Seoul' KST+9:00:00 STD>
    """
    if isinstance(ts, pd.Timestamp):
        if ts.tz is None:
            ts = ts.tz_localize('UTC')
        return ts.tz_convert('Asia/Seoul')
    return ts


def parse_exchange_name(exchange_name: str) -> tuple[str, str]:
    """
    거래소 이름을 파싱합니다.

    Args:
        exchange_name: 거래소 이름 (예: 'binance', 'okx_spot')

    Returns:
        tuple: (거래소명, 시장유형)

    Examples:
        >>> parse_exchange_name('binance')
        ('binance', 'swap')
        >>> parse_exchange_name('okx_spot')
        ('okx', 'spot')
    """
    if '_' in exchange_name:
        parts = exchange_name.split('_')
        return parts[0], parts[1] if len(parts) > 1 else 'swap'
    return exchange_name, 'swap'


def parse_timestamp(ts: Any, prev_ts: Any = None, interval: Any = None) -> Any:
    """
    타임스탬프를 파싱합니다.

    Args:
        ts: 파싱할 타임스탬프
        prev_ts: 이전 타임스탬프 (파싱 실패 시 반환)
        interval: 간격 (사용되지 않음)

    Returns:
        Any: 파싱된 타임스탬프 또는 prev_ts

    Examples:
        >>> parse_timestamp(1609459200000)
        Timestamp('2021-01-01 00:00:00')
    """
    try:
        if isinstance(ts, (int, float)):
            return pd.to_datetime(ts, unit='ms')
        elif isinstance(ts, str):
            return pd.to_datetime(ts)
        elif isinstance(ts, pd.Timestamp):
            return ts
        else:
            return prev_ts
    except Exception:
        return prev_ts


def fill_missing_timestamps(df: pd.DataFrame, file_name: str) -> pd.DataFrame:
    """
    누락된 타임스탬프를 채웁니다.

    Args:
        df: 데이터프레임
        file_name: 파일 이름 (사용되지 않음)

    Returns:
        pd.DataFrame: 타임스탬프가 채워진 데이터프레임

    Examples:
        >>> import pandas as pd
        >>> df = pd.DataFrame({'timestamp': ['2021-01-01 00:00', '2021-01-01 00:30']})
        >>> filled_df = fill_missing_timestamps(df, 'test.csv')
    """
    if df.empty or 'timestamp' not in df.columns:
        return df

    df = df.sort_values('timestamp').reset_index(drop=True)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    full_range = pd.date_range(start=df['timestamp'].min(), end=df['timestamp'].max(), freq='15min')
    df_full = pd.DataFrame({'timestamp': full_range})
    df = df_full.merge(df, on='timestamp', how='left')

    return df
