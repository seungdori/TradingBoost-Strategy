"""Redis 연결 관리자 - shared 모듈 재export 래퍼

이 파일은 하위 호환성을 위해 유지되며, shared.database.RedisConnectionManager를 재export합니다.
"""
from shared.database import RedisConnectionManager

__all__ = ['RedisConnectionManager']
