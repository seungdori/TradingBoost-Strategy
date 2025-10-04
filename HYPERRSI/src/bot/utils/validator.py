# bot/utils/validators.py

from typing import Tuple
from shared.constants.default_settings import SETTINGS_CONSTRAINTS

def validate_setting(setting_type: str, value: float) -> Tuple[bool, str]:
    """
    개별 설정값 검증
    Returns:
        Tuple[bool, str]: (검증 통과 여부, 에러 메시지)
    """
    if setting_type not in SETTINGS_CONSTRAINTS:
        return True, ""
        
    constraints = SETTINGS_CONSTRAINTS[setting_type]
    if not constraints["min"] <= float(value) <= constraints["max"]:
        return False, f"값이 허용 범위({constraints['min']}-{constraints['max']})를 벗어났습니다."
    
    return True, ""

def validate_trading_settings(settings: dict) -> Tuple[bool, str]:
    """
    전체 거래 설정값 검증
    """
    # TP 비율 합계 검증
    tp_total = settings.get('tp1_ratio', 0) + settings.get('tp2_ratio', 0) + settings.get('tp3_ratio', 0)
    if tp_total != 100:
        return False, "TP 비율의 합이 100%가 되어야 합니다."
    
    # RSI 과매수/과매도 값 검증
    if settings.get('rsi_overbought', 70) <= settings.get('rsi_oversold', 30):
        return False, "RSI 과매수값은 과매도값보다 커야 합니다."
    
    # 각 설정값 개별 검증
    for setting_type, value in settings.items():
        if setting_type in SETTINGS_CONSTRAINTS:
            is_valid, error_msg = validate_setting(setting_type, value)
            if not is_valid:
                return False, f"{setting_type}: {error_msg}"
    
    return True, ""