"""
Error Messages

주문 모듈에서 사용하는 에러 메시지 상수
"""

# Validation Errors
INVALID_SYMBOL_FORMAT = "잘못된 심볼 형식입니다"
INVALID_ORDER_SIDE = "잘못된 주문 사이드입니다"
INVALID_ORDER_TYPE = "잘못된 주문 타입입니다"
INVALID_ORDER_AMOUNT = "잘못된 주문 수량입니다"
INVALID_CLOSE_PERCENT = "종료 비율은 1-100 사이여야 합니다"
LIMIT_ORDER_REQUIRES_PRICE = "Limit 주문은 가격이 필요합니다"

# Exchange Errors
EXCHANGE_NOT_INITIALIZED = "거래소 클라이언트가 초기화되지 않았습니다"
EXCHANGE_CONNECTION_ERROR = "거래소 연결 오류"
EXCHANGE_AUTH_ERROR = "인증 오류"

# Position Errors
POSITION_NOT_FOUND = "포지션을 찾을 수 없습니다"
NO_POSITION_TO_CLOSE = "종료할 포지션이 없습니다"
INVALID_CLOSE_AMOUNT = "종료 수량이 0보다 커야 합니다"

# Order Errors
ORDER_NOT_FOUND = "주문을 찾을 수 없습니다"
INSUFFICIENT_FUNDS = "잔고가 부족합니다"
INVALID_ORDER = "잘못된 주문"
NO_ORDERS_TO_CANCEL = "취소할 주문이 없습니다"
NO_ALGO_ORDERS_TO_CANCEL = "취소할 알고리즘 주문이 없습니다"

# Stop Loss Errors
STOP_LOSS_CREATE_FAILED = "스탑로스 주문 생성 실패"
STOP_LOSS_CANCEL_FAILED = "스탑로스 주문 취소 실패"
STOP_LOSS_UPDATE_FAILED = "스탑로스 주문 업데이트 실패"
STOP_LOSS_NO_RESPONSE_DATA = "스탑로스 주문 응답 데이터 없음"

# Algo Order Errors
ALGO_ORDER_QUERY_FAILED = "알고리즘 주문 조회 실패"
ALGO_ORDER_CANCEL_FAILED = "알고리즘 주문 취소 실패"

# Redis Errors
REDIS_SAVE_FAILED = "Redis 데이터 저장 실패"
REDIS_QUERY_FAILED = "Redis 데이터 조회 실패"
REDIS_DELETE_FAILED = "Redis 데이터 삭제 실패"
REDIS_UPDATE_FAILED = "Redis 포지션 상태 업데이트 실패"

# Generic Errors
OPERATION_FAILED = "작업 실패"
MISSING_REQUIRED_PARAMS = "필수 파라미터가 누락되었습니다"
