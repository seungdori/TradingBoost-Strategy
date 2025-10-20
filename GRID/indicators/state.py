"""
Indicator State Management for Incremental Calculations
"""
import json
import logging
from typing import Any, Dict, Optional

import numpy as np

from shared.config import settings

# Note: Redis client is no longer created globally
# Use get_redis() from shared.database.redis in async functions


class IndicatorState:
    """
    기술 지표의 상태를 저장하고 증분 계산을 가능하게 하는 클래스
    """
    def __init__(self):
        # ADX 관련 상태
        self.adx_last_idx = -1
        self.adx_state = None
        self.plus_di = None
        self.minus_di = None
        self.adx = None

        # MAMA/FAMA 관련 상태
        self.mama_last_idx = -1
        self.mama_values = None
        self.fama_values = None
        self.prev_phase = 0.0
        self.prev_I2 = 0.0
        self.prev_Q2 = 0.0
        self.prev_Re = 0.0
        self.prev_Im = 0.0
        self.prev_period = 0.0

        # ATR 관련 상태
        self.atr_last_idx = -1
        self.atr_values = None
        self.prev_atr = None

        # 그리드 레벨 관련 상태
        self.grid_last_idx = -1
        self.grid_levels = None

        # 마지막 저장 시간
        self.last_update_time = None

    def to_dict(self):
        """상태를 딕셔너리로 변환하여 Redis에 저장할 수 있게 합니다"""
        return {
            'adx_last_idx': self.adx_last_idx,
            'adx_state': self.adx_state,
            'plus_di': self.plus_di.tolist() if isinstance(self.plus_di, np.ndarray) else self.plus_di,
            'minus_di': self.minus_di.tolist() if isinstance(self.minus_di, np.ndarray) else self.minus_di,
            'adx': self.adx.tolist() if isinstance(self.adx, np.ndarray) else self.adx,
            'mama_last_idx': self.mama_last_idx,
            'mama_values': self.mama_values.tolist() if isinstance(self.mama_values, np.ndarray) else self.mama_values,
            'fama_values': self.fama_values.tolist() if isinstance(self.fama_values, np.ndarray) else self.fama_values,
            'prev_phase': self.prev_phase,
            'prev_I2': self.prev_I2,
            'prev_Q2': self.prev_Q2,
            'prev_Re': self.prev_Re,
            'prev_Im': self.prev_Im,
            'prev_period': self.prev_period,
            'atr_last_idx': self.atr_last_idx,
            'atr_values': self.atr_values.tolist() if isinstance(self.atr_values, np.ndarray) else self.atr_values,
            'prev_atr': self.prev_atr,
            'grid_last_idx': self.grid_last_idx,
            'grid_levels': self.grid_levels.tolist() if isinstance(self.grid_levels, np.ndarray) else self.grid_levels,
            'last_update_time': self.last_update_time
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> 'IndicatorState':
        """딕셔너리에서 상태를 복원합니다"""
        if not data:
            return cls()

        state = cls()
        state.adx_last_idx = data.get('adx_last_idx', -1)
        state.adx_state = data.get('adx_state')

        # 숫자 배열 데이터 변환
        for attr in ['plus_di', 'minus_di', 'adx', 'mama_values', 'fama_values', 'atr_values', 'grid_levels']:
            value = data.get(attr)
            if value is not None:
                setattr(state, attr, np.array(value))

        # 스칼라 값 복원
        state.prev_phase = data.get('prev_phase', 0.0)
        state.prev_I2 = data.get('prev_I2', 0.0)
        state.prev_Q2 = data.get('prev_Q2', 0.0)
        state.prev_Re = data.get('prev_Re', 0.0)
        state.prev_Im = data.get('prev_Im', 0.0)
        state.prev_period = data.get('prev_period', 0.0)
        state.mama_last_idx = data.get('mama_last_idx', -1)
        state.atr_last_idx = data.get('atr_last_idx', -1)
        state.prev_atr = data.get('prev_atr')
        state.grid_last_idx = data.get('grid_last_idx', -1)
        state.last_update_time = data.get('last_update_time')

        return state


async def get_indicator_state(exchange_name: str, symbol: str, direction: str = 'long') -> IndicatorState:
    """
    Redis에서 지표 상태를 가져옵니다

    Parameters:
    -----------
    exchange_name : str
        거래소 이름
    symbol : str
        심볼
    direction : str
        거래 방향 ('long', 'short', 'long-short')

    Returns:
    --------
    IndicatorState
        복원된 지표 상태 객체
    """
    from shared.database.redis_patterns import redis_context

    async with redis_context() as redis:
        key = f"{exchange_name}:{symbol}:{direction}:indicator_state"
        state_json = await redis.get(key)

        if state_json:
            try:
                state_dict = json.loads(state_json)
                return IndicatorState.from_dict(state_dict)
            except Exception as e:
                logging.error(f"지표 상태 복원 중 오류: {e}")

        return IndicatorState()


async def save_indicator_state(state: IndicatorState, exchange_name: str, symbol: str, direction: str = 'long') -> None:
    """
    지표 상태를 Redis에 저장합니다

    Parameters:
    -----------
    state : IndicatorState
        저장할 지표 상태 객체
    exchange_name : str
        거래소 이름
    symbol : str
        심볼
    direction : str
        거래 방향 ('long', 'short', 'long-short')
    """
    from shared.database.redis_patterns import redis_context

    async with redis_context() as redis:
        key = f"{exchange_name}:{symbol}:{direction}:indicator_state"
        state_dict = state.to_dict()
        state_json = json.dumps(state_dict)
        await redis.set(key, state_json)

        # TTL 설정 (3일)
        await redis.expire(key, 60 * 60 * 24 * 3)
