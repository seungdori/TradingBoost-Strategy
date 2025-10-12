from .client import OKXClient
from .constants import BASE_URL, ENDPOINTS, ERROR_CODES, V5_API, WSS_PRIVATE_URL, WSS_PUBLIC_URL
from .exceptions import OKXAPIException
from .websocket import OKXWebsocket

__all__ = [
    'OKXClient',
    'OKXWebsocket',
    'OKXAPIException',
    'BASE_URL',
    'V5_API',
    'WSS_PUBLIC_URL',
    'WSS_PRIVATE_URL',
    'ENDPOINTS',
    'ERROR_CODES',
]

# 버전 정보
__version__ = '1.0.0'

# 편의를 위한 클라이언트 생성 함수
def create_okx_client(api_key: str, api_secret: str, passphrase: str) -> OKXClient:
    """OKX 클라이언트 인스턴스를 생성합니다."""
    return OKXClient(api_key, api_secret, passphrase)

def create_okx_websocket(api_key: str, api_secret: str, passphrase: str) -> OKXWebsocket:
    """OKX 웹소켓 클라이언트 인스턴스를 생성합니다."""
    return OKXWebsocket(api_key, api_secret, passphrase) 