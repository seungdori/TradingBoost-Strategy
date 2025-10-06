from datetime import datetime, timedelta
from shared.exchange_apis import exchange_store
from shared.helpers.cache_helper import cache_expired
from typing import Any

CACHE_TIME_SECONDS = 30
AVG_PRICE_CACHE_TIME_SECONDS = 30

upbit_balances_cache: Any = None
upbit_balances_cache_expiry = datetime.now()
upbit_tickers_cache: Any = None
upbit_tickers_cache_expiry = datetime.now()
upbit_avg_price_cache: Any = None
upbit_avg_price_cache_expiry = datetime.now()


def revalidate_upbit_cache():
    global upbit_balances_cache, upbit_balances_cache_expiry, upbit_tickers_cache, upbit_tickers_cache_expiry, upbit_avg_price_cache, upbit_avg_price_cache_expiry

    upbit_balances_cache = None
    upbit_balances_cache_expiry = datetime.now()
    upbit_tickers_cache = None
    upbit_tickers_cache_expiry = datetime.now()
    upbit_avg_price_cache = None
    upbit_avg_price_cache_expiry = datetime.now()


async def get_upbit_tickers():
    # Todo: refactor after
    global upbit_tickers_cache, upbit_tickers_cache_expiry
    upbit_client = exchange_store.get_upbit_instance()

    try:
        if (not cache_expired(upbit_tickers_cache_expiry)) and (upbit_tickers_cache is not None):
            return upbit_tickers_cache

        # exchange = exchange_store.get_upbit_instance()
        tickers = await upbit_client.fetch_tickers()
        upbit_tickers_cache = tickers
        upbit_tickers_cache_expiry = datetime.now() + timedelta(seconds=CACHE_TIME_SECONDS)
        return upbit_tickers_cache

    except Exception as e:
        raise ValueError(f"업비트 마켓 정보를 불러오지 못했습니다. {e}")

    finally:
        await upbit_client.close()


async def get_upbit_balances():
    # Todo: refactor after
    global upbit_balances_cache, upbit_balances_cache_expiry
    upbit_client = exchange_store.get_upbit_instance()

    try:
        if (not cache_expired(upbit_balances_cache_expiry)) and (upbit_balances_cache is not None):
            return upbit_balances_cache

        balances = await upbit_client.fetch_balance()
        upbit_balances_cache = balances
        upbit_balances_cache_expiry = datetime.now() + timedelta(seconds=CACHE_TIME_SECONDS)
        return upbit_balances_cache

    except Exception as e:
        raise ValueError(f"업비트 계좌를 불러오지 못했습니다. {e}")

    finally:
        await upbit_client.close()


async def fetch_upbit_avg_price():
    global upbit_avg_price_cache, upbit_avg_price_cache_expiry

    if not (cache_expired(upbit_avg_price_cache_expiry)) and (upbit_avg_price_cache is not None):
        return upbit_avg_price_cache

    try:
        balance_data = await get_upbit_balances()
        global_avg_price_cache = {
            item['currency']: item['avg_buy_price']
            for item in balance_data['info']
            if 'currency' in item and 'avg_buy_price' in item and item['balance'] != '0'
        }

        # 캐시 만료 시간을 10초로 설정
        upbit_avg_price_cache_expiry = datetime.now() + timedelta(seconds=AVG_PRICE_CACHE_TIME_SECONDS)

        return global_avg_price_cache

    except Exception as e:
        print('[FETCH UPBIT AVG PRICE ERROR]', e)
        raise e


async def fetch_upbit_positions():
    positions: list[Any] = []

    try:
        balances = await get_upbit_balances()
        tickers = await get_upbit_tickers()

        if (balances is None) or (tickers is None):
            return positions

        avg_prices = {
            item['currency']: item['avg_buy_price']
            for item in balances['info']
            if 'currency' in item and 'avg_buy_price' in item and item['balance'] != '0'
        }

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
                    'balance': str(balance),
                    'avg_buy_price': avg_prices[currency],
                }
                positions.append(spot_data)

        return positions
    except Exception as e:
        raise e


async def get_upbit_wallet():
    try:
        balance_info = await get_upbit_balances()
        tickers = await get_upbit_tickers()
        total_balance: float = 0
        krw_balance: float = 0

        if balance_info is None or tickers is None:
            return total_balance, krw_balance

        krw_balance = float(balance_info['total'].get('KRW', 0))
        total_balance += krw_balance

        for currency, balance in balance_info['total'].items():
            if balance > 0 and currency != "KRW":
                symbol = f'{currency}/KRW'
                if symbol in tickers:  # 업비트에서 지원하는 통화 쌍만 처리합니다.
                    ticker = tickers[symbol]
                    total_balance += balance * ticker['last']

        return total_balance, krw_balance


    except Exception as e:
        print("upbit", f"총 잔고 계산 중 오류 발생: {e}")
        raise e
