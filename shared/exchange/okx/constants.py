"""OKX 거래소 API 상수

OKX 거래소와의 통신에 사용되는 URL, 엔드포인트, 에러 코드 등의 상수 정의
"""

# API Endpoints
BASE_URL = "https://www.okx.com"
V5_API = "/api/v5"

# WebSocket
WSS_PUBLIC_URL = "wss://ws.okx.com:8443/ws/v5/public"
WSS_PRIVATE_URL = "wss://ws.okx.com:8443/ws/v5/private"

# 상품 타입
INST_TYPE = {
    "SPOT": "SPOT",        # 현물
    "MARGIN": "MARGIN",    # 마진
    "SWAP": "SWAP",        # 영구 스왑
    "FUTURES": "FUTURES"   # 선물
}

# API Endpoints
ENDPOINTS = {
    # 계정 관련
    "GET_BALANCE": "/account/balance",
    "GET_POSITIONS": "/account/positions",

    # 거래 관련
    "CREATE_ORDER": "/trade/order",
    "CANCEL_ORDER": "/trade/cancel-order",
    "GET_ORDER": "/trade/order",
    "GET_ORDERS": "/trade/orders-pending",
    "GET_ORDER_HISTORY": "/trade/orders-history",

    # 시장 데이터
    "GET_TICKER": "/market/ticker",
    "GET_INSTRUMENTS": "/public/instruments",
    "GET_FUNDING_RATE": "/public/funding-rate",
    "GET_MARK_PRICE": "/public/mark-price",
    "GET_TIME": "/public/time",
}

# Error codes
ERROR_CODES = {
    "50001": "Invalid API key",
    "50002": "Invalid signature",
    "50004": "Invalid timestamp",
    "50111": "Order not exist",
    "51000": "Parameter error",
    "51002": "Order amount too small",
    "51004": "Order price out of permissible range"
}
