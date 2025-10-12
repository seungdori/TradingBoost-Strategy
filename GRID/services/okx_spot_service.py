import asyncio
import os
import sys
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.exchange_apis import exchange_store
from shared.helpers.cache_helper import cache_expired

CACHE_TIME_SECONDS = 35

okx_spot_account_balance_cache = None
okx_spot_account_balance_cache_expiry = datetime.now()
okx_spot_mark_price_cache = None
okx_spot_mark_price_cache_expiry = datetime.now()


def revalidate_okx_spot_cache():
    global okx_spot_account_balance_cache, okx_spot_account_balance_cache_expiry, okx_spot_mark_price_cache, okx_spot_mark_price_cache_expiry

    okx_spot_account_balance_cache = None
    okx_spot_account_balance_cache_expiry = datetime.now()
    okx_spot_mark_price_cache = None
    okx_spot_mark_price_cache_expiry = datetime.now()

async def get_okx_spot_account_balance():
    global okx_spot_account_balance_cache, okx_spot_account_balance_cache_expiry
    try:
        okx_spot_client = exchange_store.get_okx_instance()
    except Exception as e:
        print('[EXCEPTION get_okx_spot_account_balance]', e)
        raise ValueError(f"OKX 계좌를 불러오지 못했습니다. {e}")

    try:
        if ((not cache_expired(okx_spot_account_balance_cache_expiry))
                and (okx_spot_account_balance_cache is not None)):
            return okx_spot_account_balance_cache  # type: ignore[unreachable]

        futures_account_balance = await okx_spot_client.fetch_balance(params={})
        okx_spot_account_balance_cache = futures_account_balance
        okx_spot_account_balance_cache_expiry = datetime.now() + timedelta(seconds=CACHE_TIME_SECONDS)
        return futures_account_balance
    except Exception as e:
        print('[EXCEPTION get_okx_balances]', e)
        raise ValueError(f"OKX 계좌를 불러오지 못했습니다. {e}")

    finally:
        if okx_spot_client is not None:
            await okx_spot_client.close()


async def get_okx_spot_wallet():

    try:
        balance_info = await get_okx_spot_account_balance()

        total_balance = float(balance_info['total']['USDT'])
        wallet_balance = float(balance_info['free']['USDT'])
        total_unrealized_profit = 0.0

        # Assuming 'unrealizedPL' corresponds to 'upl' in the new data structure
        if 'info' in balance_info and balance_info['info']['data']:
            for detail in balance_info['info']['data'][0]['details']:
                # 문자열 'upl' 값을 실수로 변환하여 합산
                upl = float(detail.get('upl', '0'))
                total_unrealized_profit += upl
        return total_balance, wallet_balance, total_unrealized_profit
    except Exception as e:
        print("okx", f"현물 계좌 잔고 정보 업데이트 중 오류 발생: {e}")
        raise e


async def get_okx_spot_tickers():
    # Todo: refactor after
    global okx_spot_mark_price_cache, okx_spot_mark_price_cache_expiry

    client = exchange_store.get_okx_instance()

    try:
        if ((not cache_expired(okx_spot_mark_price_cache_expiry))
                and (okx_spot_mark_price_cache is not None)):
            return okx_spot_mark_price_cache  # type: ignore[unreachable]

        tickers = await client.fetch_tickers()
        okx_spot_mark_price_cache = tickers
        okx_spot_mark_price_cache_expiry = datetime.now() + timedelta(seconds=CACHE_TIME_SECONDS)
        return tickers
    except Exception as e:
        raise ValueError(f"OKX 마켓 정보를 불러오지 못했습니다. {e}")
    finally:
        if client is not None:
            await client.close()


async def fetch_okx_spot_positions():

    print('[FETCH OKX POSITIONS]')
    exchange = exchange_store.get_okx_instance()
    positions: list[dict] = []

    try:
        balance = await exchange.fetch_balance()
        mark_price_data = await get_okx_spot_tickers()

        if (balance is None) or (mark_price_data is None):
            return positions
    except Exception as e:
        print('[FETCH OKX POSITION ERROR]', e)
        raise e
    finally:
        if exchange is not None:
            await exchange.close()
        for entry in balance['info']['data']:
            for detail in entry['details']:
                currency = detail['ccy']
                total_amount = float(detail['eq'])
                free_amount = float(detail['availBal'])
                used_amount = total_amount - free_amount

                if total_amount > 0:
                    positions.append({
                        'currency': currency,
                        'total': total_amount,
                        'free': free_amount,
                        'used': used_amount
                    })
        
            return positions



if __name__ == "__main__":
    print('main 실행')
    asyncio.run(fetch_okx_spot_positions())
