"""거래소 심볼 변환 유틸리티"""
import re
from typing import Optional, Tuple


def okx_to_ccxt_symbol(okx_symbol: str) -> str:
    """
    OKX 심볼을 CCXT 형식으로 변환

    Args:
        okx_symbol: OKX 심볼 (예: "BTC-USDT-SWAP")

    Returns:
        CCXT 심볼 (예: "BTC/USDT:USDT")

    Examples:
        >>> okx_to_ccxt_symbol("BTC-USDT-SWAP")
        "BTC/USDT:USDT"
        >>> okx_to_ccxt_symbol("ETH-USDT")
        "ETH/USDT"
    """
    if "-SWAP" in okx_symbol:
        # 선물: BTC-USDT-SWAP -> BTC/USDT:USDT
        base, quote, _ = okx_symbol.split("-")
        return f"{base}/{quote}:{quote}"
    else:
        # 현물: BTC-USDT -> BTC/USDT
        return okx_symbol.replace("-", "/")


def ccxt_to_okx_symbol(ccxt_symbol: str, is_swap: bool = False) -> str:
    """
    CCXT 심볼을 OKX 형식으로 변환

    Args:
        ccxt_symbol: CCXT 심볼 (예: "BTC/USDT" 또는 "BTC/USDT:USDT")
        is_swap: 선물 여부

    Returns:
        OKX 심볼 (예: "BTC-USDT-SWAP" 또는 "BTC-USDT")

    Examples:
        >>> ccxt_to_okx_symbol("BTC/USDT", is_swap=True)
        "BTC-USDT-SWAP"
        >>> ccxt_to_okx_symbol("BTC/USDT:USDT")
        "BTC-USDT-SWAP"
    """
    # BTC/USDT:USDT 형식 처리
    if ":" in ccxt_symbol:
        ccxt_symbol = ccxt_symbol.split(":")[0]
        is_swap = True

    okx_symbol = ccxt_symbol.replace("/", "-")

    if is_swap and not okx_symbol.endswith("-SWAP"):
        okx_symbol += "-SWAP"

    return okx_symbol


def convert_symbol_to_okx_instrument(symbol: str) -> str:
    """
    심볼을 OKX 인스트루먼트 ID로 변환

    Args:
        symbol: 심볼 (CCXT 형식)

    Returns:
        OKX 인스트루먼트 ID

    Examples:
        >>> convert_symbol_to_okx_instrument("BTC/USDT:USDT")
        "BTC-USDT-SWAP"
        >>> convert_symbol_to_okx_instrument("ETH/USDT")
        "ETH-USDT"
    """
    # Use ccxt_to_okx_symbol for proper conversion
    return ccxt_to_okx_symbol(symbol)


def parse_symbol(
    symbol: str,
    exchange: str = "okx"
) -> Tuple[str, str, bool]:
    """
    심볼을 파싱하여 base, quote, is_swap 반환

    Args:
        symbol: 거래 심볼
        exchange: 거래소 이름 (okx, ccxt, binance 등)

    Returns:
        (base_currency, quote_currency, is_swap)

    Examples:
        >>> parse_symbol("BTC-USDT-SWAP", "okx")
        ("BTC", "USDT", True)
        >>> parse_symbol("BTC/USDT", "ccxt")
        ("BTC", "USDT", False)
        >>> parse_symbol("BTC/USDT:USDT", "ccxt")
        ("BTC", "USDT", True)
    """
    if exchange.lower() == "okx":
        parts = symbol.split("-")
        if len(parts) == 3 and parts[2] == "SWAP":
            return parts[0], parts[1], True
        elif len(parts) == 2:
            return parts[0], parts[1], False
        else:
            raise ValueError(f"Invalid OKX symbol format: {symbol}")
    else:
        # CCXT format
        if ":" in symbol:
            base_quote, _ = symbol.split(":")
            base, quote = base_quote.split("/")
            return base, quote, True
        else:
            base, quote = symbol.split("/")
            return base, quote, False


def normalize_symbol(symbol: str, target_format: str = "okx") -> str:
    """
    심볼을 지정된 형식으로 정규화

    Args:
        symbol: 입력 심볼 (다양한 형식)
        target_format: 목표 형식 ("okx", "ccxt", "binance")

    Returns:
        정규화된 심볼

    Examples:
        >>> normalize_symbol("BTC-USDT-SWAP", "ccxt")
        "BTC/USDT:USDT"
        >>> normalize_symbol("BTC/USDT:USDT", "okx")
        "BTC-USDT-SWAP"
        >>> normalize_symbol("BTC/USDT", "binance")
        "BTCUSDT"
    """
    # 먼저 파싱
    try:
        # OKX 형식 시도
        base, quote, is_swap = parse_symbol(symbol, "okx")
    except ValueError:
        try:
            # CCXT 형식 시도
            base, quote, is_swap = parse_symbol(symbol, "ccxt")
        except ValueError:
            raise ValueError(f"Cannot parse symbol: {symbol}")

    # 목표 형식으로 변환
    if target_format.lower() == "okx":
        result = f"{base}-{quote}"
        if is_swap:
            result += "-SWAP"
        return result
    elif target_format.lower() == "ccxt":
        result = f"{base}/{quote}"
        if is_swap:
            result += f":{quote}"
        return result
    elif target_format.lower() == "binance":
        return f"{base}{quote}"
    else:
        raise ValueError(f"Unknown target format: {target_format}")


