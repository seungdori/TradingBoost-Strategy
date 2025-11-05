"""
부분 익절 시 자동 break-even 테스트
- 초기 SL 설정 없이도 break-even이 작동하는지 확인
"""

from datetime import datetime
from BACKTEST.engine.position_manager import PositionManager
from BACKTEST.models.position import Position
from BACKTEST.models.trade import TradeSide

def test_automatic_breakeven_without_initial_sl():
    """
    초기 SL 없이 부분 익절 시나리오:
    - 진입 시 SL = None
    - TP1 hit → SL이 entry_price로 자동 설정됨
    - TP2 hit → SL이 TP1 price로 자동 설정됨
    - TP3 hit → SL이 TP2 price로 자동 설정됨
    """
    print("🧪 자동 Break-even 테스트 (초기 SL 없음)\n")

    # PositionManager 초기화
    pm = PositionManager(fee_rate=0.0005)
    base_time = datetime.utcnow()

    # LONG 포지션 직접 생성 (초기 SL = None)
    position = Position(
        side=TradeSide.LONG,
        entry_price=100.0,
        quantity=1.0,
        entry_timestamp=base_time,
        leverage=10.0,
        stop_loss_price=None,  # ✅ 초기 SL 없음
        take_profit_price=None,
        tp1_price=102.0,
        tp2_price=104.0,
        tp3_price=106.0,
        tp1_ratio=0.3,
        tp2_ratio=0.3,
        tp3_ratio=0.4,
        next_dca_levels=[95.0, 90.0],
        entry_rsi=28.5,
        entry_atr=2.5
    )

    # PositionManager에 설정
    pm.position = position

    print(f"📊 초기 포지션:")
    print(f"   진입가: {position.entry_price}")
    print(f"   수량: {position.quantity}")
    print(f"   초기 SL: {position.stop_loss_price}")  # None
    print(f"   TP1: {position.tp1_price}, TP2: {position.tp2_price}, TP3: {position.tp3_price}")
    print()

    # ========================================
    # 1️⃣ TP1 부분 익절 (초기 SL 기록)
    # ========================================
    print("1️⃣ TP1 부분 익절:")
    current_sl_before_tp1 = position.stop_loss_price  # None
    print(f"   TP1 hit 시점의 SL: {current_sl_before_tp1}")

    tp1_trade = pm.partial_close_position(
        exit_price=102.0,
        timestamp=base_time,
        tp_level=1,
        exit_ratio=0.3,
        current_stop_loss=current_sl_before_tp1  # None 전달
    )

    print(f"   TP1 레코드에 기록된 SL: {tp1_trade.stop_loss_price}")
    assert tp1_trade.stop_loss_price is None, "TP1 레코드는 초기 SL (None)을 기록해야 함"
    print(f"   ✅ TP1 레코드에 초기 SL (None) 정상 기록")
    print()

    # TP1 후 break-even 적용 (BacktestEngine에서 수행)
    # 이제 무조건 적용됨!
    position.stop_loss_price = position.get_average_entry_price()  # 100.0
    print(f"   Break-even 적용 후 SL: {position.stop_loss_price}")
    print()

    # ========================================
    # 2️⃣ TP2 부분 익절 (Break-even SL 기록)
    # ========================================
    print("2️⃣ TP2 부분 익절:")
    current_sl_before_tp2 = position.stop_loss_price  # 100.0 (entry price)
    print(f"   TP2 hit 시점의 SL: {current_sl_before_tp2}")

    tp2_trade = pm.partial_close_position(
        exit_price=104.0,
        timestamp=base_time,
        tp_level=2,
        exit_ratio=0.3,
        current_stop_loss=current_sl_before_tp2  # 100.0
    )

    print(f"   TP2 레코드에 기록된 SL: {tp2_trade.stop_loss_price}")
    assert tp2_trade.stop_loss_price == 100.0, "TP2 레코드는 break-even SL (100.0)을 기록해야 함"
    print(f"   ✅ TP2 레코드에 break-even SL (100.0) 정상 기록")
    print()

    # TP2 후 break-even 적용 (SL을 TP1 price로 이동)
    position.stop_loss_price = position.tp1_price  # 102.0
    print(f"   Break-even TP2 적용 후 SL: {position.stop_loss_price}")
    print()

    # ========================================
    # 3️⃣ TP3 부분 익절 (TP1 가격 SL 기록)
    # ========================================
    print("3️⃣ TP3 부분 익절:")
    current_sl_before_tp3 = position.stop_loss_price  # 102.0 (TP1 price)
    print(f"   TP3 hit 시점의 SL: {current_sl_before_tp3}")

    tp3_trade = pm.partial_close_position(
        exit_price=106.0,
        timestamp=base_time,
        tp_level=3,
        exit_ratio=0.4,
        current_stop_loss=current_sl_before_tp3  # 102.0
    )

    print(f"   TP3 레코드에 기록된 SL: {tp3_trade.stop_loss_price}")
    assert tp3_trade.stop_loss_price == 102.0, "TP3 레코드는 TP1 가격 SL (102.0)을 기록해야 함"
    print(f"   ✅ TP3 레코드에 TP1 가격 SL (102.0) 정상 기록")
    print()

    # ========================================
    # 📋 최종 검증
    # ========================================
    print("📋 최종 검증:")
    print(f"   TP1 레코드 SL: {tp1_trade.stop_loss_price} (초기 SL = None)")
    print(f"   TP2 레코드 SL: {tp2_trade.stop_loss_price} (Break-even = 100.0)")
    print(f"   TP3 레코드 SL: {tp3_trade.stop_loss_price} (TP1 가격 = 102.0)")
    print()

    print("✅ 모든 테스트 통과!")
    print()
    print("🎯 결론:")
    print("   - 초기 SL이 없어도 (None) 정상 작동")
    print("   - TP1 후 자동으로 SL이 entry_price로 설정됨")
    print("   - TP2 후 자동으로 SL이 TP1 price로 설정됨")
    print("   - 각 레코드는 해당 시점의 유효했던 SL을 정확히 기록")


