from datetime import datetime, timedelta
from shared.dtos.exchange import WalletDto

from services.binance_service import get_binance_futures_account_balance, get_binance_wallet, get_binance_tickers, \
    fetch_binance_positions, revalidate_binance_cache
from services.binance_spot_service import get_binance_spot_account_balance, get_binance_spot_wallet, get_binance_spot_tickers, \
    fetch_binance_spot_positions, revalidate_binance_spot_cache
from services.upbit_service import get_upbit_tickers, get_upbit_balances, fetch_upbit_positions, get_upbit_wallet, \
    fetch_upbit_avg_price, revalidate_upbit_cache
from services.bitget_service import get_bitget_futures_account_balance, get_bitget_wallet, get_bitget_tickers, \
    fetch_bitget_positions, revalidate_bitget_cache
from services.okx_service import get_okx_futures_account_balance, get_okx_wallet, get_okx_tickers, \
    fetch_okx_positions, revalidate_okx_cache
from services.bitget_spot_service import get_bitget_spot_account_balance, get_bitget_spot_wallet, get_bitget_spot_tickers, \
    fetch_bitget_spot_positions, revalidate_bitget_spot_cache
from services.okx_spot_service import get_okx_spot_account_balance, get_okx_spot_wallet, get_okx_spot_tickers, \
    fetch_okx_spot_positions, revalidate_okx_spot_cache

AVG_PRICE_CACHE_TIME_SECONDS = 15


# If user update api key or secret, revalidate cache
def revalidate_cache(exchange_name: str):
    if exchange_name == 'binance':
        revalidate_binance_cache()


    elif exchange_name == 'upbit':
        revalidate_upbit_cache()

    elif exchange_name == 'bitget':
        revalidate_bitget_cache()

    elif exchange_name == 'okx':
        revalidate_okx_cache()

    else:
        raise ValueError(f'Unknown exchange name: {exchange_name}')


async def fetch_position(exchange_name: str):
    if exchange_name == 'binance':
        return await fetch_binance_positions()

    elif exchange_name == 'upbit':
        return await fetch_upbit_positions()


    elif exchange_name == 'bitget':
        return await fetch_bitget_positions()
    elif exchange_name == 'okx':
        return await fetch_okx_positions()
    elif exchange_name == 'binance_spot':
        return await fetch_binance_spot_positions()
    elif exchange_name == 'bitget_spot':
        return await fetch_bitget_spot_positions()
    elif exchange_name == 'okx_spot':
        return await fetch_okx_spot_positions()

    else:
        raise ValueError('Invalid exchange')

async def get_wallet(exchange_name: str) -> WalletDto:
    if exchange_name == 'binance':
        total_balance, total_wallet_balance, total_unrealized_profit = await get_binance_wallet()
        return WalletDto(
            exchange_name=exchange_name,
            total_balance=total_balance,
            wallet_balance=total_wallet_balance,
            total_unrealized_profit=total_unrealized_profit
        )


    elif exchange_name == 'upbit':
        total_balance, krw_balance = await get_upbit_wallet()
        total_unrealized_profit = await calculate_unrealized_profit(exchange_name='upbit')
        return WalletDto(
            exchange_name=exchange_name,
            total_balance=total_balance,
            wallet_balance=krw_balance,
            total_unrealized_profit=total_unrealized_profit
        )
    
    if exchange_name == 'bitget':
        total_balance, total_wallet_balance, total_unrealized_profit = await get_bitget_wallet()
        return WalletDto(
            exchange_name=exchange_name,
            total_balance=total_balance,
            wallet_balance=total_wallet_balance,
            total_unrealized_profit=total_unrealized_profit
        )
    if exchange_name == 'okx':
        total_balance, total_wallet_balance, total_unrealized_profit = await get_okx_wallet()
        return WalletDto(
            exchange_name=exchange_name,
            total_balance=total_balance,
            wallet_balance=total_wallet_balance,
            total_unrealized_profit=total_unrealized_profit
        )
    if exchange_name == 'binance_spot':
        total_balance, total_wallet_balance, total_unrealized_profit = await get_binance_spot_wallet()
        return WalletDto(
            exchange_name=exchange_name,
            total_balance=total_balance,
            wallet_balance=total_wallet_balance,
            total_unrealized_profit=total_unrealized_profit
        )
    if exchange_name == 'bitget_spot':
        total_balance, total_wallet_balance, total_unrealized_profit = await get_bitget_spot_wallet()
        return WalletDto(
            exchange_name=exchange_name,
            total_balance=total_balance,
            wallet_balance=total_wallet_balance,
            total_unrealized_profit=total_unrealized_profit
        )
    if exchange_name == 'okx_spot':
        total_balance, total_wallet_balance, total_unrealized_profit = await get_okx_spot_wallet()
        return WalletDto(
            exchange_name=exchange_name,
            total_balance=total_balance,
            wallet_balance=total_wallet_balance,
            total_unrealized_profit=total_unrealized_profit
        )

    else:
        raise ValueError(f"Unknown exchange name: {exchange_name}")


