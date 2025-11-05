"""
Break-even 로직 테스트

트레일링 스톱과 break-even 종료 사유가 제대로 구분되는지 확인합니다.
"""

from datetime import datetime
from BACKTEST.models.position import Position
from BACKTEST.models.trade import TradeSide


def test_long_breakeven():
    """LONG 포지션 break-even 테스트"""
    position = Position(
        side=TradeSide.LONG,
        entry_timestamp=datetime.utcnow(),
        entry_price=100.0,
        quantity=1.0,
        leverage=10.0,
        initial_margin=10.0,
        stop_loss_price=100.0,  # Break-even: stop loss = entry price
    )

    # Break-even에 걸림
    should_exit, reason = position.should_exit(99.0)
    assert should_exit is True
    assert reason == "break_even", f"Expected 'break_even', got '{reason}'"
    print("✅ LONG break-even 테스트 통과")


def test_long_stop_loss():
    """LONG 포지션 일반 stop loss 테스트"""
    position = Position(
        side=TradeSide.LONG,
        entry_timestamp=datetime.utcnow(),
        entry_price=100.0,
        quantity=1.0,
        leverage=10.0,
        initial_margin=10.0,
        stop_loss_price=98.0,  # 일반 손절: stop loss < entry price
    )

    # 손절에 걸림
    should_exit, reason = position.should_exit(97.0)
    assert should_exit is True
    assert reason == "stop_loss", f"Expected 'stop_loss', got '{reason}'"
    print("✅ LONG stop_loss 테스트 통과")


def test_long_trailing_stop():
    """LONG 포지션 trailing stop 테스트"""
    position = Position(
        side=TradeSide.LONG,
        entry_timestamp=datetime.utcnow(),
        entry_price=100.0,
        quantity=1.0,
        leverage=10.0,
        initial_margin=10.0,
        stop_loss_price=98.0,
        trailing_stop_price=102.0,  # Trailing stop 활성화
    )

    # Trailing stop에 걸림 (stop_loss보다 우선순위 높음)
    should_exit, reason = position.should_exit(101.0)
    assert should_exit is True
    assert reason == "trailing_stop", f"Expected 'trailing_stop', got '{reason}'"
    print("✅ LONG trailing_stop 테스트 통과")


def test_short_breakeven():
    """SHORT 포지션 break-even 테스트"""
    position = Position(
        side=TradeSide.SHORT,
        entry_timestamp=datetime.utcnow(),
        entry_price=100.0,
        quantity=1.0,
        leverage=10.0,
        initial_margin=10.0,
        stop_loss_price=100.0,  # Break-even: stop loss = entry price
    )

    # Break-even에 걸림
    should_exit, reason = position.should_exit(101.0)
    assert should_exit is True
    assert reason == "break_even", f"Expected 'break_even', got '{reason}'"
    print("✅ SHORT break-even 테스트 통과")


def test_short_stop_loss():
    """SHORT 포지션 일반 stop loss 테스트"""
    position = Position(
        side=TradeSide.SHORT,
        entry_timestamp=datetime.utcnow(),
        entry_price=100.0,
        quantity=1.0,
        leverage=10.0,
        initial_margin=10.0,
        stop_loss_price=102.0,  # 일반 손절: stop loss > entry price
    )

    # 손절에 걸림
    should_exit, reason = position.should_exit(103.0)
    assert should_exit is True
    assert reason == "stop_loss", f"Expected 'stop_loss', got '{reason}'"
    print("✅ SHORT stop_loss 테스트 통과")


def test_short_trailing_stop():
    """SHORT 포지션 trailing stop 테스트"""
    position = Position(
        side=TradeSide.SHORT,
        entry_timestamp=datetime.utcnow(),
        entry_price=100.0,
        quantity=1.0,
        leverage=10.0,
        initial_margin=10.0,
        stop_loss_price=102.0,
        trailing_stop_price=98.0,  # Trailing stop 활성화
    )

    # Trailing stop에 걸림 (stop_loss보다 우선순위 높음)
    should_exit, reason = position.should_exit(99.0)
    assert should_exit is True
    assert reason == "trailing_stop", f"Expected 'trailing_stop', got '{reason}'"
    print("✅ SHORT trailing_stop 테스트 통과")


if __name__ == "__main__":
    print("\n🧪 Break-even 로직 테스트 시작...\n")

    test_long_breakeven()
    test_long_stop_loss()
    test_long_trailing_stop()

    test_short_breakeven()
    test_short_stop_loss()
    test_short_trailing_stop()

    print("\n✅ 모든 테스트 통과!\n")
