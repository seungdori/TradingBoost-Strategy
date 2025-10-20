"""트레이딩 관련 공통 유틸리티 함수"""
import logging
import math
import traceback
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


def get_actual_order_type(order_data: dict[str, Any]) -> str:
    """
    실제 order_type을 결정합니다.
    order_type이 없거나 불명확한 경우 order_name을 확인합니다.

    Args:
        order_data: Redis에서 가져온 주문 데이터

    Returns:
        str: 실제 order_type (tp1, tp2, tp3, sl, break_even 등)

    Examples:
        >>> order_data = {"order_type": "limit", "order_name": "tp1"}
        >>> get_actual_order_type(order_data)
        'tp1'

        >>> order_data = {"order_type": "sl", "order_name": ""}
        >>> get_actual_order_type(order_data)
        'sl'
    """
    order_type: str = str(order_data.get("order_type", "unknown"))
    order_name: str = str(order_data.get("order_name", ""))

    # order_type이 제대로 설정되어 있으면 그대로 사용
    # limit, market은 주문 방식이지 주문 목적이 아니므로 order_name 확인 필요
    if order_type not in ["unknown", "limit", "market", "", None]:
        return order_type

    # order_name이 있고 유효한 경우 사용
    if order_name and isinstance(order_name, str):
        # tp로 시작하는 경우 (tp1, tp2, tp3)
        if order_name.startswith("tp") and len(order_name) >= 3:
            # tp1, tp2, tp3만 허용
            if order_name in ["tp1", "tp2", "tp3"]:
                return order_name
        # sl인 경우
        elif order_name == "sl":
            return "sl"
        # break_even인 경우
        elif order_name == "break_even":
            return "break_even"

    # 둘 다 없으면 unknown 반환
    return "unknown"


def is_valid_order_type(order_type: str) -> bool:
    """
    주문 타입의 유효성을 확인합니다.

    Args:
        order_type: 확인할 주문 타입

    Returns:
        bool: 유효한 주문 타입인지 여부

    Examples:
        >>> is_valid_order_type("tp1")
        True
        >>> is_valid_order_type("invalid")
        False
    """
    valid_types = ["tp1", "tp2", "tp3", "sl", "break_even", "limit", "market"]
    return order_type in valid_types


def normalize_order_type(order_type: str) -> str:
    """
    주문 타입을 정규화합니다.

    Args:
        order_type: 정규화할 주문 타입

    Returns:
        str: 정규화된 주문 타입

    Examples:
        >>> normalize_order_type("TP1")
        'tp1'
        >>> normalize_order_type("BREAK_EVEN")
        'break_even'
    """
    if not order_type:
        return "unknown"

    normalized = order_type.lower().strip()

    # 유효성 검사
    if is_valid_order_type(normalized):
        return normalized

    return "unknown"


def parse_order_info(order_data: dict[str, Any]) -> dict[str, Any]:
    """
    주문 데이터를 파싱하여 필요한 정보를 추출합니다.

    Args:
        order_data: 주문 데이터 딕셔너리

    Returns:
        dict: 파싱된 주문 정보
        {
            'order_type': str,
            'order_name': str,
            'price': float,
            'quantity': float,
            'side': str,
            'status': str
        }

    Examples:
        >>> order_data = {
        ...     "order_type": "limit",
        ...     "order_name": "tp1",
        ...     "price": 50000.0,
        ...     "quantity": 0.01,
        ...     "side": "long"
        ... }
        >>> info = parse_order_info(order_data)
        >>> info['order_type']
        'tp1'
    """
    return {
        'order_type': get_actual_order_type(order_data),
        'order_name': str(order_data.get('order_name', '')),
        'price': float(order_data.get('price', 0.0)),
        'quantity': float(order_data.get('quantity', 0.0)),
        'side': str(order_data.get('side', '')),
        'status': str(order_data.get('status', ''))
    }


