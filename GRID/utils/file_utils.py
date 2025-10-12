"""
File operation utilities (deprecated - use shared.utils.file_helpers)

이 모듈은 하위 호환성을 위해 유지됩니다.
새로운 코드는 shared.utils.file_helpers를 직접 사용하세요.
"""
from shared.utils.file_helpers import get_cached_data, lock_file

__all__ = ['lock_file', 'get_cached_data']
