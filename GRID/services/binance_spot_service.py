from datetime import datetime, timedelta
from typing import Any

from shared.exchange_apis import exchange_store
from shared.helpers.cache_helper import cache_expired

CACHE_TIME_SECONDS = 25

binance_spot_account_balance_cache: Any = None
binance_spot_account_balance_cache_expiry = datetime.now()
binance_spot_mark_price_cache: Any = None
binance_spot_mark_price_cache_expiry = datetime.now()


def revalidate_binance_spot_cache():
    global binance_spot_account_balance_cache, binance_spot_account_balance_cache_expiry, binance_spot_mark_price_cache, binance_spot_mark_price_cache_expiry

    binance_spot_account_balance_cache = None
    binance_spot_account_balance_cache_expiry = datetime.now()
    binance_spot_mark_price_cache = None
    binance_spot_mark_price_cache_expiry = datetime.now()


# 바이낸스 현물 계좌 잔고 정보
async def get_binance_spot_account_balance():
    # Todo: refactor after
    global binance_spot_account_balance_cache, binance_spot_account_balance_cache_expiry
    binance_spot_client = exchange_store.get_binance_spot_instance()

    try:
        if ((not cache_expired(binance_spot_account_balance_cache_expiry))
                and (binance_spot_account_balance_cache is not None)):
            return binance_spot_account_balance_cache

        spot_account_balance = await binance_spot_client.fetch_balance()
        binance_spot_account_balance_cache = spot_account_balance
        binance_spot_account_balance_cache_expiry = datetime.now() + timedelta(seconds=CACHE_TIME_SECONDS)
        return spot_account_balance

    except Exception as e:
        print('[EXCEPTION get_binance_spotbalances]', e)
        raise ValueError(f"바이낸스 계좌를 불러오지 못했습니다. {e}")

    finally:
        await binance_spot_client.close()


async def get_binance_spot_wallet():
    try:
        balance_info = await get_binance_spot_account_balance()
        
        # 'USDT', 'USDC', 'BUSD'의 잔액만 합산
        usdt_balance = balance_info['free'].get('USDT', 0)
        usdc_balance = balance_info['free'].get('USDC', 0)
        busd_balance = balance_info['free'].get('BUSD', 0)
        
        total_balance = usdt_balance + usdc_balance + busd_balance
        total_wallet_balance = total_balance
        total_unrealized_profit = 0  # 미실현 이익은 0으로 설정
        
        return total_balance, total_wallet_balance, total_unrealized_profit
    except Exception as e:
        print("binance", f"현물 계좌 잔고 정보 업데이트 중 오류 발생: {e}")
        raise e


async def get_binance_spot_tickers():
    # Todo: refactor after
    global binance_spot_mark_price_cache, binance_spot_mark_price_cache_expiry
    client = exchange_store.get_binance_spot_instance()

    try:
        if ((not cache_expired(binance_spot_mark_price_cache_expiry))
                and (binance_spot_mark_price_cache is not None)):
            return binance_spot_mark_price_cache

        tickers = await client.fetch_tickers()
        binance_spot_mark_price_cache = tickers
        binance_spot_mark_price_cache_expiry = datetime.now() + timedelta(seconds=CACHE_TIME_SECONDS)
        return tickers

    except Exception as e:
        raise ValueError(f"바이낸스 마켓 정보를 불러오지 못했습니다. {e}")

    finally:
        await client.close()


async def fetch_binance_spot_positions():
    print('[FETCH BINACE SPOT POSITIONS]')
    exchange = exchange_store.get_binance_spot_instance()
    positions: list[Any] = []

    try:
        balance = await get_binance_spot_account_balance()
        mark_price_data = await get_binance_spot_tickers()
        if (balance is None) or (mark_price_data is None):
            return positions
        print(balance['info'])
        position_info_data = balance['total']
        for asset, total_balance in position_info_data.items():
            if total_balance <= 0:
                continue


            symbol = f"{asset}/USDT"
            mark_price = mark_price_data.get(symbol, {}).get('last', None)

            if mark_price is None:
                value = 0
                profit_percent = 0
            else:
                value = total_balance * mark_price
                profit_percent = 0  # 미실현 이익을 계산할 필요가 없는 경우 0으로 설정

            positions.append({
                'symbol': symbol,
                'total_balance': total_balance,
                'mark_price': mark_price,
                'value': value,
                'profit_percent': profit_percent,
            })

        return positions
    except Exception as e:
        print('[FETCH BINANCE SPOT POSITION ERROR]', e)
        raise e
    finally:
        await exchange.close()