def is_tp_order(order_type: str) -> bool:
    """
    TP(Take Profit) 주문인지 확인합니다.

    Args:
        order_type: 주문 타입

    Returns:
        bool: TP 주문 여부

    Examples:
        >>> is_tp_order("tp1")
        True
        >>> is_tp_order("sl")
        False
    """
    return order_type in ["tp1", "tp2", "tp3"]


def is_sl_order(order_type: str) -> bool:
    """
    SL(Stop Loss) 주문인지 확인합니다.

    Args:
        order_type: 주문 타입

    Returns:
        bool: SL 주문 여부

    Examples:
        >>> is_sl_order("sl")
        True
        >>> is_sl_order("tp1")
        False
    """
    return order_type == "sl"


def is_break_even_order(order_type: str) -> bool:
    """
    Break Even 주문인지 확인합니다.

    Args:
        order_type: 주문 타입

    Returns:
        bool: Break Even 주문 여부

    Examples:
        >>> is_break_even_order("break_even")
        True
        >>> is_break_even_order("tp1")
        False
    """
    return order_type == "break_even"


# ============================================================================
# 주문 계약 및 수량 관련 함수
# ============================================================================

async def get_perpetual_instruments() -> list[dict[str, Any]] | None:
    """
    OKX Perpetual 종목 정보를 가져옵니다.

    Returns:
        List[Dict]: Perpetual 종목 정보 리스트 또는 None
    """
    try:
        from shared.database.redis import get_redis
        from shared.utils.redis_utils import get_redis_data, set_redis_data

        redis_client = await get_redis()

        # Redis에서 데이터 확인
        cached_data = await get_redis_data(redis_client, 'perpetual_instruments')
        if cached_data:
            return list(cached_data) if isinstance(cached_data, list) else None

        # 캐시된 데이터가 없으면 API 호출
        base_url = "https://www.okx.com"
        # SSL 검증을 비활성화하는 옵션 추가
        conn = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=conn) as session:
            url = f"{base_url}/api/v5/public/instruments?instType=SWAP"
            async with session.get(url) as response:
                data: dict[str, Any] = await response.json()

        # 데이터를 Redis에 저장
        if data and 'data' in data:
            instruments: list[dict[str, Any]] = data['data']
            await set_redis_data(redis_client, 'perpetual_instruments', instruments)
            return instruments
        else:
            logger.warning("Invalid response from OKX API")
            return None

    except Exception as e:
        logger.error(f"Error in get_perpetual_instruments: {str(e)}")
        traceback.print_exc()
        return None


def get_lot_sizes(instruments: list[dict[str, Any]]) -> dict[str, tuple[float, float, str]]:
    """
    종목별 계약 단위 정보를 정리합니다.

    Args:
        instruments: Perpetual 종목 정보 리스트

    Returns:
        Dict: {symbol: (lot_size, contract_value, base_currency)}
    """
    lot_sizes = {}
    for instrument in instruments:
        symbol = instrument['instId']
        lot_size = float(instrument['lotSz'])
        contract_value = float(instrument['ctVal'])
        base_currency = symbol.split('-')[0]
        lot_sizes[symbol] = (lot_size, contract_value, base_currency)
    return lot_sizes


async def round_to_qty(symbol: str, qty: float, lot_sizes: dict[str, Any]) -> int:
    """
    수량을 계약 수로 변환하고 내림합니다.

    Args:
        symbol: 거래 심볼 (예: BTC-USDT-SWAP)
        qty: 수량 (예: 0.02 BTC)
        lot_sizes: get_lot_sizes()로 얻은 계약 정보

    Returns:
        int: 내림된 계약 수

    Raises:
        ValueError: 유효하지 않은 심볼인 경우
    """
    if symbol not in lot_sizes:
        raise ValueError(f"{symbol} is not a valid Perpetual instrument.")
    if not symbol.endswith('-USDT-SWAP'):
        raise ValueError(f"{symbol} is not a USDT-SWAP instrument.")

    lot_size, contract_value, _ = lot_sizes[symbol]

    # qty는 실제 수량(예: 0.02 BTC)
    # contract_value는 한 계약당 기초자산의 양(예: BTC의 경우 0.01 BTC)
    contracts = qty / contract_value  # 계약 수 계산
    rounded_contracts: int = int(math.floor(contracts))  # 계약 수 내림

    logger.debug(f"round_to_qty - 입력 수량: {qty}, 계약 가치: {contract_value}, "
                f"계산된 계약 수: {contracts}, 반올림된 계약 수: {rounded_contracts}")

    return rounded_contracts


