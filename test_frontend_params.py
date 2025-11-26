#!/usr/bin/env python3
"""
Test with exact frontend parameters
"""

import requests
import json
from datetime import datetime, timedelta

# API endpoint
API_URL = "http://localhost:8013/backtest/run"

# Exact parameters from frontend
strategy_params = {
    "rsi_period": 14,
    "rsi_os": 30,
    "rsi_ob": 70,
    "direction": "both",
    "use_trend_filter": True,
    "ema_period": 7,
    "sma_period": 20,
    "entry_option": "rsi_trend",
    "require_trend_confirm": True,
    "use_trend_close": True,
    "use_tp1": True,
    "tp1_percent": 3,
    "tp1_close_percent": 30,
    "use_tp2": True,
    "tp2_percent": 4,
    "tp2_close_percent": 30,
    "use_tp3": True,
    "tp3_percent": 5,
    "tp3_close_percent": 40,
    "use_trailing_stop": True,
    "trailing_stop_percent": 0.5,
    "trailing_activation_percent": 2,
    "use_break_even": True,
    "use_break_even_tp2": True,
    "use_break_even_tp3": True,
    "use_dca": True,
    "dca_max_orders": 8,
    "dca_price_step_percent": 3,
    "dca_size_multiplier": 1,
    "rsi_entry_option": "돌파",
    "leverage": 10,
    "investment": 35,
    "stop_loss_enabled": False,
    "take_profit_enabled": False,
    "take_profit_percent": None,
    "pyramiding_enabled": True,
    "pyramiding_limit": 8,
    "pyramiding_entry_type": "atr",
    "pyramiding_value": 3,
    "use_rsi_with_pyramiding": True,
    "use_trend_logic": True,
    "trend_timeframe": "1H",
    "tp_option": "atr",
    "tp1_value": 3,
    "tp2_value": 4,
    "tp3_value": 5,
    "tp1_ratio": 30,
    "tp2_ratio": 30,
    "tp3_ratio": 40,
    "trailing_stop_active": True,
    "trailing_start_point": "tp2",
    "trailing_stop_offset_value": 0.5,
    "use_trailing_stop_value_with_tp2_tp3_difference": True,
    # Dual-side configuration
    "use_dual_side_entry": True,
    "dual_side_entry_trigger": 2,
    "dual_side_entry_ratio_type": "percent_of_position",
    "dual_side_entry_ratio_value": 100,
    "dual_side_entry_tp_trigger_type": "existing_position",
    "close_main_on_hedge_tp": True,
    "use_dual_sl": False,
    "dual_side_pyramiding_limit": 2,
    "dual_side_trend_close": True,
}

# Backtest request - similar period to frontend
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

request_data = {
    "symbol": "BTC-USDT-SWAP",
    "timeframe": "15m",
    "start_date": start_date.isoformat() + "Z",
    "end_date": end_date.isoformat() + "Z",
    "strategy_name": "hyperrsi",
    "strategy_params": strategy_params,
    "initial_balance": 10000.0,
    "fee_rate": 0.0005,
    "slippage_percent": 0.05
}

print("=" * 80)
print("🔍 FRONTEND PARAMETERS TEST")
print("=" * 80)
print(f"Dual-side enabled: {strategy_params['use_dual_side_entry']}")
print(f"Dual entry trigger: {strategy_params['dual_side_entry_trigger']} DCA")
print(f"Entry option: {strategy_params['entry_option']}")
print(f"Use trend close: {strategy_params['use_trend_close']}")
print("=" * 80)
print()

print(f"📅 Test period: {start_date.date()} to {end_date.date()}")
print(f"💰 Initial balance: ${request_data['initial_balance']:,.2f}")
print()
print("🚀 Starting backtest via API...")
print()

try:
    response = requests.post(API_URL, json=request_data, timeout=300)

    if response.status_code == 200:
        result = response.json()

        print("=" * 80)
        print("📈 BACKTEST RESULTS")
        print("=" * 80)
        print(f"Total trades: {result['total_trades']}")
        print(f"Winning trades: {result['winning_trades']}")
        print(f"Losing trades: {result['losing_trades']}")
        print(f"Win rate: {result['win_rate']:.2f}%")
        print(f"Final balance: ${result['final_balance']:.2f}")
        print(f"Total PnL: ${result['total_return']:.2f}")
        print(f"Total return: {result['total_return_percent']:.2f}%")
        print("=" * 80)
        print()

        # Analyze trades
        trades = result['trades']
        main_trades = [t for t in trades if not t.get('is_dual_side_position', False)]
        dual_trades = [t for t in trades if t.get('is_dual_side_position', False)]

        print("🔍 ANALYZING DUAL-SIDE TRADES...")
        print("=" * 80)
        print(f"📊 Main position trades: {len(main_trades)}")
        print(f"🔄 Dual-side trades: {len(dual_trades)}")
        print()

        # Check DCA counts
        high_dca_trades = [t for t in trades if t.get('dca_count', 0) >= 2]
        print(f"📊 Trades with DCA >= 2: {len(high_dca_trades)}")
        print()

        if high_dca_trades:
            print("📋 High DCA Trades (should have dual-side):")
            for trade in high_dca_trades[:5]:
                print(f"  Trade #{trade['trade_number']}: DCA={trade['dca_count']}, is_dual={trade.get('is_dual_side_position', False)}")
        print()

        # Check for linked_exit trades
        linked_exit_trades = [t for t in trades if t.get('exit_reason') == 'linked_exit']
        print(f"🔗 Trades closed with LINKED_EXIT: {len(linked_exit_trades)}")

        if linked_exit_trades:
            print()
            print("📋 LINKED_EXIT Trade Details:")
            for trade in linked_exit_trades[:5]:
                print(f"\n  Trade #{trade['trade_number']}:")
                print(f"    Side: {trade['side']}")
                print(f"    Is dual: {trade.get('is_dual_side_position', False)}")
                print(f"    Parent trade: {trade.get('parent_trade_id', 'None')}")
                print(f"    DCA count: {trade.get('dca_count', 0)}")

        # Save result
        with open('frontend_test_result.json', 'w') as f:
            json.dump(result, f, indent=2)
        print()
        print("💾 Full results saved to: frontend_test_result.json")

    else:
        print(f"❌ API Error {response.status_code}:")
        print(response.text)

except requests.exceptions.ConnectionError:
    print("❌ Cannot connect to API server!")
    print("Please check if BACKTEST service is running on port 8013")

except Exception as e:
    print(f"❌ Error: {e}")
