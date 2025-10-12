"""GRID OKX 포지션 조회 (하위 호환성)

이 파일은 하위 호환성을 위해 유지되며, shared.exchange를 사용합니다.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio

from shared.exchange.okx.client import OKXClient
from shared.exchange_apis import exchange_store
from shared.helpers.cache_helper import cache_expired

CACHE_TIME_SECONDS = 35

okx_futures_account_balance_cache = None
okx_futures_account_balance_cache_expiry = datetime.now()
okx_futures_mark_price_cache = None
okx_futures_mark_price_cache_expiry = datetime.now()


def revalidate_okx_cache():
    """OKX 캐시 무효화"""
    global okx_futures_account_balance_cache, okx_futures_account_balance_cache_expiry
    global okx_futures_mark_price_cache, okx_futures_mark_price_cache_expiry

    okx_futures_account_balance_cache = None
    okx_futures_account_balance_cache_expiry = datetime.now()
    okx_futures_mark_price_cache = None
    okx_futures_mark_price_cache_expiry = datetime.now()


async def get_okx_futures_account_balance():
    """OKX 선물 계좌 잔고 조회"""
    global okx_futures_account_balance_cache, okx_futures_account_balance_cache_expiry

    okx_client = exchange_store.get_okx_instance()

    try:
        if ((not cache_expired(okx_futures_account_balance_cache_expiry))
                and (okx_futures_account_balance_cache is not None)):
            return okx_futures_account_balance_cache

        try:
            futures_account_balance = await okx_client.fetch_balance(params={})
            okx_futures_account_balance_cache = futures_account_balance
            okx_futures_account_balance_cache_expiry = datetime.now() + timedelta(
                seconds=CACHE_TIME_SECONDS
            )
        except Exception as e:
            print(f"An error occurred while fetching okx futures account balance: {e}")
            raise e
        return futures_account_balance

    except Exception as e:
        print('[EXCEPTION get_okx_balances]', e)
        raise ValueError(f"OKX 계좌를 불러오지 못했습니다. {e}")

    finally:
        if okx_client is not None:
            await okx_client.close()


async def get_okx_wallet():
    """OKX 지갑 정보 조회"""
    try:
        balance_info = await get_okx_futures_account_balance()

        total_balance = float(balance_info['total']['USDT'])
        wallet_balance = float(balance_info['free']['USDT'])
        total_unrealized_profit = 0.0

        if 'info' in balance_info and balance_info['info']['data']:
            for detail in balance_info['info']['data'][0]['details']:
                upl = float(detail.get('upl', '0'))
                total_unrealized_profit += upl

        return total_balance, wallet_balance, total_unrealized_profit
    except Exception as e:
        print("okx", f"선물 계좌 잔고 정보 업데이트 중 오류 발생: {e}")
        raise e


async def get_okx_tickers():
    """OKX 티커 정보 조회"""
    global okx_futures_mark_price_cache, okx_futures_mark_price_cache_expiry

    client = exchange_store.get_okx_instance()

    try:
        if ((not cache_expired(okx_futures_mark_price_cache_expiry))
                and (okx_futures_mark_price_cache is not None)):
            return okx_futures_mark_price_cache

        tickers = await client.fetch_tickers(params={'productType': 'swap'})
        okx_futures_mark_price_cache = tickers
        okx_futures_mark_price_cache_expiry = datetime.now() + timedelta(
            seconds=CACHE_TIME_SECONDS
        )
        return tickers
    except Exception as e:
        raise ValueError(f"OKX 마켓 정보를 불러오지 못했습니다. {e}")
    finally:
        if client is not None:
            await client.close()


async def fetch_okx_positions():
    """OKX 포지션 조회"""
    print('[FETCH OKX POSITIONS]')
    exchange = exchange_store.get_okx_instance()
    positions: list[dict] = []

    try:
        balance = await exchange.private_get_account_positions()
        print(balance)
        mark_price_data = await get_okx_tickers()

        if (balance is None) or (mark_price_data is None):
            return positions
    except Exception as e:
        print('[FETCH OKX POSITION ERROR]', e)
        raise e
    finally:
        await exchange.close()

    for position in balance['data']:
        if 'instId' in position:
            symbol = position['instId']
            entry_price = float(position['avgPx'])
            quantity = float(position['pos'])
            leverage = float(position['lever'])

            mark_price = float(position['markPx'])
            if mark_price is None or entry_price == 0:
                profit_percent = 0.0
                value = 0.0
            else:
                value = abs(quantity) * mark_price
                if quantity > 0:  # 롱 포지션
                    profit_percent = (mark_price - entry_price) / entry_price * 100 * leverage
                else:  # 숏 포지션
                    profit_percent = (entry_price - mark_price) / entry_price * 100 * leverage

            if quantity != 0:
                positions.append({
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'quantity': quantity,
                    'mark_price': mark_price,
                    'value': value,
                    'profit_percent': profit_percent,
                })
            print(positions)
            return positions


if __name__ == "__main__":
    print('main 실행')
    asyncio.run(get_okx_futures_account_balance())
