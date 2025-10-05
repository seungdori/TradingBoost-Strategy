import ccxt
import logging
import time
from shared.config import OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE  # 환경 변수에서 키 가져오기
# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# OKX API 클라이언트 초기화
exchange = ccxt.okx({
    'apiKey': OKX_API_KEY,
    'secret': OKX_SECRET_KEY,
    'password': OKX_PASSPHRASE,
    'enableRateLimit': True,
})
def get_open_positions():
    max_retries = 3
    retry_delay = 2  # 초

    for attempt in range(max_retries):
        try:
            # 모든 포지션 정보 가져오기
            positions = exchange.fetchPositions()
            logging.debug(f"Raw positions data: {positions}")  # 디버깅을 위해 원본 데이터 출력

            # 열린 포지션만 필터링 (contracts 또는 amount 필드 사용)
            open_positions = [pos for pos in positions if float(pos.get('contracts', 0)) != 0 or float(pos.get('amount', 0)) != 0]

            if not open_positions:
                logging.info("현재 열린 포지션이 없습니다.")
                return []

            position_info = []
            for pos in open_positions:
                symbol = pos['symbol']
                amount = float(pos.get('contracts', 0)) or float(pos.get('amount', 0))
                entry_price = float(pos.get('entryPrice', 0))
                side = pos.get('side', 'unknown')
                notional = float(pos.get('notional', 0))
                leverage = pos.get('leverage', 'N/A')
                
                info = {
                    'symbol': symbol,
                    'side': side,
                    'amount': abs(amount),
                    'entry_price': entry_price,
                    'notional': notional,
                    'leverage': leverage
                }
                position_info.append(info)
                logging.info(f"포지션: {symbol}, 방향: {side}, 수량: {abs(amount)}, 진입가: {entry_price}, "
                             f"명목 가치: {notional} USD, 레버리지: {leverage}x")

            return position_info

        except ccxt.NetworkError as e:
            if attempt < max_retries - 1:
                logging.warning(f"네트워크 오류 발생, 재시도 중 ({attempt + 1}/{max_retries}): {str(e)}")
                time.sleep(retry_delay)
            else:
                logging.error(f"네트워크 오류로 인한 최종 실패: {str(e)}", exc_info=True)
                return None

        except Exception as e:
            logging.error(f"포지션 정보 조회 중 오류 발생: {str(e)}", exc_info=True)
            return None

def fetch_specific_positions(symbol=None, position_type=None):
    try:
        params = {}
        if symbol:
            params['symbol'] = symbol
        if position_type:
            params['type'] = position_type

        positions = exchange.fetchPositions(params=params)
        return positions
    except Exception as e:
        logging.error(f"특정 포지션 정보 조회 중 오류 발생: {str(e)}", exc_info=True)
        return None

def main():
    # 모든 포지션 가져오기
    positions = get_open_positions()
    if positions:
        print("\n=== 현재 열린 포지션 요약 ===")
        for pos in positions:
            print(f"{pos['symbol']} ({pos['side']}): {pos['amount']} 계약, "
                  f"진입가: {pos['entry_price']}, 명목 가치: {pos['notional']} USD, 레버리지: {pos['leverage']}x")
    else:
        print("열린 포지션이 없거나 정보를 가져오는데 실패했습니다.")

    # 특정 심볼에 대한 포지션 가져오기 (예: BTC/USDT)
    btc_positions = fetch_specific_positions(symbol='BTC/USDT:USDT')
    if btc_positions:
        print("\n=== BTC/USDT 포지션 ===")
        for pos in btc_positions:
            print(f"방향: {pos['side']}, 수량: {pos['contracts']}, 진입가: {pos['entryPrice']}")

    # 특정 유형의 포지션 가져오기 (예: 마진 거래)
    margin_positions = fetch_specific_positions(position_type='MARGIN')
    if margin_positions:
        print("\n=== 마진 포지션 ===")
        for pos in margin_positions:
            print(f"{pos['symbol']} ({pos['side']}): {pos['contracts']} 계약")

if __name__ == "__main__":
    main()