"""
Position Calculation Helpers

포지션 관련 계산 유틸리티 함수들
"""
from typing import Optional
from decimal import Decimal


def calculate_position_value(amount: float, price: float) -> Decimal:
    """
    포지션 가치 계산

    Args:
        amount: 수량
        price: 가격

    Returns:
        Decimal: 포지션 가치
    """
    return Decimal(str(amount)) * Decimal(str(price))


def calculate_close_amount(total_amount: float, close_percent: float) -> float:
    """
    종료할 수량 계산

    Args:
        total_amount: 전체 포지션 수량
        close_percent: 종료할 비율 (1-100)

    Returns:
        float: 종료할 수량
    """
    return total_amount * (close_percent / 100.0)


def calculate_pnl(
    entry_price: float,
    exit_price: float,
    amount: float,
    side: str
) -> Decimal:
    """
    PNL(손익) 계산

    Args:
        entry_price: 진입 가격
        exit_price: 청산 가격
        amount: 수량
        side: 포지션 사이드 (long/short)

    Returns:
        Decimal: 손익
    """
    entry = Decimal(str(entry_price))
    exit_val = Decimal(str(exit_price))
    amt = Decimal(str(amount))

    if side.lower() == "long":
        return (exit_val - entry) * amt
    else:  # short
        return (entry - exit_val) * amt


def calculate_pnl_percentage(
    entry_price: float,
    exit_price: float,
    side: str,
    leverage: int = 1
) -> Decimal:
    """
    PNL 퍼센트 계산

    Args:
        entry_price: 진입 가격
        exit_price: 청산 가격
        side: 포지션 사이드 (long/short)
        leverage: 레버리지 배수

    Returns:
        Decimal: 손익 퍼센트
    """
    entry = Decimal(str(entry_price))
    exit_val = Decimal(str(exit_price))
    lev = Decimal(str(leverage))

    if side.lower() == "long":
        price_change = (exit_val - entry) / entry
    else:  # short
        price_change = (entry - exit_val) / entry

    return price_change * lev * Decimal("100")


def calculate_liquidation_price(
    entry_price: float,
    leverage: int,
    side: str,
    maintenance_margin_rate: float = 0.004  # OKX 기본값 0.4%
) -> Decimal:
    """
    청산 가격 계산 (간이 계산)

    Args:
        entry_price: 진입 가격
        leverage: 레버리지 배수
        side: 포지션 사이드 (long/short)
        maintenance_margin_rate: 유지 증거금 비율

    Returns:
        Decimal: 청산 가격
    """
    entry = Decimal(str(entry_price))
    lev = Decimal(str(leverage))
    mmr = Decimal(str(maintenance_margin_rate))

    if side.lower() == "long":
        # Long: 청산가 = 진입가 * (1 - 1/레버리지 + 유지증거금비율)
        liq_price = entry * (Decimal("1") - Decimal("1") / lev + mmr)
    else:  # short
        # Short: 청산가 = 진입가 * (1 + 1/레버리지 - 유지증거금비율)
        liq_price = entry * (Decimal("1") + Decimal("1") / lev - mmr)

    return liq_price


def calculate_stop_loss_distance(
    entry_price: float,
    stop_loss_price: float,
    side: str
) -> Decimal:
    """
    스탑로스 거리(%) 계산

    Args:
        entry_price: 진입 가격
        stop_loss_price: 스탑로스 가격
        side: 포지션 사이드 (long/short)

    Returns:
        Decimal: 스탑로스 거리(%)
    """
    entry = Decimal(str(entry_price))
    sl = Decimal(str(stop_loss_price))

    if side.lower() == "long":
        # Long: (진입가 - 스탑로스가) / 진입가 * 100
        distance = (entry - sl) / entry * Decimal("100")
    else:  # short
        # Short: (스탑로스가 - 진입가) / 진입가 * 100
        distance = (sl - entry) / entry * Decimal("100")

    return distance


def calculate_take_profit_distance(
    entry_price: float,
    take_profit_price: float,
    side: str
) -> Decimal:
    """
    테이크프로핏 거리(%) 계산

    Args:
        entry_price: 진입 가격
        take_profit_price: 테이크프로핏 가격
        side: 포지션 사이드 (long/short)

    Returns:
        Decimal: 테이크프로핏 거리(%)
    """
    entry = Decimal(str(entry_price))
    tp = Decimal(str(take_profit_price))

    if side.lower() == "long":
        # Long: (TP가 - 진입가) / 진입가 * 100
        distance = (tp - entry) / entry * Decimal("100")
    else:  # short
        # Short: (진입가 - TP가) / 진입가 * 100
        distance = (entry - tp) / entry * Decimal("100")

    return distance


def calculate_required_margin(
    position_value: float,
    leverage: int
) -> Decimal:
    """
    필요 증거금 계산

    Args:
        position_value: 포지션 가치
        leverage: 레버리지 배수

    Returns:
        Decimal: 필요 증거금
    """
    value = Decimal(str(position_value))
    lev = Decimal(str(leverage))

    return value / lev


def calculate_average_entry_price(
    positions: list[tuple[float, float]]  # [(price1, amount1), (price2, amount2), ...]
) -> Decimal:
    """
    평균 진입 가격 계산

    Args:
        positions: 포지션 리스트 [(가격, 수량), ...]

    Returns:
        Decimal: 평균 진입 가격
    """
    if not positions:
        return Decimal("0")

    total_value = Decimal("0")
    total_amount = Decimal("0")

    for price, amount in positions:
        p = Decimal(str(price))
        a = Decimal(str(amount))
        total_value += p * a
        total_amount += a

    if total_amount == 0:
        return Decimal("0")

    return total_value / total_amount
