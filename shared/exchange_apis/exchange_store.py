# 임시 exchange_store 모듈

class DummyExchange:
    """테스트용 더미 교환소 클래스"""
    
    def __init__(self):
        self.name = "dummy"
    
    def fetch_balance(self, *args, **kwargs):
        """빈 잔액 정보 반환"""
        return {
            "info": {},
            "free": {},
            "used": {},
            "total": {}
        }
    
    def fetch_tickers(self, *args, **kwargs):
        """빈 티커 정보 반환"""
        return {}
    
    def fetch_positions(self, *args, **kwargs):
        """빈 포지션 정보 반환"""
        return []

_binance_instance = DummyExchange()
_upbit_instance = DummyExchange()
_bitget_instance = DummyExchange()
_okx_instance = DummyExchange()

def get_binance_instance():
    """바이낸스 인스턴스 반환"""
    return _binance_instance

def get_upbit_instance():
    """업비트 인스턴스 반환"""
    return _upbit_instance

def get_bitget_instance():
    """비트겟 인스턴스 반환"""
    return _bitget_instance

def get_okx_instance():
    """OKX 인스턴스 반환"""
    return _okx_instance 