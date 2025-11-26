# src/core/models/preset.py
"""
Trading Preset Model

프리셋 시스템을 위한 Pydantic 모델 정의.
사용자가 재사용 가능한 트레이딩 설정을 저장하고 관리할 수 있습니다.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator

from shared.constants.default_settings import (
    DEFAULT_PARAMS_SETTINGS,
    DIRECTION_OPTIONS,
    ENTRY_OPTIONS,
    TP_SL_OPTIONS,
    ENTRY_CRITERION_OPTIONS,
    TRAILING_STOP_TYPES,
    ENTRY_AMOUNT_OPTIONS,
)


def generate_preset_id() -> str:
    """8자리 UUID 생성"""
    return str(uuid.uuid4())[:8]


class TradingPreset(BaseModel):
    """
    재사용 가능한 트레이딩 설정 프리셋.

    DEFAULT_PARAMS_SETTINGS의 모든 필드를 포함하며,
    프리셋 메타데이터(이름, 생성일 등)를 추가로 관리합니다.
    """

    # 프리셋 메타데이터
    preset_id: str = Field(default_factory=generate_preset_id)
    owner_id: str  # okx_uid
    name: str = Field(max_length=50)
    description: Optional[str] = Field(default=None, max_length=200)
    version: int = Field(default=1)
    is_default: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # 기본 투자 설정
    btc_investment: float = Field(default=20, ge=1, le=1000000)
    eth_investment: float = Field(default=20, ge=1, le=1000000)
    sol_investment: float = Field(default=20, ge=1, le=1000000)
    entry_amount_option: str = Field(default="usdt")
    symbol_investments: Dict[str, float] = Field(default_factory=dict)

    # 실행 모드 설정
    execution_mode: str = Field(default="api_direct")
    signal_bot_token: Optional[str] = None
    signal_bot_webhook_url: Optional[str] = None
    symbol_execution_modes: Dict[str, str] = Field(default_factory=dict)

    # 레버리지 및 방향
    leverage: int = Field(default=10, ge=1, le=125)
    direction: str = Field(default="롱숏")
    entry_multiplier: float = Field(default=1.0, ge=0.1, le=5.0)

    # 쿨다운 설정
    use_cooldown: bool = Field(default=True)
    cooldown_time: int = Field(default=300, ge=0, le=3000)

    # 트렌드 설정
    use_trend_logic: bool = Field(default=True)
    trend_timeframe: str = Field(default="auto")
    use_trend_close: bool = Field(default=True)

    # RSI 설정
    rsi_length: int = Field(default=14, ge=1, le=100)
    rsi_oversold: int = Field(default=30, ge=0, le=100)
    rsi_overbought: int = Field(default=70, ge=0, le=100)
    entry_option: str = Field(default="돌파")

    # TP 설정
    tp_option: str = Field(default="퍼센트 기준")
    tp1_ratio: int = Field(default=30, ge=0, le=100)
    tp2_ratio: int = Field(default=30, ge=0, le=100)
    tp3_ratio: int = Field(default=40, ge=0, le=100)
    tp1_value: float = Field(default=2.0, ge=0)
    tp2_value: float = Field(default=3.0, ge=0)
    tp3_value: float = Field(default=4.0, ge=0)
    use_tp1: bool = Field(default=True)
    use_tp2: bool = Field(default=True)
    use_tp3: bool = Field(default=True)

    # SL 설정
    use_sl: bool = Field(default=False)
    use_sl_on_last: bool = Field(default=False)
    sl_option: str = Field(default="퍼센트 기준")
    sl_value: float = Field(default=5.0, ge=0.1, le=100)

    # 브레이크이븐 설정
    use_break_even: bool = Field(default=True)
    use_break_even_tp2: bool = Field(default=True)
    use_break_even_tp3: bool = Field(default=True)

    # 피라미딩 설정
    use_check_DCA_with_price: bool = Field(default=True)
    use_rsi_with_pyramiding: bool = Field(default=True)
    entry_criterion: str = Field(default="평균 단가")
    pyramiding_type: str = Field(default="0")
    pyramiding_limit: int = Field(default=4, ge=1, le=10)
    pyramiding_entry_type: str = Field(default="퍼센트 기준")
    pyramiding_value: float = Field(default=3.0, ge=0)

    # 트레일링스탑 설정
    trailing_stop_active: bool = Field(default=True)
    trailing_start_point: str = Field(default="tp3")
    trailing_stop_type: str = Field(default="트레일링 스탑 고정값")
    use_trailing_stop_value_with_tp2_tp3_difference: bool = Field(default=False)
    trailing_stop_offset_value: float = Field(default=0.5, ge=0)

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        if v not in DIRECTION_OPTIONS:
            raise ValueError(f"direction must be one of {DIRECTION_OPTIONS}")
        return v

    @field_validator("entry_option")
    @classmethod
    def validate_entry_option(cls, v: str) -> str:
        if v not in ENTRY_OPTIONS:
            raise ValueError(f"entry_option must be one of {ENTRY_OPTIONS}")
        return v

    @field_validator("tp_option", "sl_option", "pyramiding_entry_type")
    @classmethod
    def validate_tp_sl_option(cls, v: str) -> str:
        if v not in TP_SL_OPTIONS:
            raise ValueError(f"option must be one of {TP_SL_OPTIONS}")
        return v

    @field_validator("entry_criterion")
    @classmethod
    def validate_entry_criterion(cls, v: str) -> str:
        if v not in ENTRY_CRITERION_OPTIONS:
            raise ValueError(f"entry_criterion must be one of {ENTRY_CRITERION_OPTIONS}")
        return v

    @field_validator("trailing_stop_type")
    @classmethod
    def validate_trailing_stop_type(cls, v: str) -> str:
        if v not in TRAILING_STOP_TYPES:
            raise ValueError(f"trailing_stop_type must be one of {TRAILING_STOP_TYPES}")
        return v

    @field_validator("entry_amount_option")
    @classmethod
    def validate_entry_amount_option(cls, v: str) -> str:
        if v not in ENTRY_AMOUNT_OPTIONS:
            raise ValueError(f"entry_amount_option must be one of {ENTRY_AMOUNT_OPTIONS}")
        return v

    def to_settings_dict(self) -> Dict[str, Any]:
        """
        프리셋을 DEFAULT_PARAMS_SETTINGS 형식의 딕셔너리로 변환.
        메타데이터 필드는 제외합니다.
        """
        metadata_fields = {
            "preset_id", "owner_id", "name", "description",
            "version", "is_default", "created_at", "updated_at"
        }
        return {
            k: v for k, v in self.model_dump().items()
            if k not in metadata_fields
        }

    def to_redis_dict(self) -> Dict[str, Any]:
        """Redis 저장용 딕셔너리 변환 (datetime을 ISO 문자열로)"""
        data = self.model_dump()
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_redis_dict(cls, data: Dict[str, Any]) -> "TradingPreset":
        """Redis에서 읽은 딕셔너리로 프리셋 생성"""
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "updated_at" in data and isinstance(data["updated_at"], str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return cls(**data)

    @classmethod
    def from_settings(
        cls,
        owner_id: str,
        name: str,
        settings: Dict[str, Any],
        is_default: bool = False
    ) -> "TradingPreset":
        """
        기존 settings 딕셔너리에서 프리셋 생성.
        마이그레이션 시 사용됩니다.
        """
        # 기본값과 병합
        merged = {**DEFAULT_PARAMS_SETTINGS, **settings}

        # 메타데이터 추가
        merged["owner_id"] = owner_id
        merged["name"] = name
        merged["is_default"] = is_default

        return cls(**merged)

    model_config = {
        "json_schema_extra": {
            "example": {
                "preset_id": "a1b2c3d4",
                "owner_id": "518796558012178692",
                "name": "Conservative SOL",
                "description": "SOL 종목용 보수적 설정",
                "leverage": 5,
                "direction": "롱숏",
                "rsi_length": 14,
                "rsi_oversold": 25,
                "rsi_overbought": 75,
                "pyramiding_limit": 3,
            }
        }
    }


class PresetSummary(BaseModel):
    """프리셋 목록 조회용 요약 모델"""
    preset_id: str
    name: str
    description: Optional[str] = None
    is_default: bool = False
    created_at: datetime
    updated_at: datetime

    # 주요 설정 요약
    leverage: int
    direction: str
    pyramiding_limit: int


class CreatePresetRequest(BaseModel):
    """프리셋 생성 요청 모델"""
    name: str = Field(max_length=50)
    description: Optional[str] = Field(default=None, max_length=200)
    settings: Optional[Dict[str, Any]] = Field(
        default=None,
        description="트레이딩 설정. 없으면 기본값 사용"
    )
    is_default: bool = Field(default=False)


class UpdatePresetRequest(BaseModel):
    """프리셋 수정 요청 모델"""
    name: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None, max_length=200)
    settings: Optional[Dict[str, Any]] = Field(
        default=None,
        description="수정할 트레이딩 설정 (부분 업데이트)"
    )
