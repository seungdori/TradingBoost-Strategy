from datetime import datetime, timedelta

from shared.exchange_apis import exchange_store
from shared.helpers.cache_helper import cache_expired

CACHE_TIME_SECONDS = 25

bitget_spot_account_balance_cache = None
bitget_spot_account_balance_cache_expiry = datetime.now()
bitget_spot_mark_price_cache = None
bitget_spot_mark_price_cache_expiry = datetime.now()


def revalidate_bitget_spot_cache():
    global bitget_spot_account_balance_cache, bitget_spot_account_balance_cache_expiry, bitget_spot_mark_price_cache, bitget_spot_mark_price_cache_expiry

    bitget_spot_account_balance_cache = None
    bitget_spot_account_balance_cache_expiry = datetime.now()
    bitget_spot_mark_price_cache = None
    bitget_spot_mark_price_cache_expiry = datetime.now()


# 비트겟 현물 계좌 잔고 정보
async def get_bitget_spot_account_balance():
    # Todo: refactor after
    global bitget_spot_account_balance_cache, bitget_spot_account_balance_cache_expiry

    bitget_spot_client = exchange_store.get_bitget_spot_instance()

    try:
        if ((not cache_expired(bitget_spot_account_balance_cache_expiry))
                and (bitget_spot_account_balance_cache is not None)):
            return bitget_spot_account_balance_cache
        else:
            account_balance = await bitget_spot_client.fetch_balance(params={})
            bitget_spot_account_balance_cache = account_balance
            bitget_spot_account_balance_cache_expiry = datetime.now() + timedelta(seconds=CACHE_TIME_SECONDS)
            return account_balance
    except Exception as e:
        print('[EXCEPTION get_bitget_spot_balances]', e)
        raise ValueError(f"비트겟 계좌를 불러오지 못했습니다. {e}")

    finally:
        if bitget_spot_client is not None:
            await bitget_spot_client.close()


async def get_bitget_spot_wallet():
    try:
        balance_info = await get_bitget_spot_account_balance()
        
        # USDT 잔액 정보 추출
        usdt_balance_info = balance_info['total'].get('USDT', {})
        free_usdt_balance_info = balance_info['free'].get('USDT', {})
        
        total_balance = usdt_balance_info.get('total', 0)
        wallet_balance = free_usdt_balance_info.get('free', 0)
        
        # 미실현 이익을 항상 0으로 설정 (현물 계정에 해당 값이 없으므로)
        total_unrealized_profit = 0
        
        return total_balance, wallet_balance, total_unrealized_profit
    except Exception as e:
        print("bitget", f"현물 계좌 잔고 정보 업데이트 중 오류 발생: {e}")
        raise e


async def get_bitget_spot_tickers():
    # Todo: refactor after
    global bitget_spot_mark_price_cache, bitget_spot_mark_price_cache_expiry

    client = exchange_store.get_bitget_spot_instance()

    try:
        if ((not cache_expired(bitget_spot_mark_price_cache_expiry))
                and (bitget_spot_mark_price_cache is not None)):
            return bitget_spot_mark_price_cache
        else:
            tickers = await client.fetch_tickers(params={'productType': 'USDT-FUTURES'})
            bitget_spot_mark_price_cache = tickers
            bitget_spot_mark_price_cache_expiry = datetime.now() + timedelta(seconds=CACHE_TIME_SECONDS)
            return tickers
    except Exception as e:
        raise ValueError(f"비트겟 마켓 정보를 불러오지 못했습니다. {e}")
    finally:
        if client is not None:
            await client.close()


async def fetch_bitget_spot_positions():
    print('[FETCH BITGET POSITIONS]')
    exchange = exchange_store.get_bitget_spot_instance()
    positions = []

    try:
        balance = await get_bitget_spot_account_balance()
        mark_price_data = await get_bitget_spot_tickers()

        if (balance is None) or (mark_price_data is None):
            return positions

        position_info_data = balance['info']['positions']

        for position in position_info_data:
            symbol = position['symbol']
            if not symbol.endswith('USDT_UMCBL'):
                continue

            entry_price = float(position['averageOpenPrice'])
            quantity = float(position['total'])
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
        print('[FETCH BITGET POSITION ERROR]', e)
        raise e
    finally:
        await exchange.close()
