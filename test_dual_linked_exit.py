#!/usr/bin/env python3
"""
Test dual-side LINKED_EXIT behavior via API
"""

import requests
import json
from datetime import datetime, timedelta

# API endpoint
API_URL = "http://localhost:8013/backtest/run"

# Strategy parameters from user
strategy_params = {
    "rsi_period": 14,
    "rsi_os": 30,
    "rsi_ob": 70,
    "direction": "both",
    "use_trend_filter": True,
    "ema_period": 7,
    "sma_period": 20,
    "entry_option": "rsi_only",
    "require_trend_confirm": True,
    "use_trend_close": False,
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
    "use_trend_logic": False,
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
    "dual_side_entry_trigger": 6,
    "dual_side_entry_ratio_type": "percent_of_position",
    "dual_side_entry_ratio_value": 100,
    "dual_side_entry_tp_trigger_type": "existing_position",
    "close_main_on_hedge_tp": True,
    "use_dual_sl": False,
    "dual_side_pyramiding_limit": 2,
    "dual_side_trend_close": False,
}

# Backtest request
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
print("🔍 DUAL-SIDE BACKTEST - LINKED_EXIT TEST")
print("=" * 80)
print(f"Dual-side enabled: {strategy_params['use_dual_side_entry']}")
print(f"Dual entry trigger: {strategy_params['dual_side_entry_trigger']} DCA")
print(f"Dual trend close: {strategy_params['dual_side_trend_close']}")
print(f"Dual close on main SL: {strategy_params.get('dual_side_close_on_main_sl', 'Not set (default: False)')}")
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
        print(f"Max drawdown: {result['max_drawdown_percent']:.2f}%")
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

        # Check for linked_exit issues
        linked_exit_trades = [t for t in trades if t.get('exit_reason') == 'linked_exit']
        print(f"🔗 Trades closed with LINKED_EXIT: {len(linked_exit_trades)}")

        if linked_exit_trades:
            print()
            print("📋 LINKED_EXIT Trade Details (first 10):")
            for i, trade in enumerate(linked_exit_trades[:10], 1):
                print(f"\n  Trade #{trade['trade_number']}:")
                print(f"    Side: {trade['side']}")
                print(f"    Is dual: {trade.get('is_dual_side_position', False)}")
                print(f"    Parent trade: {trade.get('parent_trade_id', 'None')}")
                print(f"    Entry: ${trade['entry_price']:.2f}")
                print(f"    Exit: ${trade.get('exit_price', 'N/A'):.2f}")
                print(f"    PnL: ${trade.get('pnl', 0):.2f}")

        # Check for open positions (via detailed_metrics or other fields)
        print()
        print("=" * 80)
        # Try to find unrealized PnL in detailed_metrics or check if all trades are closed
        open_trades = [t for t in result['trades'] if t.get('exit_timestamp') is None]
        if open_trades:
            print(f"⚠️ OPEN POSITIONS REMAINING: {len(open_trades)} trades")
            print("This indicates positions were not properly closed!")
            for trade in open_trades[:3]:  # Show first 3
                print(f"  - Trade #{trade['trade_number']}: {trade['side']} position still open")
        else:
            print("✅ All positions closed successfully (no open trades)")
        print("=" * 80)

        # Save full response to file for detailed analysis
        with open('backtest_result.json', 'w') as f:
            json.dump(result, f, indent=2)
        print()
        print("💾 Full results saved to: backtest_result.json")

    else:
        print(f"❌ API Error {response.status_code}:")
        print(response.text)

except requests.exceptions.ConnectionError:
    print("❌ Cannot connect to API server!")
    print("Please start the BACKTEST service first:")
    print("  cd BACKTEST && python main.py")

except Exception as e:
    print(f"❌ Error: {e}")
