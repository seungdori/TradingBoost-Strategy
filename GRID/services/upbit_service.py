"""Upbit 서비스 (통합 헬퍼 사용)

이 파일은 shared.exchange.helpers를 사용하도록 업데이트되었습니다.
"""
from datetime import datetime, timedelta
from typing import Any

from shared.exchange.helpers.wallet_helper import extract_upbit_wallet_info
from shared.exchange_apis import exchange_store
from shared.helpers.cache_helper import cache_expired

CACHE_TIME_SECONDS = 30
AVG_PRICE_CACHE_TIME_SECONDS = 30

upbit_balances_cache: Any = None
upbit_balances_cache_expiry = datetime.now()
upbit_tickers_cache: Any = None
upbit_tickers_cache_expiry = datetime.now()
upbit_avg_price_cache: Any = None
upbit_avg_price_cache_expiry = datetime.now()


def revalidate_upbit_cache():
    """Upbit 캐시 무효화"""
    global upbit_balances_cache, upbit_balances_cache_expiry
    global upbit_tickers_cache, upbit_tickers_cache_expiry
    global upbit_avg_price_cache, upbit_avg_price_cache_expiry

    upbit_balances_cache = None
    upbit_balances_cache_expiry = datetime.now()
    upbit_tickers_cache = None
    upbit_tickers_cache_expiry = datetime.now()
    upbit_avg_price_cache = None
    upbit_avg_price_cache_expiry = datetime.now()


async def get_upbit_tickers():
    """Upbit 티커 정보 조회"""
    global upbit_tickers_cache, upbit_tickers_cache_expiry
    upbit_client = exchange_store.get_upbit_instance()

    try:
        if (not cache_expired(upbit_tickers_cache_expiry)) and (upbit_tickers_cache is not None):
            return upbit_tickers_cache

        tickers = await upbit_client.fetch_tickers()
        upbit_tickers_cache = tickers
        upbit_tickers_cache_expiry = datetime.now() + timedelta(seconds=CACHE_TIME_SECONDS)
        return upbit_tickers_cache

    except Exception as e:
        raise ValueError(f"업비트 마켓 정보를 불러오지 못했습니다. {e}")

    finally:
        await upbit_client.close()


async def get_upbit_balances():
    """Upbit 잔고 조회"""
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
    """Upbit 평균 구매가 조회"""
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

        upbit_avg_price_cache_expiry = datetime.now() + timedelta(
            seconds=AVG_PRICE_CACHE_TIME_SECONDS
        )

        return global_avg_price_cache

    except Exception as e:
        print('[FETCH UPBIT AVG PRICE ERROR]', e)
        raise e


async def fetch_upbit_positions():
    """Upbit 포지션 조회"""
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
    """Upbit 지갑 정보 조회 (통합 헬퍼 사용)"""
    try:
        balance_info = await get_upbit_balances()
        tickers = await get_upbit_tickers()

        if balance_info is None or tickers is None:
            return 0.0, 0.0

        return extract_upbit_wallet_info(balance_info, tickers)

    except Exception as e:
        print("upbit", f"총 잔고 계산 중 오류 발생: {e}")
        raise e
