"""
부분 익절 시 각 구간의 stop_loss_price가 올바르게 기록되는지 테스트

각 부분 익절 레코드는 그 시점에 유효했던 stop_loss_price를 담아야 합니다:
- TP1 레코드: 초기 SL (98.0)
- TP2 레코드: Break-even SL (100.0 = 평균 진입가)
- TP3 레코드: TP1 가격 SL (102.0)
"""

from datetime import datetime, timedelta
from BACKTEST.models.position import Position
from BACKTEST.models.trade import TradeSide
from BACKTEST.engine.position_manager import PositionManager


def test_partial_exit_sl_snapshots():
    """각 부분 익절 레코드에 올바른 SL 가격이 기록되는지 테스트"""

    # Position Manager 생성
    pm = PositionManager(fee_rate=0.0005)

    # 포지션 오픈 (LONG, 진입가=100, 초기 SL=98)
    base_time = datetime.utcnow()
    position = pm.open_position(
        side=TradeSide.LONG,
        price=100.0,
        quantity=1.0,
        leverage=10.0,
        timestamp=base_time,
        stop_loss_price=98.0,  # 초기 SL
        entry_reason="Test entry"
    )

    # TP 가격 설정
    position.tp1_price = 102.0
    position.tp2_price = 104.0
    position.tp3_price = 106.0

    # TP1/TP2/TP3 활성화
    position.use_tp1 = True
    position.use_tp2 = True
    position.use_tp3 = True

    # TP1/TP2/TP3 비율 설정
    position.tp1_ratio = 0.3
    position.tp2_ratio = 0.3
    position.tp3_ratio = 0.4

    print("\n🧪 부분 익절 SL Snapshot 테스트 시작...\n")
    print(f"📊 초기 설정:")
    print(f"   진입가: {position.entry_price}")
    print(f"   초기 SL: {position.stop_loss_price}")
    print(f"   TP1: {position.tp1_price}, TP2: {position.tp2_price}, TP3: {position.tp3_price}\n")

    # ===== TP1 부분 익절 (초기 SL=98 기록되어야 함) =====
    print("1️⃣ TP1 부분 익절 (초기 SL 기록)")
    current_sl_before_tp1 = position.stop_loss_price  # 98.0

    tp1_trade = pm.partial_close_position(
        exit_price=102.0,
        timestamp=base_time + timedelta(minutes=10),
        tp_level=1,
        exit_ratio=0.3,
        current_stop_loss=current_sl_before_tp1  # 초기 SL 전달
    )

    assert tp1_trade is not None, "TP1 trade should be created"
    assert tp1_trade.stop_loss_price == 98.0, f"TP1 레코드의 SL은 98.0이어야 하는데 {tp1_trade.stop_loss_price}"
    print(f"   ✅ TP1 레코드 SL: {tp1_trade.stop_loss_price} (초기 SL)")

    # TP1 후 Break-even 적용 (SL을 평균 진입가로 이동)
    position.stop_loss_price = 100.0  # Break-even
    print(f"   📍 Break-even 적용: SL → {position.stop_loss_price} (평균 진입가)\n")

    # ===== TP2 부분 익절 (Break-even SL=100 기록되어야 함) =====
    print("2️⃣ TP2 부분 익절 (Break-even SL 기록)")
    current_sl_before_tp2 = position.stop_loss_price  # 100.0

    tp2_trade = pm.partial_close_position(
        exit_price=104.0,
        timestamp=base_time + timedelta(minutes=20),
        tp_level=2,
        exit_ratio=0.3,
        current_stop_loss=current_sl_before_tp2  # Break-even SL 전달
    )

    assert tp2_trade is not None, "TP2 trade should be created"
    assert tp2_trade.stop_loss_price == 100.0, f"TP2 레코드의 SL은 100.0이어야 하는데 {tp2_trade.stop_loss_price}"
    print(f"   ✅ TP2 레코드 SL: {tp2_trade.stop_loss_price} (Break-even SL)")

    # TP2 후 SL을 TP1 가격으로 이동
    position.stop_loss_price = position.tp1_price  # 102.0
    print(f"   📍 TP1 가격으로 이동: SL → {position.stop_loss_price}\n")

    # ===== TP3 부분 익절 (TP1 가격 SL=102 기록되어야 함) =====
    print("3️⃣ TP3 부분 익절 (TP1 가격 SL 기록)")
    current_sl_before_tp3 = position.stop_loss_price  # 102.0

    tp3_trade = pm.partial_close_position(
        exit_price=106.0,
        timestamp=base_time + timedelta(minutes=30),
        tp_level=3,
        exit_ratio=0.4,
        current_stop_loss=current_sl_before_tp3  # TP1 가격 SL 전달
    )

    assert tp3_trade is not None, "TP3 trade should be created"
    assert tp3_trade.stop_loss_price == 102.0, f"TP3 레코드의 SL은 102.0이어야 하는데 {tp3_trade.stop_loss_price}"
    print(f"   ✅ TP3 레코드 SL: {tp3_trade.stop_loss_price} (TP1 가격 SL)\n")

    # ===== 최종 검증 =====
    print("📋 최종 검증:")
    print(f"   총 거래 수: {len(pm.get_trade_history())}")

    trades = pm.get_trade_history()
    assert len(trades) == 3, f"3개의 거래가 있어야 하는데 {len(trades)}개"

    print(f"\n   TP1 레코드 SL: {trades[0].stop_loss_price} ← 초기 SL (98.0)")
    print(f"   TP2 레코드 SL: {trades[1].stop_loss_price} ← Break-even SL (100.0)")
    print(f"   TP3 레코드 SL: {trades[2].stop_loss_price} ← TP1 가격 SL (102.0)")

    assert trades[0].stop_loss_price == 98.0, "TP1 레코드 SL 불일치"
    assert trades[1].stop_loss_price == 100.0, "TP2 레코드 SL 불일치"
    assert trades[2].stop_loss_price == 102.0, "TP3 레코드 SL 불일치"

    print("\n✅ 모든 테스트 통과! 각 구간의 SL이 올바르게 기록되었습니다.\n")


if __name__ == "__main__":
    test_partial_exit_sl_snapshots()
