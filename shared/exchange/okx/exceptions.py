"""OKX 거래소 API 예외 클래스

OKX API 통신 중 발생할 수 있는 예외들을 정의
"""
from typing import Optional


class OKXAPIException(Exception):
    """OKX API 관련 기본 예외"""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[dict] = None
    ):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)


class OKXRequestException(OKXAPIException):
    """API 요청 관련 예외"""
    pass


class OKXResponseException(OKXAPIException):
    """API 응답 관련 예외"""
    pass


class OKXWebsocketException(Exception):
    """웹소켓 관련 예외"""
    pass
