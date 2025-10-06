from GRID.api.apilist import telegram_store
from GRID.dtos.telegram import TelegramTokenDto


def set_telegram_id(telegram_id: str) -> None:
    telegram_store.set_telegram_id(telegram_id)


def get_telegram_id() -> str:
    result: str = telegram_store.get_telegram_id()
    return result


def set_telegram_token(dto: TelegramTokenDto) -> None:
    exchange_name = dto.exchange_name
    token = dto.token

    if exchange_name == 'binance':
        telegram_store.set_binance_token(token)
    elif exchange_name == 'binance_spot':
        telegram_store.set_binance_token(token)
    elif exchange_name == 'upbit':
        telegram_store.set_upbit_token(token)
    elif exchange_name == 'bitget':
        telegram_store.set_bitget_token(token)
    elif exchange_name == 'okx':
        telegram_store.set_okx_token(token)
    elif exchange_name == 'bitget_spot':
        telegram_store.set_bitget_token(token)
    elif exchange_name == 'okx_spot':
        telegram_store.set_okx_token(token)
    else:
        raise Exception('Unknown exchange')


def get_telegram_token(exchange_name: str) -> str:
    print('[GET TELEGRAM TOKEN EXCHANGE_NAME]', exchange_name)
    result: str
    if exchange_name == 'binance':
        result = telegram_store.get_binance_token()
    elif exchange_name == 'binance_spot':
        result = telegram_store.get_binance_token()
    elif exchange_name == 'upbit':
        result = telegram_store.get_upbit_token()
    elif exchange_name == 'bitget':
        result = telegram_store.get_bitget_token()
    elif exchange_name == 'okx':
        result = telegram_store.get_okx_token()
    elif exchange_name == 'bitget_spot':
        result = telegram_store.get_bitget_token()
    elif exchange_name == 'okx_spot':
        result = telegram_store.get_okx_token()
    else:
        raise Exception('Unknown exchange')
    return result