async def contracts_to_qty(symbol: str, contracts: int) -> float | None:
    """
    계약 수를 실제 수량으로 변환합니다.

    Args:
        symbol: 거래 심볼 (예: BTC-USDT-SWAP)
        contracts: 계약 수

    Returns:
        float: 실제 수량 또는 None (오류 시)
    """
    try:
        perpetual_instruments = await get_perpetual_instruments()
        if not perpetual_instruments:
            logger.error("Failed to get perpetual instruments")
            return None

        lot_sizes = get_lot_sizes(perpetual_instruments)

        if not symbol.endswith('-USDT-SWAP'):
            raise ValueError(f"{symbol} is not a USDT-SWAP instrument.")

        lot_size, contract_value, _ = lot_sizes[symbol]
        qty = contracts * contract_value  # 계약 수에 계약 가치를 곱해서 실제 수량 계산

        logger.debug(f"contracts_to_qty - 계약 수: {contracts}, 계약 가치: {contract_value}, 수량: {qty}")

        return qty
    except Exception as e:
        logger.error(f"Error in contracts_to_qty: {str(e)}")
        traceback.print_exc()
        return None


def split_contracts(total_contracts: int) -> tuple[int, int, int]:
    """
    계약 수를 30%, 30%, 40%로 분할하고 최소 계약 단위로 내림합니다.

    Args:
        total_contracts: 총 계약 수

    Returns:
        Tuple[int, int, int]: (qty1, qty2, qty3)
    """
    qty1 = math.floor(total_contracts * 0.3)
    qty2 = math.ceil(total_contracts * 0.3)
    qty3 = total_contracts - (qty1 + qty2)

    logger.debug(f"split_contracts - 총 계약: {total_contracts}, "
                f"분할 결과: qty1={qty1}, qty2={qty2}, qty3={qty3}")

    return qty1, qty2, qty3


# ============================================================================
# Redis 기반 계약 및 Tick Size 조회 함수
# ============================================================================

async def get_contract_size(symbol: str, redis_client: Any = None) -> float:
    """
    Redis에서 심볼의 계약 크기를 조회합니다.

    Args:
        symbol: 거래 심볼
        redis_client: Redis 클라이언트 (선택, None이면 자동 생성)

    Returns:
        float: 계약 크기 (기본값: 0.01)
    """
    try:
        if redis_client is None:
            from shared.database.redis import get_redis
            redis_client = await get_redis()

        import json

        spec_key = await redis_client.get(f"symbol_info:contract_specifications")

        if not spec_key:
            logger.warning(f"Contract specifications not found in Redis for {symbol}")
            return 0.01

        spec_json: dict[str, Any] = json.loads(spec_key)
        spec: dict[str, Any] | None = spec_json.get(symbol)

        if not spec:
            logger.warning(f"Symbol specification not found: {symbol}")
            return 0.01

        contract_size: float = float(spec.get("contractSize", 0.01))

        logger.debug(f"Contract size for {symbol}: {contract_size}")

        return contract_size

    except Exception as e:
        logger.error(f"Error getting contract size for {symbol}: {str(e)}")
        return 0.01


