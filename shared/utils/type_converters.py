"""타입 변환 및 검증 유틸리티"""
from typing import Any, Optional, Union, Dict, List, Tuple
from decimal import Decimal, ROUND_HALF_UP


def parse_bool(value: Any) -> bool:
    """
    다양한 타입을 불리언으로 변환

    Args:
        value: 변환할 값 (bool, int, float, str)

    Returns:
        불리언 값

    Examples:
        >>> parse_bool(1)
        True
        >>> parse_bool("false")
        False
        >>> parse_bool("yes")
        True
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on', 'y')
    return False


def safe_float(
    value: Any,
    default: float = 0.0,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None
) -> float:
    """
    안전한 float 변환 (범위 검증 포함)

    Args:
        value: 변환할 값
        default: 변환 실패 시 기본값
        min_value: 최소값 (선택)
        max_value: 최대값 (선택)

    Returns:
        float 값

    Examples:
        >>> safe_float("3.14")
        3.14
        >>> safe_float(None, default=1.0)
        1.0
        >>> safe_float(100, min_value=0, max_value=50)
        50.0
    """
    if value is None or value == '':
        return default

    try:
        result = float(value)

        if min_value is not None and result < min_value:
            return min_value
        if max_value is not None and result > max_value:
            return max_value

        return result
    except (ValueError, TypeError):
        return default


def safe_int(
    value: Any,
    default: int = 0,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None
) -> int:
    """
    안전한 int 변환 (범위 검증 포함)

    Args:
        value: 변환할 값
        default: 변환 실패 시 기본값
        min_value: 최소값 (선택)
        max_value: 최대값 (선택)

    Returns:
        int 값

    Examples:
        >>> safe_int("42")
        42
        >>> safe_int("3.14")
        3
        >>> safe_int(None, default=10)
        10
    """
    if value is None or value == '':
        return default

    try:
        result = int(float(value))  # "3.14" -> 3

        if min_value is not None and result < min_value:
            return min_value
        if max_value is not None and result > max_value:
            return max_value

        return result
    except (ValueError, TypeError):
        return default


def safe_decimal(
    value: Any,
    default: Union[Decimal, str, float] = "0.0",
    precision: Optional[int] = None
) -> Decimal:
    """
    안전한 Decimal 변환

    Args:
        value: 변환할 값
        default: 변환 실패 시 기본값
        precision: 소수점 자리수 (선택)

    Returns:
        Decimal 값

    Examples:
        >>> safe_decimal("3.14159", precision=2)
        Decimal('3.14')
        >>> safe_decimal(None, default="1.0")
        Decimal('1.0')
    """
    if value is None or value == '':
        return Decimal(str(default))

    try:
        result = Decimal(str(value))

        if precision is not None:
            quantize_str = f"0.{'0' * precision}"
            result = result.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)

        return result
    except (ValueError, TypeError, Exception):
        return Decimal(str(default))


def validate_settings(
    settings: Dict[str, Any],
    required_fields: List[str],
    type_validators: Optional[Dict[str, Any]] = None
) -> Tuple[bool, Optional[str]]:
    """
    설정 딕셔너리 검증

    Args:
        settings: 검증할 설정 딕셔너리
        required_fields: 필수 필드 리스트
        type_validators: 타입 검증 함수 딕셔너리 (선택)

    Returns:
        (검증 성공 여부, 에러 메시지)

    Example:
        >>> settings = {"api_key": "xxx", "leverage": "10"}
        >>> required = ["api_key", "leverage"]
        >>> validators = {"leverage": lambda x: safe_int(x, min_value=1, max_value=125)}
        >>> is_valid, error = validate_settings(settings, required, validators)
    """
    # 필수 필드 확인
    for field in required_fields:
        if field not in settings:
            return False, f"Missing required field: {field}"
        if settings[field] is None or settings[field] == "":
            return False, f"Field '{field}' cannot be empty"

    # 타입 검증
    if type_validators:
        for field, validator in type_validators.items():
            if field in settings:
                try:
                    settings[field] = validator(settings[field])
                except Exception as e:
                    return False, f"Validation failed for '{field}': {str(e)}"

    return True, None


def parse_numeric(value: Any, value_type: str = 'float') -> Optional[Union[int, float]]:
    """
    숫자 타입으로 안전하게 변환

    Args:
        value: 변환할 값
        value_type: 'int' 또는 'float'

    Returns:
        변환된 숫자 또는 None

    Examples:
        >>> parse_numeric("42", "int")
        42
        >>> parse_numeric("3.14", "float")
        3.14
        >>> parse_numeric("invalid", "float")
        None
    """
    if value is None or value == '':
        return None

    try:
        if value_type.lower() == 'int':
            return int(float(value))
        else:
            return float(value)
    except (ValueError, TypeError):
        return None


def is_true_value(value: Any) -> bool:
    """
    불리언 값 또는 문자열을 안전하게 처리하는 함수
    (parse_bool의 alias로 하위 호환성 유지)

    Args:
        value: 확인할 값

    Returns:
        bool: True/False

    Examples:
        >>> is_true_value(True)
        True
        >>> is_true_value("true")
        True
        >>> is_true_value("false")
        False
        >>> is_true_value(1)
        True
    """
    return parse_bool(value)


# ============================================================================
# 딕셔너리 데이터 변환 함수들
# ============================================================================

def convert_bool_to_string(data_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    딕셔너리 내 부울 값을 문자열로 변환하는 헬퍼 함수

    Args:
        data_dict: 변환할 딕셔너리

    Returns:
        Dict: 부울이 문자열로 변환된 딕셔너리

    Examples:
        >>> convert_bool_to_string({"active": True, "value": 10})
        {'active': 'true', 'value': 10}
        >>> convert_bool_to_string({"enabled": False, "count": 5})
        {'enabled': 'false', 'count': 5}
    """
    converted_dict = {}
    for key, value in data_dict.items():
        if isinstance(value, bool):
            converted_dict[key] = str(value).lower()  # 'true' 또는 'false'로 변환
        else:
            converted_dict[key] = value
    return converted_dict


def convert_bool_to_int(data_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    딕셔너리 내 부울 값을 정수로 변환하는 헬퍼 함수

    Args:
        data_dict: 변환할 딕셔너리

    Returns:
        Dict: 부울이 정수로 변환된 딕셔너리

    Examples:
        >>> convert_bool_to_int({"active": True, "value": 10})
        {'active': 1, 'value': 10}
        >>> convert_bool_to_int({"enabled": False, "count": 5})
        {'enabled': 0, 'count': 5}
    """
    converted_dict = {}
    for key, value in data_dict.items():
        if isinstance(value, bool):
            converted_dict[key] = 1 if value else 0  # 1 또는 0으로 변환
        else:
            converted_dict[key] = value
    return converted_dict
