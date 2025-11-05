"""
API 응답에서 TP/SL 가격 정보가 제대로 포함되는지 테스트

BacktestResult (Trade) → BacktestDetailResponse (TradeResponse) 변환 확인
"""

from datetime import datetime
from uuid import uuid4
from BACKTEST.models.result import BacktestResult
from BACKTEST.models.trade import Trade, TradeSide, ExitReason
from BACKTEST.api.schemas.response import BacktestDetailResponse, TradeResponse


def test_api_response_includes_tp_sl_prices():
    """API 응답에 TP/SL 가격 정보가 포함되는지 테스트"""

    # Trade 객체 생성 (모든 TP/SL 필드 포함)
    trade = Trade(
        trade_number=1,
        side=TradeSide.LONG,
        entry_timestamp=datetime.utcnow(),
        entry_price=100.0,
        exit_timestamp=datetime.utcnow(),
        exit_price=102.0,
        exit_reason=ExitReason.TP1,
        quantity=1.0,
        leverage=10.0,
        pnl=20.0,
        pnl_percent=2.0,
        entry_fee=0.5,
        exit_fee=0.51,
        # TP/SL 가격 정보
        take_profit_price=105.0,
        stop_loss_price=98.0,
        trailing_stop_price=None,
        tp1_price=102.0,
        tp2_price=104.0,
        tp3_price=106.0,
        # 기타 정보
        next_dca_levels=[95.0, 90.0],
        entry_rsi=28.5,
        entry_atr=2.5,
        dca_count=0,
        is_partial_exit=True,
        tp_level=1,
        exit_ratio=0.3,
        remaining_quantity=0.7
    )

    # BacktestResult 생성
    result = BacktestResult(
        user_id=uuid4(),
        symbol="BTC-USDT-SWAP",
        timeframe="5m",
        start_date=datetime.utcnow(),
        end_date=datetime.utcnow(),
        strategy_name="hyperrsi",
        strategy_params={"leverage": 10},
        started_at=datetime.utcnow(),
        initial_balance=10000.0,
        final_balance=10020.0,
        trades=[trade]
    )

    print("\n🧪 API 응답 매핑 테스트 시작...\n")
    print("📊 Trade 모델 필드:")
    trade_dict = trade.model_dump()
    tp_sl_fields = [
        'take_profit_price', 'stop_loss_price', 'trailing_stop_price',
        'tp1_price', 'tp2_price', 'tp3_price',
        'next_dca_levels', 'entry_rsi', 'entry_atr'
    ]
    for field in tp_sl_fields:
        value = trade_dict.get(field)
        print(f"   {field}: {value}")

    # BacktestDetailResponse로 변환 (API가 하는 것처럼)
    print("\n🔄 BacktestDetailResponse로 변환 중...")
    response = BacktestDetailResponse(**result.model_dump())

    print("\n✅ 변환 완료! TradeResponse 확인:\n")

    # TradeResponse 필드 확인
    assert len(response.trades) == 1, "Trade가 1개여야 함"
    trade_response = response.trades[0]

    # 기본 필드 확인
    assert trade_response.trade_number == 1
    assert trade_response.side == "long"
    assert trade_response.entry_price == 100.0
    assert trade_response.exit_price == 102.0
    print(f"   기본 필드: ✅")

    # TP/SL 가격 정보 확인
    print(f"\n   TP/SL 가격 정보:")
    assert hasattr(trade_response, 'take_profit_price'), "take_profit_price 필드 없음!"
    assert hasattr(trade_response, 'stop_loss_price'), "stop_loss_price 필드 없음!"
    assert hasattr(trade_response, 'trailing_stop_price'), "trailing_stop_price 필드 없음!"
    assert hasattr(trade_response, 'tp1_price'), "tp1_price 필드 없음!"
    assert hasattr(trade_response, 'tp2_price'), "tp2_price 필드 없음!"
    assert hasattr(trade_response, 'tp3_price'), "tp3_price 필드 없음!"

    print(f"   • take_profit_price: {trade_response.take_profit_price} ✅")
    print(f"   • stop_loss_price: {trade_response.stop_loss_price} ✅")
    print(f"   • trailing_stop_price: {trade_response.trailing_stop_price} ✅")
    print(f"   • tp1_price: {trade_response.tp1_price} ✅")
    print(f"   • tp2_price: {trade_response.tp2_price} ✅")
    print(f"   • tp3_price: {trade_response.tp3_price} ✅")

    # 값 확인
    assert trade_response.take_profit_price == 105.0
    assert trade_response.stop_loss_price == 98.0
    assert trade_response.trailing_stop_price is None
    assert trade_response.tp1_price == 102.0
    assert trade_response.tp2_price == 104.0
    assert trade_response.tp3_price == 106.0

    # 추가 정보 확인
    print(f"\n   추가 정보:")
    assert hasattr(trade_response, 'next_dca_levels'), "next_dca_levels 필드 없음!"
    assert hasattr(trade_response, 'entry_rsi'), "entry_rsi 필드 없음!"
    assert hasattr(trade_response, 'entry_atr'), "entry_atr 필드 없음!"

    print(f"   • next_dca_levels: {trade_response.next_dca_levels} ✅")
    print(f"   • entry_rsi: {trade_response.entry_rsi} ✅")
    print(f"   • entry_atr: {trade_response.entry_atr} ✅")

    assert trade_response.next_dca_levels == [95.0, 90.0]
    assert trade_response.entry_rsi == 28.5
    assert trade_response.entry_atr == 2.5

    # 부분 익절 정보 확인
    print(f"\n   부분 익절 정보:")
    print(f"   • is_partial_exit: {trade_response.is_partial_exit} ✅")
    print(f"   • tp_level: {trade_response.tp_level} ✅")
    print(f"   • exit_ratio: {trade_response.exit_ratio} ✅")
    print(f"   • remaining_quantity: {trade_response.remaining_quantity} ✅")

    assert trade_response.is_partial_exit is True
    assert trade_response.tp_level == 1
    assert trade_response.exit_ratio == 0.3
    assert trade_response.remaining_quantity == 0.7

    # JSON 직렬화 테스트
    print(f"\n🔧 JSON 직렬화 테스트...")
    response_json = response.model_dump_json()
    assert 'tp1_price' in response_json
    assert 'tp2_price' in response_json
    assert 'tp3_price' in response_json
    assert 'stop_loss_price' in response_json
    print(f"   JSON 직렬화: ✅")

    print("\n✅ 모든 테스트 통과!")
    print("\n🎉 API 응답에 모든 TP/SL 가격 정보가 포함됩니다!\n")


if __name__ == "__main__":
    test_api_response_includes_tp_sl_prices()
