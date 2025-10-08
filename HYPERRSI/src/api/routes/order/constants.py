"""
Order API Constants

주문 관련 상수 정의
"""

# 주문 취소 청크 크기
ALGO_ORDERS_CHUNK_SIZE = 10  # 알고리즘 주문 한 번에 취소할 개수
REGULAR_ORDERS_CHUNK_SIZE = 20  # 일반 주문 한 번에 취소할 개수

# OKX API 엔드포인트
API_ENDPOINTS = {
    'ALGO_ORDERS_PENDING': 'trade/orders-algo-pending',
    'CANCEL_ALGO_ORDERS': 'trade/cancel-algos',
    'CANCEL_BATCH_ORDERS': 'trade/cancel-batch-orders',
}
