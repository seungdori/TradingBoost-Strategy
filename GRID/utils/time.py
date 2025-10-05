"""시간 계산 유틸리티"""

from datetime import datetime, timedelta
import pytz


def parse_timeframe(timeframe):
    """
    시간프레임 문자열을 파싱합니다.

    Args:
        timeframe: 시간프레임 문자열 (예: '15m', '1h')

    Returns:
        tuple: (단위, 값) - ('minutes', 15) 또는 ('hours', 1)
    """
    if 'm' in timeframe:
        return 'minutes', int(timeframe.replace('m', ''))
    elif 'h' in timeframe:
        return 'hours', int(timeframe.replace('h', ''))
    else:
        return 'minutes', 15  # 기본값


def calculate_current_timeframe_start(timeframe, timezone="Asia/Seoul"):
    """
    현재 시간프레임의 시작 시간을 계산합니다.

    Args:
        timeframe: 시간프레임 문자열
        timezone: 타임존

    Returns:
        datetime: 시간프레임 시작 시간
    """
    now = datetime.now(pytz.timezone(timezone))
    timeframe_unit, timeframe_value = parse_timeframe(timeframe)

    if timeframe_unit == 'minutes':
        current_timeframe_start = now - timedelta(minutes=now.minute % timeframe_value)
    elif timeframe_unit == 'hours':
        current_timeframe_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=now.hour % timeframe_value)

    return current_timeframe_start


def calculate_next_timeframe_start(now, timeframe):
    """
    다음 시간프레임의 시작 시간을 계산합니다.

    Args:
        now: 현재 시간
        timeframe: 시간프레임 문자열

    Returns:
        datetime: 다음 시간프레임 시작 시간
    """
    timeframe_unit, timeframe_value = parse_timeframe(timeframe)

    next_minute, next_hour = now.minute, now.hour
    if timeframe_unit == 'minutes':
        next_minute = ((now.minute // timeframe_value + 1) * timeframe_value) % 60
        if next_minute <= now.minute:
            next_hour = (now.hour + 1) % 24
    elif timeframe_unit == 'hours':
        next_hour = (now.hour + timeframe_value) % 24
        next_minute = 0

    next_timeframe_start = now.replace(hour=next_hour, minute=next_minute, second=0, microsecond=0)
    return next_timeframe_start


def calculate_sleep_duration(now, next_timeframe_start):
    """
    다음 시간프레임까지의 대기 시간을 계산합니다.

    Args:
        now: 현재 시간
        next_timeframe_start: 다음 시간프레임 시작 시간

    Returns:
        float: 대기 시간 (초)
    """
    delta = next_timeframe_start - now
    return max(15, delta.total_seconds())
