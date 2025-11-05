# constants/default_settings.py

DEFAULT_TRADING_SETTINGS = {
    "timeframe": "1m",
    "symbol": "BTC-USDT-SWAP",
}


DEFAULT_PARAMS_SETTINGS = {
    # 기본 설정
    "btc_investment": 20,
    "eth_investment": 20,
    "sol_investment": 20,
    'entry_amount_option': 'usdt',

    'symbol_investments': {},  # 심볼별 투입금액 {심볼: 금액}

    # 실행 모드 설정 (글로벌 기본값 + 종목별 Override)
    "execution_mode": "api_direct",  # 글로벌 기본값: api_direct | signal_bot
    "signal_bot_token": None,
    "signal_bot_webhook_url": None,

    # 종목별 실행 모드 Override (선택사항)
    # 예: {"BTC-USDT-SWAP": "signal_bot", "ETH-USDT-SWAP": "api_direct"}
    # 설정 없는 종목은 execution_mode 기본값 사용
    "symbol_execution_modes": {},

    "leverage": 10,
    "direction": "롱숏",
    "entry_multiplier": 1.0,
    "use_cooldown": True,
    "cooldown_time": 300,
    "use_trend_logic": True,
    "trend_timeframe": "1H",
    "use_trend_close": True,
    # RSI 설정
    "rsi_length": 14,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "entry_option": "돌파",
    
    # TP 설정
    "tp_option": "퍼센트 기준",
    "tp1_ratio": 30,
    "tp2_ratio": 30,
    "tp3_ratio": 40,
    "tp1_value": 2.0,
    "tp2_value": 3.0,
    "tp3_value": 4.0,
    "use_tp1": True,
    "use_tp2": True,
    "use_tp3": True,
    
    # SL 설정
    "use_sl": False,  # 기본값: OFF
    "use_sl_on_last": False,
    "sl_option": "퍼센트 기준",
    "sl_value": 5.0,
    
    # 브레이크이븐 설정
    "use_break_even": True,
    "use_break_even_tp2": True,
    "use_break_even_tp3": True,

    # 피라미딩 설정
    "use_check_DCA_with_price": True,
    "use_rsi_with_pyramiding": True,
    "entry_criterion": "평균 단가",
    
    "pyramiding_type": "0",  # 0: 최초 진입만, 1: 추가진입, 2: 반대방향 진입
    "pyramiding_limit": 4,
    "pyramiding_entry_type": "퍼센트 기준",  # 금액/퍼센트/ATR 기준
    "pyramiding_value": 3.0,
    
    #트레일링스탑 설정
    "trailing_stop_active": True,  # 기본값: ON
    "trailing_start_point": "tp3",
    "trailing_stop_type": "트레일링 스탑 고정값",
    "use_trailing_stop_value_with_tp2_tp3_difference": False,
    "trailing_stop_offset_value": 0.5,
    
}

# 설정값 검증을 위한 제한사항
SETTINGS_CONSTRAINTS = {
    "investment": {"min": 1, "max": 1000000},
    "leverage": {"min": 1, "max": 125},
    "pyramiding_limit": {"min": 1, "max": 10},
    "entry_multiplier": {"min": 0.1, "max": 5.0},
    "rsi_length": {"min": 1, "max": 100},
    "rsi_oversold": {"min": 0, "max": 100},
    "rsi_overbought": {"min": 0, "max": 100},
    "tp1_ratio": {"min": 0, "max": 100},
    "tp2_ratio": {"min": 0, "max": 100},
    "tp3_ratio": {"min": 0, "max": 100},
    "sl_value": {"min": 0.1, "max": 100},
    "cooldown_time": {"min": 0, "max": 3000},
}

DEFAULT_DUAL_SIDE_ENTRY_SETTINGS = {
    "use_dual_side_entry": False,
    "dual_side_entry_trigger": 3,
    "dual_side_entry_ratio_type": "percent_of_position",
    "dual_side_entry_ratio_value": 30,
    "dual_side_entry_tp_trigger_type": "last_dca_on_position",
    "dual_side_entry_tp_value": 0.3,
    "dual_side_entry_sl_trigger_type": "percent",
    "dual_side_entry_sl_value": 5,
    "dual_side_pyramiding_limit": 1,
    "activate_tp_sl_after_all_dca": False,
    "dual_side_trend_close": False
}

# 선택 옵션들
ENTRY_OPTIONS = ["돌파", "변곡", "변곡돌파", "초과"]
TP_SL_OPTIONS = ["금액 기준", "퍼센트 기준", "ATR 기준"]
DIRECTION_OPTIONS = ["롱", "숏", "롱숏"]

ENTRY_CRITERION_OPTIONS = [
    "평균 단가",
    "마지막 진입"
]

TRAILING_STOP_TYPES = [
    "트레일링 스탑 고정값",
    "TP2-TP3 차이 기준"
]

# 투입금액 옵션
ENTRY_AMOUNT_OPTIONS = ["usdt", "percent", "count"]
ENTRY_AMOUNT_UNITS = {
    "usdt": "USDT",
    "percent": "%",
    "count": "개"
}