async def get_tick_size_from_redis(symbol: str, redis_client: Any = None) -> float | None:
    """
    Redis에서 심볼의 tick size를 조회합니다.

    Args:
        symbol: 거래 심볼
        redis_client: Redis 클라이언트 (선택, None이면 자동 생성)

    Returns:
        float: Tick size 또는 None
    """
    try:
        if redis_client is None:
            from shared.database.redis import get_redis
            redis_client = await get_redis()

        import json

        spec_json = await redis_client.get("symbol_info:contract_specifications")
        if spec_json:
            specs = json.loads(spec_json)
            spec = specs.get(symbol)
            tick_size = spec.get("tickSize") if spec else None
            if tick_size is None:
                logger.error(f"Tick size not found in contract specification for {symbol}")
            return tick_size
        else:
            logger.error(f"Contract specification not found for symbol: {symbol}")
            return None
    except Exception as e:
        logger.error(f"Error fetching tick size for {symbol}: {str(e)}")
        return None


async def get_minimum_qty_from_contract_spec(symbol: str, redis_client: Any = None) -> float:
    """
    Redis에 저장된 contract_specifications에서 해당 심볼의 최소 주문 수량을 반환합니다.
    (OKX 특화 함수)

    Args:
        symbol: 거래 심볼
        redis_client: Redis 클라이언트 (선택, None이면 자동 생성)

    Returns:
        float: 최소 주문 수량 (기본값: 0.1)
    """
    try:
        if redis_client is None:
            from shared.database.redis import get_redis
            redis_client = await get_redis()

        import json

        spec_json = await redis_client.get("symbol_info:contract_specifications")
        if not spec_json:
            logger.error(f"Contract specification not found for symbol: {symbol}")
            return 0.1

        specs = json.loads(spec_json)
        spec = specs.get(symbol)
        if not spec:
            logger.error(f"Specification not found for symbol: {symbol}")
            return 0.1

        min_size = spec.get("minSize")
        contract_size = spec.get("contractSize")
        if min_size is None or contract_size is None:
            logger.error(f"minSize or contractSize not defined for symbol: {symbol}")
            return 0.1

        # 정수 스케일링을 위한 소수점 자릿수 계산
        min_size_decimals = len(str(min_size).split('.')[-1]) if '.' in str(min_size) else 0
        contract_size_decimals = len(str(contract_size).split('.')[-1]) if '.' in str(contract_size) else 0
        total_decimals = min_size_decimals + contract_size_decimals

        # 정수로 변환하여 계산
        multiplier = 10 ** total_decimals
        min_size_int = int(float(min_size) * (10 ** min_size_decimals))
        contract_size_int = int(float(contract_size) * (10 ** contract_size_decimals))

        # 계산 후 원래 소수점으로 복원
        result = (min_size_int * contract_size_int) / multiplier

        # 8자리까지 반올림 (정수 연산으로)
        final_multiplier = 10 ** 8
        rounded_result = int(result * final_multiplier) / final_multiplier

        return rounded_result

    except Exception as e:
        logger.error(f"Error fetching minimum quantity for {symbol}: {str(e)}")
        return 0.1


# Backward compatibility alias
async def get_minimum_qty(symbol: str, redis_client: Any = None) -> float:
    """Deprecated: Use get_minimum_qty_from_contract_spec instead"""
    return await get_minimum_qty_from_contract_spec(symbol, redis_client)


