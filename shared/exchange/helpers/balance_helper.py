"""잔고 데이터 처리 헬퍼 함수

GRID와 HYPERRSI에서 공통으로 사용되는 잔고 데이터 처리 로직
"""
import json
from typing import Any, Dict, Optional

from shared.logging import get_logger

logger = get_logger(__name__)


def process_upbit_balance(balance: Dict[str, Any], symbol: str) -> float:
    """
    Upbit 잔고 데이터를 처리하여 특정 심볼의 사용 가능 잔고 반환

    Args:
        balance: 잔고 데이터
        symbol: 심볼 (예: 'KRW-BTC')

    Returns:
        float: 사용 가능 잔고
    """
    try:
        base_currency = symbol.split('-')[1]
        free_balance = balance['free'].get(base_currency, 0.0)
        logger.debug(f'{symbol} balance: {free_balance}')
        return float(free_balance) if free_balance else 0.0
    except Exception as e:
        logger.error(f"Error processing Upbit balance: {e}")
        return 0.0


def extract_balance_info(balance_data: Dict[str, Any], currency: str = "USDT") -> Dict[str, float]:
    """
    잔고 데이터에서 주요 정보 추출

    Args:
        balance_data: 거래소 잔고 데이터
        currency: 조회할 화폐 (기본값: USDT)

    Returns:
        Dict: 추출된 잔고 정보 {total, free, used}
    """
    try:
        return {
            'total': float(balance_data.get('total', {}).get(currency, 0)),
            'free': float(balance_data.get('free', {}).get(currency, 0)),
            'used': float(balance_data.get('used', {}).get(currency, 0)),
        }
    except Exception as e:
        logger.error(f"Error extracting balance info: {e}")
        return {'total': 0.0, 'free': 0.0, 'used': 0.0}


def calculate_total_balance(balance_data: Dict[str, Any], tickers: Dict[str, Any], base_currency: str = "KRW") -> float:
    """
    전체 잔고를 기준 화폐로 계산

    Args:
        balance_data: 잔고 데이터
        tickers: 시세 데이터
        base_currency: 기준 화폐 (기본값: KRW)

    Returns:
        float: 전체 잔고 (기준 화폐 기준)
    """
    total = 0.0

    try:
        # 기준 화폐 잔고
        total += float(balance_data.get('total', {}).get(base_currency, 0))

        # 다른 화폐 잔고를 기준 화폐로 환산
        for currency, balance in balance_data.get('total', {}).items():
            if currency != base_currency and balance > 0:
                symbol = f'{currency}/{base_currency}'
                if symbol in tickers:
                    price = tickers[symbol].get('last', 0)
                    total += balance * price

        return total
    except Exception as e:
        logger.error(f"Error calculating total balance: {e}")
        return 0.0
