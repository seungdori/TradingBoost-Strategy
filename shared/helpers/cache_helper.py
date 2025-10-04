"""캐시 만료 확인 헬퍼

캐시의 만료 시간을 확인하는 유틸리티 함수
"""
from datetime import datetime


def cache_expired(cache_expiry) -> bool:
    """캐시가 만료되었는지 확인

    Args:
        cache_expiry: 캐시 만료 시간 (datetime 객체 또는 None)

    Returns:
        bool: 캐시가 만료되었으면 True, 아니면 False
    """
    return datetime.now() > cache_expiry if cache_expiry else True