async def get_min_notional(
    symbol: str,
    exchange_instance: Any,
    redis_client: Any = None,
    default_value: float = 10.0
) -> float:
    """
    거래소별 최소 주문 금액을 조회합니다. (Redis 캐싱)

    Args:
        symbol: 심볼
        exchange_instance: CCXT 거래소 인스턴스
        redis_client: Redis 클라이언트 (None이면 자동 생성)
        default_value: 기본값

    Returns:
        float: 최소 주문 금액

    Examples:
        >>> # OKX
        >>> min_notional = await get_min_notional('BTC-USDT-SWAP', okx_exchange)
        >>> # Upbit
        >>> min_notional = await get_min_notional('KRW-BTC', upbit_exchange)
    """
    from shared.database.redis import get_redis
    from shared.utils.redis_utils import get_redis_data, set_redis_data

    new_redis_flag = False
    if redis_client is None:
        redis_client = await get_redis()
        new_redis_flag = True

    try:
        # Redis 키 생성
        redis_key = f"min_notional:{exchange_instance.id}:{symbol}"

        # Redis에서 데이터 확인
        cached_min_notional = await get_redis_data(redis_client, redis_key)
        if cached_min_notional is not None:
            return float(cached_min_notional)

        # 캐시된 데이터가 없으면 거래소 API 호출
        try:
            markets = await exchange_instance.load_markets()
            market = None

            if exchange_instance.name.lower() == 'upbit':
                # Upbit: 'KRW-BTC' -> 'BTC/KRW'
                symbol_parts = symbol.split('-')
                converted_symbol = f"{symbol_parts[1]}/{symbol_parts[0]}"
                market = markets.get(converted_symbol, None)
            else:
                # OKX, Binance, Bitget 등
                market = markets.get(symbol.replace("/", ""))

            if market is not None:
                if str(exchange_instance).lower() == 'upbit':
                    min_notional = float(market['precision']['amount'])
                elif exchange_instance.id == 'bitget':
                    min_notional = float(market['limits']['amount']['min'] * market['limits']['price']['min'])
                elif exchange_instance.id == 'okx':
                    min_notional = float(market['limits']['amount']['min'])
                else:  # 바이낸스 등 다른 거래소
                    min_notional = float(market['limits']['cost']['min'])
            else:
                min_notional = default_value
        except Exception as e:
            logger.error(f"Error in get_min_notional for {symbol}: {str(e)}")
            min_notional = default_value

        # 결과를 Redis에 저장 (1일)
        await set_redis_data(redis_client, redis_key, min_notional, expiry=86400)
        return min_notional
    finally:
        if new_redis_flag and redis_client is not None:
            await redis_client.aclose()


async def round_to_tick_size(
    value: float,
    current_price: float | None = None,
    symbol: str | None = None,
    redis_client: Any = None
) -> float:
    """
    가격을 tick size 또는 heuristics에 따라 반올림합니다.

    Args:
        value: 반올림할 가격
        current_price: tick_size가 없을 경우 기준 가격
        symbol: 종목 코드 (tick_size를 가져오기 위함)
        redis_client: Redis 클라이언트 (선택, None이면 자동 생성)

    Returns:
        float: 반올림된 가격
    """
    from decimal import ROUND_HALF_UP, Decimal

    logger.debug(f"round_to_tick_size - value={value}, current_price={current_price}, symbol={symbol}")

    if symbol:
        tick_size = await get_tick_size_from_redis(symbol, redis_client)
        logger.debug(f"Redis tick_size: {tick_size}")
    else:
        tick_size = 0.001  # 기본 tick size
        logger.debug(f"Using default tick_size: {tick_size}")

    value_decimal: Decimal = Decimal(str(value))  # 부동소수점 오차 방지

    if tick_size and tick_size > 0:
        tick_size_decimal: Decimal = Decimal(str(tick_size))
        rounded = (value_decimal / tick_size_decimal).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick_size_decimal
        return float(rounded)

    # tick size가 없을 경우, current_price 기준 반올림
    if current_price is None:
        return float(value_decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    if current_price < 0.01:
        decimals = "0.00001"
    elif current_price < 0.1:
        decimals = "0.00001"
    elif current_price < 10:
        decimals = "0.0001"
    elif current_price < 1000:
        decimals = "0.001"
    else:
        decimals = "0.01"

    rounded = value_decimal.quantize(Decimal(decimals), rounding=ROUND_HALF_UP)
    return float(rounded)
