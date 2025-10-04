from dotenv import load_dotenv

import os

load_dotenv()



class TelegramStore:
    __telegram_id: str
    __binance_token: str
    __upbit_token: str
    __bitget_token: str

    def __init__(self):
        self.__telegram_id = '1709556958'
        self.__binance_token = '6896659435:AAHn47_AzhnqoGoC1k8euqb0ca96pqO9_p8'
        self.__upbit_token = '6361283148:AAF3W0njouzhzRZjNt0ZsXwaTgZw2BLiE3U'
        self.__bitget_token = '6468139319:AAFahdVubywE64CEdireFSNUYej6tl3StDw'
        self.__okx_token = '7159235181:AAH2t1wVV3JynlR6ruzqCgCeH-0hjHhV20Y'

    def set_telegram_id(self, telegram_id: str):
        self.__telegram_id = telegram_id

    def set_binance_token(self, token: str):
        self.__binance_token = token

    def set_upbit_token(self, token: str):
        self.__upbit_token = token


    def set_bitget_token(self, token: str):
        self.__bitget_token = token

    def set_okx_token(self, token: str):
        self.__okx_token = token

    def get_telegram_id(self) -> str:
        return self.__telegram_id

    def get_binance_token(self) -> str:
        return self.__binance_token

    def get_upbit_token(self) -> str:
        return self.__upbit_token

    
    def get_bitget_token(self) -> str:
        return self.__bitget_token
    
    def get_okx_token(self) -> str:
        return self.__okx_token


DEFAULT_DEBUG_TELEGRAM_ID = '1709556958'
DEBUG_TELEGRAM_ID = os.getenv('DEBUG_TELEGRAM_ID') if os.getenv('DEBUG_TELEGRAM_ID') else DEFAULT_DEBUG_TELEGRAM_ID

# telegram_store 인스턴스에서 텔레그램 ID와 토큰을 관리합니다.
telegram_store = TelegramStore()