"""지갑 정보 처리 헬퍼 함수

거래소 지갑 정보 조회 및 처리를 위한 공통 함수
"""
from typing import Dict, Tuple
from shared.logging import get_logger

logger = get_logger(__name__)


def extract_binance_wallet_info(balance_info: Dict) -> Tuple[float, float, float]:
    """
    Binance 지갑 정보 추출

    Args:
        balance_info: Binance 잔고 데이터

    Returns:
        Tuple[float, float, float]: (총 잔고, 지갑 잔고, 미실현 손익)
    """
    try:
        total_balance = float(balance_info['info']['totalMarginBalance'])
        wallet_balance = float(balance_info['info']['totalWalletBalance'])
        unrealized_profit = float(balance_info['info']['totalUnrealizedProfit'])
        return total_balance, wallet_balance, unrealized_profit
    except Exception as e:
        logger.error(f"Error extracting Binance wallet info: {e}")
        return 0.0, 0.0, 0.0


def extract_okx_wallet_info(balance_info: Dict) -> Tuple[float, float, float]:
    """
    OKX 지갑 정보 추출

    Args:
        balance_info: OKX 잔고 데이터

    Returns:
        Tuple[float, float, float]: (총 잔고, 지갑 잔고, 미실현 손익)
    """
    try:
        total_balance = float(balance_info['total']['USDT'])
        wallet_balance = float(balance_info['free']['USDT'])
        total_unrealized_profit = 0.0

        if 'info' in balance_info and balance_info['info']['data']:
            for detail in balance_info['info']['data'][0]['details']:
                upl = float(detail.get('upl', '0'))
                total_unrealized_profit += upl

        return total_balance, wallet_balance, total_unrealized_profit
    except Exception as e:
        logger.error(f"Error extracting OKX wallet info: {e}")
        return 0.0, 0.0, 0.0


def extract_upbit_wallet_info(balance_info: Dict, tickers: Dict) -> Tuple[float, float]:
    """
    Upbit 지갑 정보 추출

    Args:
        balance_info: Upbit 잔고 데이터
        tickers: 시세 데이터

    Returns:
        Tuple[float, float]: (총 잔고, KRW 잔고)
    """
    try:
        total_balance = 0.0
        krw_balance = float(balance_info['total'].get('KRW', 0))
        total_balance += krw_balance

        for currency, balance in balance_info['total'].items():
            if balance > 0 and currency != "KRW":
                symbol = f'{currency}/KRW'
                if symbol in tickers:
                    ticker = tickers[symbol]
                    total_balance += balance * ticker['last']

        return total_balance, krw_balance
    except Exception as e:
        logger.error(f"Error extracting Upbit wallet info: {e}")
        return 0.0, 0.0


def extract_bitget_wallet_info(balance_info: Dict) -> Tuple[float, float, float]:
    """
    Bitget 지갑 정보 추출

    Args:
        balance_info: Bitget 잔고 데이터

    Returns:
        Tuple[float, float, float]: (총 잔고, 지갑 잔고, 미실현 손익)
    """
    try:
        # Bitget의 경우 Binance와 유사한 구조로 가정
        total_balance = float(balance_info.get('total', {}).get('USDT', 0))
        wallet_balance = float(balance_info.get('free', {}).get('USDT', 0))
        unrealized_profit = 0.0

        # Info에서 미실현 손익 추출 (구조에 따라 조정 필요)
        if 'info' in balance_info:
            unrealized_profit = float(balance_info['info'].get('totalUnrealizedProfit', 0))

        return total_balance, wallet_balance, unrealized_profit
    except Exception as e:
        logger.error(f"Error extracting Bitget wallet info: {e}")
        return 0.0, 0.0, 0.0
