from datetime import datetime, timedelta
from typing import Any

from shared.exchange_apis import exchange_store
from shared.helpers.cache_helper import cache_expired

CACHE_TIME_SECONDS = 25

binance_futures_account_balance_cache: Any = None
binance_futures_account_balance_cache_expiry = datetime.now()
binance_futures_mark_price_cache: Any = None
binance_futures_mark_price_cache_expiry = datetime.now()


def revalidate_binance_cache():
    global binance_futures_account_balance_cache, binance_futures_account_balance_cache_expiry, binance_futures_mark_price_cache, binance_futures_mark_price_cache_expiry

    binance_futures_account_balance_cache = None
    binance_futures_account_balance_cache_expiry = datetime.now()
    binance_futures_mark_price_cache = None
    binance_futures_mark_price_cache_expiry = datetime.now()


# 바이낸스 선물 계좌 잔고 정보
async def get_binance_futures_account_balance():
    # Todo: refactor after
    global binance_futures_account_balance_cache, binance_futures_account_balance_cache_expiry
    binance_client = exchange_store.get_binance_instance()

    try:
        if ((not cache_expired(binance_futures_account_balance_cache_expiry))
                and (binance_futures_account_balance_cache is not None)):
            return binance_futures_account_balance_cache

        futures_account_balance = await binance_client.fetch_balance()
        binance_futures_account_balance_cache = futures_account_balance
        binance_futures_account_balance_cache_expiry = datetime.now() + timedelta(seconds=CACHE_TIME_SECONDS)
        return futures_account_balance

    except Exception as e:
        print('[EXCEPTION get_binance_balances]', e)
        raise ValueError(f"바이낸스 계좌를 불러오지 못했습니다. {e}")

    finally:
        await binance_client.close()


async def get_binance_wallet():
    try:
        balance_info = await get_binance_futures_account_balance()
        total_balance = balance_info['info']['totalMarginBalance']  # 총 마진 잔액
        total_wallet_balance = balance_info['info']['totalWalletBalance']  # 전체 지갑 잔액
        total_unrealized_profit = balance_info['info']['totalUnrealizedProfit']  # 미실현 이익

        return total_balance, total_wallet_balance, total_unrealized_profit

    except Exception as e:
        print("binance", f"선물 계좌 잔고 정보 업데이트 중 오류 발생: {e}")
        raise e


async def get_binance_tickers():
    # Todo: refactor after
    global binance_futures_mark_price_cache, binance_futures_mark_price_cache_expiry
    client = exchange_store.get_binance_instance()

    try:
        if ((not cache_expired(binance_futures_mark_price_cache_expiry))
                and (binance_futures_mark_price_cache is not None)):
            return binance_futures_mark_price_cache

        tickers = await client.fetch_tickers()
        binance_futures_mark_price_cache = tickers
        binance_futures_mark_price_cache_expiry = datetime.now() + timedelta(seconds=CACHE_TIME_SECONDS)
        return tickers

    except Exception as e:
        raise ValueError(f"바이낸스 마켓 정보를 불러오지 못했습니다. {e}")

    finally:
        await client.close()


async def fetch_binance_positions():
    print('[FETCH BINACE POSITIONS]')
    exchange = exchange_store.get_binance_instance()
    positions: list[Any] = []

    try:
        balance = await get_binance_futures_account_balance()
        mark_price_data = await get_binance_tickers()
        if (balance is None) or (mark_price_data is None):
            return positions

        position_info_data = balance['info']['positions']
        for position in position_info_data:
            symbol = position['symbol']
            if not symbol.endswith('USDT'):
                continue

            entry_price = float(position['entryPrice'])
            quantity = float(position['positionAmt'])
            leverage = float(position['leverage'])
            mark_price = mark_price_data.get(symbol, {}).get('last', None)

            if mark_price is None or entry_price == 0:
                profit_percent = 0
                value = 0
            else:
                value = abs(quantity) * mark_price
                profit_percent = ((mark_price - entry_price) / entry_price * 100 * leverage) if quantity > 0 else (
                        (entry_price - mark_price) / entry_price * 100 * leverage)

            if quantity != 0:
                positions.append({
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'quantity': quantity,
                    'mark_price': mark_price,
                    'value': value,
                    'profit_percent': profit_percent,
                })

        return positions
    except Exception as e:
        print('[FETCH BINANCE POSITION ERROR]', e)
        raise e
    finally:
        await exchange.close()
