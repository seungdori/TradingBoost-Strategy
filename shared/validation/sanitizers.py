"""
Input Sanitization and Validation

Provides comprehensive input validation and sanitization for:
- Trading symbols
- Amounts and prices
- User inputs
- Log data (sensitive information removal)
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from shared.errors import InvalidSymbolException, ValidationException

# ============================================================================
# Symbol Validation
# ============================================================================

# Valid symbol pattern: alphanumeric, forward slash, hyphen, underscore
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9/_-]+$")


def sanitize_symbol(symbol: str) -> str:
    """
    Sanitize and validate trading symbol.

    Args:
        symbol: Raw trading symbol input

    Returns:
        str: Sanitized uppercase symbol

    Raises:
        InvalidSymbolException: If symbol is invalid

    Examples:
        >>> sanitize_symbol("btc/usdt")
        'BTC/USDT'
        >>> sanitize_symbol("BTC-USDT")
        'BTC-USDT'
        >>> sanitize_symbol("invalid symbol!")
        InvalidSymbolException
    """
    if not symbol or not isinstance(symbol, str):
        raise InvalidSymbolException("Symbol cannot be empty")

    # Convert to uppercase and strip whitespace
    symbol = symbol.upper().strip()

    # Check length constraints
    if len(symbol) < 3 or len(symbol) > 20:
        raise InvalidSymbolException(
            f"Symbol length must be between 3 and 20 characters: {symbol}"
        )

    # Validate pattern
    if not SYMBOL_PATTERN.match(symbol):
        raise InvalidSymbolException(
            f"Symbol contains invalid characters. Allowed: A-Z, 0-9, /, -, _: {symbol}"
        )

    return symbol


# ============================================================================
# String Sanitization
# ============================================================================


def sanitize_string(
    value: str,
    max_length: int = 1000,
    allow_special_chars: bool = False,
    strip: bool = True,
) -> str:
    """
    Sanitize general string input.

    Args:
        value: Input string
        max_length: Maximum allowed length
        allow_special_chars: Allow special characters
        strip: Strip whitespace

    Returns:
        str: Sanitized string

    Raises:
        ValidationException: If validation fails
    """
    if not isinstance(value, str):
        raise ValidationException(f"Expected string, got {type(value).__name__}")

    if strip:
        value = value.strip()

    # Check length
    if len(value) > max_length:
        raise ValidationException(
            f"String too long: {len(value)} > {max_length}",
            details={"max_length": max_length, "actual_length": len(value)},
        )

    # Remove control characters
    value = "".join(char for char in value if ord(char) >= 32 or char in "\n\r\t")

    # Optionally remove special characters
    if not allow_special_chars:
        value = re.sub(r"[<>\"'`]", "", value)

    return value


# ============================================================================
# Numeric Validation
# ============================================================================


def validate_numeric_range(
    value: float | int | Decimal | str,
    min_value: float | None = None,
    max_value: float | None = None,
    name: str = "value",
) -> Decimal:
    """
    Validate numeric value within range.

    Args:
        value: Numeric value to validate
        min_value: Minimum allowed value (inclusive)
        max_value: Maximum allowed value (inclusive)
        name: Field name for error messages

    Returns:
        Decimal: Validated decimal value

    Raises:
        ValidationException: If validation fails

    Examples:
        >>> validate_numeric_range(100, min_value=0, max_value=1000)
        Decimal('100')
        >>> validate_numeric_range(-5, min_value=0)
        ValidationException
    """
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationException(
            f"Invalid {name}: must be a valid number",
            details={"value": str(value), "field": name},
        )

    # Check for NaN or Infinity
    if not decimal_value.is_finite():
        raise ValidationException(
            f"Invalid {name}: must be a finite number",
            details={"value": str(value), "field": name},
        )

    # Validate range
    if min_value is not None and decimal_value < Decimal(str(min_value)):
        raise ValidationException(
            f"{name} must be >= {min_value}",
            details={
                "value": str(decimal_value),
                "min": min_value,
                "field": name,
            },
        )

    if max_value is not None and decimal_value > Decimal(str(max_value)):
        raise ValidationException(
            f"{name} must be <= {max_value}",
            details={
                "value": str(decimal_value),
                "max": max_value,
                "field": name,
            },
        )

    return decimal_value


def validate_trading_amount(amount: float | str, min_amount: float = 0.00001) -> Decimal:
    """
    Validate trading amount.

    Args:
        amount: Trading amount
        min_amount: Minimum allowed amount

    Returns:
        Decimal: Validated amount

    Raises:
        ValidationException: If amount is invalid
    """
    return validate_numeric_range(
        amount,
        min_value=min_amount,
        max_value=1_000_000_000,  # 1 billion max
        name="amount",
    )


def validate_trading_price(price: float | str, min_price: float = 0.00000001) -> Decimal:
    """
    Validate trading price.

    Args:
        price: Trading price
        min_price: Minimum allowed price

    Returns:
        Decimal: Validated price

    Raises:
        ValidationException: If price is invalid
    """
    return validate_numeric_range(
        price,
        min_value=min_price,
        max_value=10_000_000,  # 10 million max
        name="price",
    )


# ============================================================================
# Trading-Specific Validation
# ============================================================================


VALID_ORDER_SIDES = {"buy", "sell", "long", "short"}


def validate_order_side(side: str) -> str:
    """
    Validate order side.

    Args:
        side: Order side (buy/sell/long/short)

    Returns:
        str: Validated lowercase order side

    Raises:
        ValidationException: If order side is invalid
    """
    if not isinstance(side, str):
        raise ValidationException(
            f"Order side must be string, got {type(side).__name__}"
        )

    side = side.lower().strip()

    if side not in VALID_ORDER_SIDES:
        raise ValidationException(
            f"Invalid order side: {side}",
            details={
                "value": side,
                "valid_values": list(VALID_ORDER_SIDES),
            },
        )

    return side


# ============================================================================
# Log Data Sanitization
# ============================================================================

# Sensitive keywords to redact from logs
SENSITIVE_KEYWORDS = {
    "password",
    "passwd",
    "pwd",
    "api_key",
    "apikey",
    "api_secret",
    "apisecret",
    "secret",
    "secret_key",
    "secretkey",
    "passphrase",
    "private_key",
    "privatekey",
    "token",
    "auth_token",
    "authtoken",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "session_id",
    "sessionid",
    "cookie",
    "authorization",
    "credentials",
}


def sanitize_log_data(data: dict[str, Any], redact_value: str = "***REDACTED***") -> dict[str, Any]:
    """
    Remove sensitive data from logs.

    Recursively scans dictionary and redacts values for keys containing
    sensitive keywords.

    Args:
        data: Dictionary to sanitize
        redact_value: Replacement value for sensitive data

    Returns:
        dict: Sanitized dictionary with sensitive values redacted

    Examples:
        >>> sanitize_log_data({"user": "john", "password": "secret123"})
        {'user': 'john', 'password': '***REDACTED***'}
        >>> sanitize_log_data({"config": {"api_key": "xyz"}})
        {'config': {'api_key': '***REDACTED***'}}
    """
    sanitized: dict[str, Any] = {}

    for key, value in data.items():
        key_lower = key.lower()

        # Check if key contains sensitive keyword
        is_sensitive = any(keyword in key_lower for keyword in SENSITIVE_KEYWORDS)

        if is_sensitive:
            sanitized[key] = redact_value
        elif isinstance(value, dict):
            # Recursively sanitize nested dictionaries
            sanitized[key] = sanitize_log_data(value, redact_value)
        elif isinstance(value, list):
            # Sanitize lists of dictionaries
            sanitized[key] = [
                sanitize_log_data(item, redact_value) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value

    return sanitized


# ============================================================================
# URL/Path Sanitization
# ============================================================================


def sanitize_path(path: str, max_length: int = 500) -> str:
    """
    Sanitize file path or URL path.

    Args:
        path: Path to sanitize
        max_length: Maximum path length

    Returns:
        str: Sanitized path

    Raises:
        ValidationException: If path is invalid
    """
    if not isinstance(path, str):
        raise ValidationException(f"Path must be string, got {type(path).__name__}")

    path = path.strip()

    # Check length
    if len(path) > max_length:
        raise ValidationException(
            f"Path too long: {len(path)} > {max_length}",
            details={"max_length": max_length, "actual_length": len(path)},
        )

    # Prevent path traversal
    if ".." in path or path.startswith("/"):
        raise ValidationException(
            "Path contains invalid patterns",
            details={"path": path},
        )

    # Remove null bytes
    if "\x00" in path:
        raise ValidationException("Path contains null bytes")

    return path
