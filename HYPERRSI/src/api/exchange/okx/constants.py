"""HYPERRSI OKX 상수 (하위 호환성)

이 파일은 하위 호환성을 위해 유지되며, shared.exchange.okx를 재export합니다.
"""
from shared.exchange.okx.constants import (
    BASE_URL,
    ENDPOINTS,
    ERROR_CODES,
    INST_TYPE,
    V5_API,
    WSS_PRIVATE_URL,
    WSS_PUBLIC_URL,
)

__all__ = [
    'BASE_URL',
    'V5_API',
    'WSS_PUBLIC_URL',
    'WSS_PRIVATE_URL',
    'INST_TYPE',
    'ENDPOINTS',
    'ERROR_CODES'
]