async def fetch_ccxt_tickers(exchange_name: str):
    if exchange_name == 'binance':
        return await get_binance_tickers()

    elif exchange_name == 'upbit':
        return await get_upbit_tickers()

    elif exchange_name == 'bitget':
        return await get_bitget_tickers()
    
    elif exchange_name == 'okx':
        return await get_okx_tickers()
    
    elif exchange_name == 'binance_spot':
        return await get_binance_spot_tickers()

    elif exchange_name == 'bitget_spot':
        return await get_bitget_spot_tickers()
    
    elif exchange_name == 'okx_spot':
        return await get_okx_spot_tickers()

    else:
        raise ValueError(f'Unknown exchange name: {exchange_name}')


async def fetch_ccxt_balances(exchange_name: str):
    if exchange_name == 'binance':
        return await get_binance_futures_account_balance()

    elif exchange_name == 'upbit':
        return await get_upbit_balances()

    
    elif exchange_name == 'bitget':
        return await get_bitget_futures_account_balance()
    
    elif exchange_name == 'okx':
        return await get_okx_futures_account_balance()
    
    if exchange_name == 'binance_spot':
        return await get_binance_spot_account_balance()

    elif exchange_name == 'bitget_spot':
        return await get_bitget_spot_account_balance()
    
    elif exchange_name == 'okx_spot':
        return await get_okx_spot_account_balance()

    else:
        raise ValueError(f'Unknown exchange name: {exchange_name}')

async def fetch_ccxt_avg_price(exchange_name: str):
    global global_avg_price_cache, avg_price_cache_expiry

    # Todo: refactor

    if exchange_name == 'upbit':
        return await fetch_upbit_avg_price()


    try:
        balance_data = await fetch_ccxt_balances(exchange_name)
        global_avg_price_cache = {
            item['currency']: item['avg_buy_price']
            for item in balance_data['info']
            if 'currency' in item and 'avg_buy_price' in item and item['balance'] != '0'
        }

        # 캐시 만료 시간을 10초로 설정
        avg_price_cache_expiry = datetime.now() + timedelta(seconds=AVG_PRICE_CACHE_TIME_SECONDS)
        return global_avg_price_cache
    except Exception as e:
        raise e


async def fetch_spot_info(exchange_name: str):
    spot_info = []

    try:
        tickers = await fetch_ccxt_tickers(exchange_name)
        balances = await fetch_ccxt_balances(exchange_name)
        avg_prices = await fetch_ccxt_avg_price(exchange_name)

        for currency, balance in balances['total'].items():
            if currency == "KRW" or balance <= 0:
                continue

            if currency not in avg_prices:
                continue

            symbol = f'{currency}/KRW'
            if symbol in tickers:
                ticker = tickers[symbol]
                current_price = ticker.get('last', 0)

                spot_data = {
                    'currency': currency,
                    'current_price': current_price,
                    'balance': balance,
                    'avg_buy_price': avg_prices[currency],
                }
                spot_info.append(spot_data)

        return spot_info

    except Exception as e:
        print(f"스팟 정보 가져오기 중 오류 발생: {e}")


async def calculate_unrealized_profit(exchange_name: str):
    try:
        spot_info = await fetch_spot_info(exchange_name)
        unrealized_profit = 0
        for info in spot_info:
            current_price = info['current_price']
            balance = info['balance']
            avg_buy_price = info['avg_buy_price']

            # avg_buy_price를 실수로 변환
            try:
                avg_buy_price = float(avg_buy_price)
            except ValueError:
                avg_buy_price = 0  # 변환할 수 없는 경우 0으로 설정

            unrealized_profit += (current_price - avg_buy_price) * balance

        return unrealized_profit

    except Exception as e:
        print("upbit", f"미실현 이익 계산 중 오류 발생: {e}")
        return None