def is_valid_symbol(symbol: str, exchange: str = "okx") -> bool:
    """
    심볼 유효성 검증

    Args:
        symbol: 검증할 심볼
        exchange: 거래소 이름

    Returns:
        유효성 여부

    Examples:
        >>> is_valid_symbol("BTC-USDT-SWAP", "okx")
        True
        >>> is_valid_symbol("INVALID", "okx")
        False
    """
    try:
        parse_symbol(symbol, exchange)
        return True
    except (ValueError, AttributeError):
        return False


def extract_base_currency(symbol: str) -> str:
    """
    심볼에서 기본 통화 추출

    Args:
        symbol: 거래 심볼

    Returns:
        기본 통화

    Examples:
        >>> extract_base_currency("BTC-USDT-SWAP")
        "BTC"
        >>> extract_base_currency("BTC/USDT:USDT")
        "BTC"
    """
    try:
        base, _, _ = parse_symbol(symbol, "okx")
        return base
    except ValueError:
        try:
            base, _, _ = parse_symbol(symbol, "ccxt")
            return base
        except ValueError:
            # 마지막 시도: 단순 분리
            if "-" in symbol:
                return symbol.split("-")[0]
            elif "/" in symbol:
                return symbol.split("/")[0]
            else:
                return symbol


def extract_quote_currency(symbol: str) -> str:
    """
    심볼에서 견적 통화 추출

    Args:
        symbol: 거래 심볼

    Returns:
        견적 통화

    Examples:
        >>> extract_quote_currency("BTC-USDT-SWAP")
        "USDT"
        >>> extract_quote_currency("BTC/USDT:USDT")
        "USDT"
    """
    try:
        _, quote, _ = parse_symbol(symbol, "okx")
        return quote
    except ValueError:
        try:
            _, quote, _ = parse_symbol(symbol, "ccxt")
            return quote
        except ValueError:
            # 마지막 시도: 단순 분리
            if "-SWAP" in symbol:
                return symbol.replace("-SWAP", "").split("-")[1]
            elif "-" in symbol:
                return symbol.split("-")[1]
            elif ":" in symbol:
                return symbol.split(":")[0].split("/")[1]
            elif "/" in symbol:
                return symbol.split("/")[1]
            else:
                return ""


def is_swap_symbol(symbol: str) -> bool:
    """
    선물/스왑 심볼인지 확인

    Args:
        symbol: 거래 심볼

    Returns:
        선물/스왑 여부

    Examples:
        >>> is_swap_symbol("BTC-USDT-SWAP")
        True
        >>> is_swap_symbol("BTC/USDT:USDT")
        True
        >>> is_swap_symbol("BTC-USDT")
        False
    """
    try:
        _, _, is_swap = parse_symbol(symbol, "okx")
        return is_swap
    except ValueError:
        try:
            _, _, is_swap = parse_symbol(symbol, "ccxt")
            return is_swap
        except ValueError:
            # 마지막 시도: 패턴 검사
            return "-SWAP" in symbol or ":" in symbol


def convert_to_trading_symbol(symbol: str) -> str:
    """
    일반 심볼(예: BTCUSDT)을 거래소 심볼 포맷(예: BTC-USDT-SWAP)으로 변환합니다.

    Args:
        symbol: 입력 심볼 (BTCUSDT 형식 또는 BTC-USDT-SWAP 형식)

    Returns:
        str: 거래소 심볼 포맷 (BTC-USDT-SWAP)

    Examples:
        >>> convert_to_trading_symbol("BTCUSDT")
        'BTC-USDT-SWAP'
        >>> convert_to_trading_symbol("BTC-USDT-SWAP")
        'BTC-USDT-SWAP'
    """
    import logging
    logger = logging.getLogger(__name__)

    # 이미 변환된 포맷인 경우
    if "-" in symbol and symbol.endswith("-SWAP"):
        return symbol

    # USDT를 기준으로 분리
    if "USDT" in symbol:
        base = symbol.replace("USDT", "")
        return f"{base}-USDT-SWAP"

    # 변환할 수 없는 경우 원본 반환
    logger.warning(f"심볼 변환 불가: {symbol}")
    return symbol
