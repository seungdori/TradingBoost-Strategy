class OKXAPIException(Exception):
    """OKX API 관련 예외"""
    def __init__(self, message: str, status_code: int = None, response: dict = None):
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