"""포지션 데이터 처리 헬퍼 함수

GRID와 HYPERRSI에서 공통으로 사용되는 포지션 데이터 처리 로직
"""
import json
from typing import Any, Dict, List, Optional

from shared.logging import get_logger

logger = get_logger(__name__)


def process_position_data(positions_data: Any, symbol: str) -> float:
    """
    OKX 포지션 데이터를 처리하여 특정 심볼의 포지션 수량 반환

    Args:
        positions_data: 포지션 데이터 (list, dict, 또는 JSON 문자열)
        symbol: 조회할 심볼

    Returns:
        float: 포지션 수량 (포지션이 없으면 0.0)
    """
    # JSON 문자열인 경우 파싱
    if isinstance(positions_data, str):
        try:
            positions_data = json.loads(positions_data)
        except json.JSONDecodeError:
            logger.warning("Failed to parse positions_data as JSON")
            return 0.0

    # List 형태의 포지션 데이터 처리
    if isinstance(positions_data, list):
        for position in positions_data:
            if not isinstance(position, dict):
                continue
            if position.get('instId') == symbol:
                try:
                    quantity = float(position.get('pos', '0'))
                    logger.debug(f"{symbol} position: {quantity}")
                    return quantity
                except (KeyError, ValueError) as e:
                    logger.error(f"Error processing position data: {e}")
        return 0.0

    # WebSocket 응답 형태 (dict with 'data' key)
    if isinstance(positions_data, dict) and 'data' in positions_data:
        for position in positions_data['data']:
            if position.get('instId') == symbol:
                try:
                    quantity = float(position.get('pos', '0'))
                    logger.debug(f"{symbol} position: {quantity}")
                    return quantity
                except (KeyError, ValueError) as e:
                    logger.error(f"Error processing position data: {e}")
        return 0.0

    # 예상치 못한 데이터 구조
    logger.warning(f"Unexpected data structure: {type(positions_data)}")
    return 0.0


def extract_position_info(position_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    포지션 데이터에서 주요 정보 추출

    Args:
        position_data: OKX 포지션 데이터

    Returns:
        Dict: 추출된 포지션 정보
    """
    return {
        'symbol': position_data.get('instId'),
        'entry_price': float(position_data.get('avgPx', '0')),
        'quantity': float(position_data.get('pos', '0')),
        'leverage': float(position_data.get('lever', '1')),
        'mark_price': float(position_data.get('markPx', '0')),
        'unrealized_pnl': float(position_data.get('upl', '0')),
        'margin': float(position_data.get('margin', '0')),
    }


def filter_active_positions(positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    활성 포지션만 필터링 (수량이 0이 아닌 포지션)

    Args:
        positions: 포지션 데이터 리스트

    Returns:
        List[Dict]: 활성 포지션 리스트
    """
    return [
        pos for pos in positions
        if abs(float(pos.get('pos', '0'))) > 0
    ]
