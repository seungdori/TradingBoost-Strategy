"""Timeframe Utility Module

Provides timeframe conversion and normalization utilities for all strategies.
"""

from typing import Optional

# Timeframe mapping for OKX and other exchanges
TF_MAPPING = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    # Uppercase variants
    "1M": "1m",
    "5M": "5m",
    "15M": "15m",
    "30M": "30m",
    "1H": "1h",
    "4H": "4h",
    "1D": "1d",
}


def get_timeframe(timeframe: Optional[str]) -> str:
    """
    시간 프레임을 맵핑에 따라 변환합니다.
    맵핑에 없는 시간 프레임은 원래 값을 그대로 반환합니다.

    Args:
        timeframe: 시간 프레임 문자열 (예: "1m", "5M", "1H")

    Returns:
        정규화된 시간 프레임 (소문자, 예: "1m", "5m", "1h")

    Examples:
        >>> get_timeframe("1M")
        "1m"
        >>> get_timeframe("4H")
        "4h"
        >>> get_timeframe(None)
        "1m"
    """
    if timeframe is None:
        return "1m"

    # 입력값을 소문자로 변환하여 매핑
    return TF_MAPPING.get(timeframe.lower(), timeframe.lower())


def normalize_timeframe(timeframe: str) -> str:
    """
    Alias for get_timeframe for better semantic meaning.

    Args:
        timeframe: Timeframe string to normalize

    Returns:
        Normalized timeframe string
    """
    return get_timeframe(timeframe)
