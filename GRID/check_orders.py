import ccxt

# OKX API 키와 시크릿 설정
api_key = 'YOUR_API_KEY'
api_secret = 'YOUR_API_SECRET'
password = 'YOUR_PASSWORD'  # OKX의 경우 Passphrase가 필요합니다.

# CCXT OKX 객체 생성
exchange = ccxt.okx({
    'apiKey': api_key,
    'secret': api_secret,
    'password': password,
})

# 주문 ID
order_id = 'e847386590ce4dBC2b053cdf555835a8'

try:
    # 주문 정보 확인
    order = exchange.fetch_order(order_id, 'BTC/USDT')  # 두 번째 인자는 거래 페어로 변경할 수 있습니다.
    print(order)
except ccxt.BaseError as e:
    print(f"An error occurred: {e}")