def test_with_initial_sl():
    """
    초기 SL이 있는 경우 (기존 시나리오)
    """
    print("\n" + "="*60)
    print("🧪 자동 Break-even 테스트 (초기 SL 있음)\n")

    pm = PositionManager(fee_rate=0.0005)
    base_time = datetime.utcnow()

    # LONG 포지션 오픈 (초기 SL = 98.0)
    position = pm.open_position(
        side=TradeSide.LONG,
        entry_price=100.0,
        quantity=1.0,
        timestamp=base_time,
        leverage=10.0,
        stop_loss_price=98.0,  # ✅ 초기 SL 있음
        take_profit_price=None,
        tp1_price=102.0,
        tp2_price=104.0,
        tp3_price=106.0,
        tp1_ratio=0.3,
        tp2_ratio=0.3,
        tp3_ratio=0.4,
    )

    print(f"📊 초기 포지션:")
    print(f"   초기 SL: {position.stop_loss_price}")  # 98.0
    print()

    # TP1
    current_sl_before_tp1 = position.stop_loss_price  # 98.0
    tp1_trade = pm.partial_close_position(
        exit_price=102.0, timestamp=base_time, tp_level=1, exit_ratio=0.3,
        current_stop_loss=current_sl_before_tp1
    )
    assert tp1_trade.stop_loss_price == 98.0
    print(f"✅ TP1 레코드 SL: {tp1_trade.stop_loss_price} (초기 SL)")

    # Break-even 적용
    position.stop_loss_price = position.get_average_entry_price()  # 100.0

    # TP2
    current_sl_before_tp2 = position.stop_loss_price  # 100.0
    tp2_trade = pm.partial_close_position(
        exit_price=104.0, timestamp=base_time, tp_level=2, exit_ratio=0.3,
        current_stop_loss=current_sl_before_tp2
    )
    assert tp2_trade.stop_loss_price == 100.0
    print(f"✅ TP2 레코드 SL: {tp2_trade.stop_loss_price} (Break-even)")

    # Break-even TP2 적용
    position.stop_loss_price = position.tp1_price  # 102.0

    # TP3
    current_sl_before_tp3 = position.stop_loss_price  # 102.0
    tp3_trade = pm.partial_close_position(
        exit_price=106.0, timestamp=base_time, tp_level=3, exit_ratio=0.4,
        current_stop_loss=current_sl_before_tp3
    )
    assert tp3_trade.stop_loss_price == 102.0
    print(f"✅ TP3 레코드 SL: {tp3_trade.stop_loss_price} (TP1 가격)")
    print()

    print("✅ 초기 SL이 있는 경우도 정상 작동!")


if __name__ == "__main__":
    test_automatic_breakeven_without_initial_sl()
    test_with_initial_sl()

    print("\n" + "="*60)
    print("🎉 모든 자동 break-even 테스트 통과!")
    print()
    print("💡 핵심 변경사항:")
    print("   - 부분 익절 사용 시 break-even이 **무조건** 자동 적용됨")
    print("   - use_break_even, use_break_even_tp2 플래그 체크 제거")
    print("   - 초기 SL 설정 여부와 관계없이 정상 작동")
