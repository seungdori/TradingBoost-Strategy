"""
Redis 타입 변환 유틸리티

Redis 저장 시 Python 타입을 문자열로 변환하고,
조회 시 원래 타입으로 복원하는 기능 제공
"""
import json
from decimal import Decimal
from typing import Any, Dict, Optional


def prepare_for_redis(data: Dict[str, Any]) -> Dict[str, str]:
    """
    Redis 저장을 위해 모든 값을 문자열로 변환

    Args:
        data: 변환할 딕셔너리

    Returns:
        모든 값이 문자열로 변환된 딕셔너리

    Examples:
        >>> data = {"use_sl": True, "leverage": 20, "tp1_value": 2.5}
        >>> prepare_for_redis(data)
        {'use_sl': 'true', 'leverage': '20', 'tp1_value': '2.5'}
    """
    result = {}
    for key, value in data.items():
        if isinstance(value, bool):
            # Boolean은 소문자 문자열로 변환
            result[key] = str(value).lower()
        elif isinstance(value, (int, float, Decimal)):
            # 숫자는 문자열로 변환
            result[key] = str(value)
        elif isinstance(value, (list, dict)):
            # 복잡한 타입은 JSON으로 직렬화
            result[key] = json.dumps(value)
        elif value is None:
            # None은 빈 문자열로
            result[key] = ""
        else:
            # 나머지는 문자열로 변환
            result[key] = str(value)

    return result


def parse_from_redis(data: Dict[str, str], schema: Optional[Dict[str, type]] = None) -> Dict[str, Any]:
    """
    Redis에서 가져온 데이터를 원래 타입으로 변환

    Args:
        data: Redis에서 가져온 문자열 딕셔너리
        schema: 각 필드의 타입 정보 (선택사항)

    Returns:
        타입이 변환된 딕셔너리

    Examples:
        >>> raw_data = {'use_sl': 'true', 'leverage': '20'}
        >>> schema = {'use_sl': bool, 'leverage': int}
        >>> parse_from_redis(raw_data, schema)
        {'use_sl': True, 'leverage': 20}
    """
    if not data:
        return {}

    result: Dict[str, Any] = {}
    for key, value in data.items():
        if not value:  # 빈 문자열은 None으로
            result[key] = None
            continue

        # schema가 제공된 경우 타입에 따라 변환
        if schema and key in schema:
            target_type = schema[key]
            if target_type == bool:
                result[key] = value.lower() == 'true'
            elif target_type == int:
                result[key] = int(value)
            elif target_type == float:
                result[key] = float(value)
            else:
                result[key] = value
        else:
            # schema가 없으면 자동 추론
            # Boolean 체크
            if value.lower() in ('true', 'false'):
                result[key] = value.lower() == 'true'
            # 숫자 체크
            elif value.replace('.', '', 1).replace('-', '', 1).isdigit():
                if '.' in value:
                    result[key] = float(value)
                else:
                    result[key] = int(value)
            # JSON 체크
            elif value.startswith(('[', '{')):
                try:
                    result[key] = json.loads(value)
                except json.JSONDecodeError:
                    result[key] = value
            else:
                result[key] = value

    return result


# 공통 스키마 정의
DUAL_SIDE_SETTINGS_SCHEMA = {
    "use_dual_side_entry": bool,
    "dual_side_entry_trigger": int,
    "dual_side_entry_ratio_type": str,
    "dual_side_entry_ratio_value": float,
    "dual_side_entry_tp_trigger_type": str,
    "dual_side_entry_tp_value": float,
    "dual_side_entry_sl_trigger_type": str,
    "dual_side_entry_sl_value": float,
    "dual_side_pyramiding_limit": int,
    "activate_tp_sl_after_all_dca": bool,
    "dual_side_trend_close": bool
}

USER_SETTINGS_SCHEMA = {
    "use_sl": bool,
    "use_break_even": bool,
    "use_break_even_tp2": bool,
    "use_break_even_tp3": bool,
    "use_trend_logic": bool,
    "use_trend_close": bool,
    "use_rsi_with_pyramiding": bool,
    "use_check_DCA_with_price": bool,
    "use_sl_on_last": bool,
    "trailing_stop_active": bool,
    "is_hedge": bool,
    "leverage": int,
    "rsi_length": int,
    "rsi_oversold": float,
    "rsi_overbought": float,
    "tp1_ratio": float,
    "tp2_ratio": float,
    "tp3_ratio": float,
    "tp1_value": float,
    "tp2_value": float,
    "tp3_value": float,
    "sl_value": float,
    "entry_multiplier": float,
    "pyramiding_value": float,
    "pyramiding_limit": int,
    "cooldown_time": int,
}
