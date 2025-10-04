# API Endpoints
BASE_URL = "https://www.okx.com"
V5_API = "/api/v5"

# WebSocket
WSS_PUBLIC_URL = "wss://ws.okx.com:8443/ws/v5/public"
WSS_PRIVATE_URL = "wss://ws.okx.com:8443/ws/v5/private"
INST_TYPE = {
    "SPOT": "SPOT",
    "MARGIN": "MARGIN",
    "SWAP": "SWAP",      # 영구 스왑
    "FUTURES": "FUTURES" # 선물
}
# Endpoints
ENDPOINTS = {
    "GET_BALANCE": "/account/balance",
    "CREATE_ORDER": "/trade/order",
    "CANCEL_ORDER": "/trade/cancel-order",
    "GET_POSITIONS": "/account/positions",
    "GET_TICKER": "/market/ticker",
    "GET_ORDER": "/trade/order",  # 주문 조회
    "GET_ORDERS": "/trade/orders-pending",  # 미체결 주문 목록
    "GET_ORDER_HISTORY": "/trade/orders-history",  # 주문 내역
    "GET_INSTRUMENTS": "/public/instruments",  # 거래 가능한 심볼 목록
    "GET_FUNDING_RATE": "/public/funding-rate",  # 자금조달비율
    "GET_MARK_PRICE": "/public/mark-price",  # 청산가격
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