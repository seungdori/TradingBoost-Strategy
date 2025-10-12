"""OKX 거래소 통합 모듈

HYPERRSI와 GRID 전략에서 공통으로 사용되는 OKX API 기능 제공
"""
from shared.exchange.okx.client import OKXClient
from shared.exchange.okx.constants import (
    BASE_URL,
    ENDPOINTS,
    ERROR_CODES,
    INST_TYPE,
    V5_API,
    WSS_PRIVATE_URL,
    WSS_PUBLIC_URL,
)
from shared.exchange.okx.exceptions import (
    OKXAPIException,
    OKXRequestException,
    OKXResponseException,
    OKXWebsocketException,
)
from shared.exchange.okx.websocket import OKXWebsocket, get_position_via_websocket

__all__ = [
    # 클라이언트
    'OKXClient',
    'OKXWebsocket',
    'get_position_via_websocket',
    # 상수
    'BASE_URL',
    'V5_API',
    'WSS_PUBLIC_URL',
    'WSS_PRIVATE_URL',
    'INST_TYPE',
    'ENDPOINTS',
    'ERROR_CODES',
    # 예외
    'OKXAPIException',
    'OKXRequestException',
    'OKXResponseException',
    'OKXWebsocketException',
]
