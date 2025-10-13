import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from HYPERRSI.src.services.redis_service import ApiKeyService, RedisService
from HYPERRSI.src.services.timescale_service import TimescaleUserService
from shared.constants.default_settings import (
    DEFAULT_DUAL_SIDE_ENTRY_SETTINGS,
    DEFAULT_PARAMS_SETTINGS,
    SETTINGS_CONSTRAINTS,
)
from shared.database.redis_helper import get_redis_client

router = APIRouter(prefix="/settings", tags=["User Settings"])
redis_service = RedisService()
logger = logging.getLogger(__name__)


async def get_api_keys_from_timescale(identifier: str) -> Optional[Dict[str, Any]]:
    try:
        return await TimescaleUserService.get_api_keys(str(identifier))
    except Exception as exc:
        logger.error(f"Timescale API 키 조회 실패: {exc}")
        return None


async def get_timescale_user(identifier: str):
    try:
        return await TimescaleUserService.fetch_user(str(identifier))
    except Exception as exc:
        logger.error(f"Timescale 사용자 조회 실패: {exc}")
        return None


class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, Any] = Field(..., description="사용자 설정 업데이트")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "settings": {
                    "leverage": 10,
                    "direction": "롱숏",
                    "tp1_value": 2.0
                }
            }
        }
    }


class SettingsResponse(BaseModel):
    user_id: str
    settings: Dict[str, Any]
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": 123456789,
                "settings": {
                    "leverage": 10,
                    "direction": "롱숏",
                    "entry_multiplier": 1.0,
                    "use_cooldown": True
                }
            }
        }
    }


def validate_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """설정값 유효성 검사"""
    validated_settings = {}
    
    for key, value in settings.items():
        if key in SETTINGS_CONSTRAINTS:
            constraints = SETTINGS_CONSTRAINTS[key]
            if isinstance(value, (int, float)):
                if value < constraints["min"] or value > constraints["max"]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{key} 값은 {constraints['min']}에서 {constraints['max']} 사이여야 합니다."
                    )
        validated_settings[key] = value
    
    return validated_settings


@router.get(
    "/{user_id}",
    response_model=SettingsResponse,
    summary="사용자 트레이딩 설정 조회",
    description="""
# 사용자 트레이딩 설정 조회

사용자의 트레이딩 전략 설정을 조회합니다. 설정이 없는 경우 자동으로 기본 설정을 생성하고 반환합니다.

## 경로 파라미터

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 예시: "518796558012178692", "1709556958"

## 동작 방식

1. **사용자 확인**: Redis에서 API 키 존재 여부 확인
2. **자동 생성**: API 키가 없으면 TimescaleDB에서 조회하여 자동 생성
3. **설정 조회**: Redis에서 사용자 설정 조회
4. **기본값 반환**: 설정이 없으면 기본 설정 생성 및 저장
5. **응답 반환**: 사용자 ID와 설정 정보 반환

## 반환 데이터 구조

- **user_id** (string): 사용자 식별자
- **settings** (object): 트레이딩 설정
  - **leverage** (integer): 레버리지 배율 (1-125)
  - **direction** (string): 거래 방향 ("롱", "숏", "롱숏")
  - **entry_multiplier** (float): 진입 배율 (0.1-10.0)
  - **use_cooldown** (boolean): 쿨다운 사용 여부
  - **tp1_value** (float): 1차 익절 목표 (%)
  - **tp2_value** (float): 2차 익절 목표 (%)
  - **tp3_value** (float): 3차 익절 목표 (%)
  - **sl_value** (float): 손절 목표 (%)
  - **use_dual_side_entry** (boolean): 양방향 진입 사용 여부

## 사용 시나리오

- ⚙️ **설정 로드**: 앱 시작 시 사용자 설정 불러오기
-  **초기화**: 신규 사용자의 기본 설정 자동 생성
-  **설정 확인**: 현재 전략 파라미터 확인
-  **동기화**: 다중 디바이스 간 설정 동기화

## 예시 URL

```
GET /settings/518796558012178692
GET /settings/1709556958
```
""",
    responses={
        200: {
            "description": " 사용자 설정 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "existing_user": {
                            "summary": "기존 사용자 설정",
                            "value": {
                                "user_id": "518796558012178692",
                                "settings": {
                                    "leverage": 10,
                                    "direction": "롱숏",
                                    "entry_multiplier": 1.0,
                                    "use_cooldown": True,
                                    "tp1_value": 2.0,
                                    "tp2_value": 3.0,
                                    "tp3_value": 4.0,
                                    "sl_value": 1.5,
                                    "use_dual_side_entry": False
                                }
                            }
                        },
                        "new_user_default": {
                            "summary": "신규 사용자 (기본 설정)",
                            "value": {
                                "user_id": "1709556958",
                                "settings": {
                                    "leverage": 10,
                                    "direction": "롱숏",
                                    "entry_multiplier": 1.0,
                                    "use_cooldown": True,
                                    "tp1_value": 1.0,
                                    "tp2_value": 2.0,
                                    "tp3_value": 3.0,
                                    "sl_value": 1.0,
                                    "use_dual_side_entry": False
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "general_error": {
                            "summary": "설정 조회 오류",
                            "value": {
                                "detail": "사용자 설정 조회 중 오류 발생: Database connection failed"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자 없음",
                            "value": {
                                "detail": "User not found"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_settings(user_id: str):
    try:
        # 사용자 존재 여부 확인
        api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
        
        if not api_keys:
            # 사용자가 없는 경우, TimescaleDB에서 정보 가져오기
            timescale_api_keys = await get_api_keys_from_timescale(user_id)
            
            if timescale_api_keys:
                # TimescaleDB에서 가져온 API 키로 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    timescale_api_keys['api_key'], 
                    timescale_api_keys['api_secret'], 
                    timescale_api_keys['passphrase']
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
            else:
                # TimescaleDB에도 사용자 정보가 없는 경우 기본값으로 생성
                default_api_key = "default_api_key"
                default_api_secret = "default_api_secret"
                default_passphrase = "default_passphrase"
                
                # 새 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    default_api_key, 
                    default_api_secret, 
                    default_passphrase
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
            
        # 설정 정보 조회
        settings = await redis_service.get_user_settings(str(user_id))
        if not settings:
            # 기본 설정 반환
            settings = DEFAULT_PARAMS_SETTINGS.copy()
            await redis_service.set_user_settings(str(user_id), settings)
        
        return SettingsResponse(
            user_id=user_id,
            settings=settings
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"사용자 설정 조회 중 오류 발생: {str(e)}"
        )


@router.put(
    "/{user_id}",
    response_model=SettingsResponse,
    summary="사용자 트레이딩 설정 업데이트",
    description="""
# 사용자 트레이딩 설정 업데이트

사용자의 트레이딩 전략 설정을 업데이트합니다. 부분 업데이트를 지원하며, 제공된 필드만 변경됩니다.

## 경로 파라미터

- **user_id** (string, required): 사용자 식별자

## 요청 본문

- **settings** (object, required): 업데이트할 설정
  - **leverage** (integer, optional): 레버리지 배율 (1-125)
  - **direction** (string, optional): 거래 방향 ("롱", "숏", "롱숏")
  - **entry_multiplier** (float, optional): 진입 배율 (0.1-10.0)
  - **tp1_value** (float, optional): 1차 익절 목표 (%)
  - **use_cooldown** (boolean, optional): 쿨다운 사용 여부

## 동작 방식

1. **사용자 확인**: API 키 존재 여부 확인
2. **기존 설정 로드**: 현재 설정 불러오기 또는 기본값 사용
3. **설정 병합**: 기존 설정 + 새 설정 병합
4. **유효성 검증**: 설정 제약 조건 확인
5. **저장**: Redis에 업데이트된 설정 저장
6. **응답 반환**: 업데이트된 전체 설정 반환

## 제약 조건

- **leverage**: 1-125
- **entry_multiplier**: 0.1-10.0
- **tp1_value, tp2_value, tp3_value**: 0.1-100.0
- **sl_value**: 0.1-100.0

## 사용 시나리오

- ⚙️ **전략 조정**: 레버리지, 익절/손절 값 변경
-  **위험 관리**: 손절 비율 업데이트
-  **성과 최적화**: 진입 배율 조정

## 예시 URL

```
PUT /settings/518796558012178692
```
""",
    responses={
        200: {
            "description": " 설정 업데이트 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "leverage_update": {
                            "summary": "레버리지 변경",
                            "value": {
                                "user_id": "518796558012178692",
                                "settings": {
                                    "leverage": 20,
                                    "direction": "롱숏",
                                    "entry_multiplier": 1.0,
                                    "use_cooldown": True,
                                    "tp1_value": 2.0
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 유효하지 않은 설정값",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_range": {
                            "summary": "값 범위 오류",
                            "value": {
                                "detail": "leverage 값은 1에서 125 사이여야 합니다."
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자를 찾을 수 없음"
        }
    }
)
async def update_settings(
    user_id: str,
    request: SettingsUpdateRequest = Body(
        ...,
        description="업데이트할 설정 데이터"
    )
):
    try:
        # 사용자 존재 여부 확인
        api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            # 사용자가 없는 경우, TimescaleDB에서 정보 가져오기
            timescale_api_keys = await get_api_keys_from_timescale(user_id)
            
            if timescale_api_keys:
                # TimescaleDB에서 가져온 API 키로 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    timescale_api_keys['api_key'], 
                    timescale_api_keys['api_secret'], 
                    timescale_api_keys['passphrase']
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
            else:
                # TimescaleDB에도 사용자 정보가 없는 경우 기본값으로 생성
                default_api_key = "default_api_key"
                default_api_secret = "default_api_secret"
                default_passphrase = "default_passphrase"
                
                # 새 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    default_api_key, 
                    default_api_secret, 
                    default_passphrase
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
        
        # 기존 설정 가져오기
        current_settings = await redis_service.get_user_settings(str(user_id))
        if not current_settings:
            current_settings = DEFAULT_PARAMS_SETTINGS.copy()
        
        # 새 설정과 기존 설정 병합
        updated_settings = {**current_settings, **request.settings}
        
        # 설정값 유효성 검사
        validated_settings = validate_settings(updated_settings)
        
        # 업데이트된 설정 저장
        await redis_service.set_user_settings(str(user_id), validated_settings)
        
        return SettingsResponse(
            user_id=user_id,
            settings=validated_settings
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"사용자 설정 업데이트 중 오류 발생: {str(e)}"
        )


@router.post(
    "/{user_id}/reset",
    response_model=SettingsResponse,
    summary="사용자 트레이딩 설정 초기화",
    description="""
# 사용자 트레이딩 설정 초기화

사용자의 트레이딩 전략 설정을 기본값으로 초기화합니다.

## 경로 파라미터

- **user_id** (string, required): 사용자 식별자

## 동작 방식

1. **사용자 확인**: API 키 존재 여부 확인
2. **기본 설정 로드**: 시스템 기본 설정 가져오기
3. **저장**: Redis에 기본 설정 저장
4. **응답 반환**: 초기화된 설정 반환

## 기본 설정 값

- **leverage**: 10
- **direction**: "롱숏"
- **entry_multiplier**: 1.0
- **use_cooldown**: True
- **tp1_value**: 1.0
- **tp2_value**: 2.0
- **tp3_value**: 3.0
- **sl_value**: 1.0
- **use_dual_side_entry**: False

## 사용 시나리오

-  **설정 복구**: 잘못된 설정 변경 후 원상복구
- 🆕 **새 시작**: 전략 재설정을 위한 초기화
-  **안전 모드**: 보수적인 기본 설정으로 전환

## 예시 URL

```
POST /settings/518796558012178692/reset
```
""",
    responses={
        200: {
            "description": " 설정 초기화 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "reset_success": {
                            "summary": "설정 초기화 완료",
                            "value": {
                                "user_id": "518796558012178692",
                                "settings": {
                                    "leverage": 10,
                                    "direction": "롱숏",
                                    "entry_multiplier": 1.0,
                                    "use_cooldown": True,
                                    "tp1_value": 1.0,
                                    "tp2_value": 2.0,
                                    "tp3_value": 3.0,
                                    "sl_value": 1.0,
                                    "use_dual_side_entry": False
                                }
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 초기화 오류"
        },
        404: {
            "description": " 사용자를 찾을 수 없음"
        }
    }
)
async def reset_settings(user_id: str):
    try:
        # 사용자 존재 여부 확인
        api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            # 사용자가 없는 경우, TimescaleDB에서 정보 가져오기
            timescale_api_keys = await get_api_keys_from_timescale(user_id)
            
            if timescale_api_keys:
                # Timescale에서 가져온 API 키로 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    timescale_api_keys['api_key'], 
                    timescale_api_keys['api_secret'], 
                    timescale_api_keys['passphrase']
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
            else:
                # TimescaleDB에도 사용자 정보가 없는 경우 기본값으로 생성
                default_api_key = "default_api_key"
                default_api_secret = "default_api_secret"
                default_passphrase = "default_passphrase"
                
                # 새 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    default_api_key, 
                    default_api_secret, 
                    default_passphrase
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
        
        # 기본 설정으로 초기화
        default_settings = DEFAULT_PARAMS_SETTINGS.copy()
        await redis_service.set_user_settings(str(user_id), default_settings)
        
        return SettingsResponse(
            user_id=user_id,
            settings=default_settings
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"사용자 설정 초기화 중 오류 발생: {str(e)}"
        )


class DualSideSettingsUpdateRequest(BaseModel):
    settings: Dict[str, Any] = Field(..., description="양방향 매매 설정 업데이트")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "settings": {
                    "use_dual_side_entry": True,
                    "dual_side_entry_trigger": 2,
                    "dual_side_entry_ratio_type": "percent_of_position",
                    "dual_side_entry_ratio_value": 30
                }
            }
        }
    }


class DualSideSettingsResponse(BaseModel):
    user_id: str
    settings: Dict[str, Any]
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": 123456789,
                "settings": {
                    "use_dual_side_entry": True,
                    "dual_side_entry_trigger": 2,
                    "dual_side_entry_ratio_type": "percent_of_position",
                    "dual_side_entry_ratio_value": 30
                }
            }
        }
    }


async def get_dual_side_settings(user_id: str) -> Dict[str, Any]:
    """양방향 매매 설정을 조회합니다."""
    # Redis에서 dual_side 해시 조회
    settings_key = f"user:{user_id}:dual_side"
    settings = await get_redis_client().hgetall(settings_key)
    
    if not settings:
        # 기본 설정
        settings = {k: str(v) if isinstance(v, bool) else str(v) for k, v in DEFAULT_DUAL_SIDE_ENTRY_SETTINGS.items()}
        await get_redis_client().hset(settings_key, mapping=settings)
    
    # 문자열 값을 적절한 타입으로 변환
    parsed_settings = {}
    for key, value in settings.items():
        if value.lower() in ('true', 'false'):
            # 불리언 값 처리
            parsed_settings[key] = value.lower() == 'true'
        else:
            try:
                # 숫자 값 처리 (정수 또는 실수)
                if '.' in value:
                    parsed_settings[key] = float(value)
                else:
                    parsed_settings[key] = int(value)
            except ValueError:
                # 숫자가 아닌 경우 원래 문자열 사용
                parsed_settings[key] = value
    
    return parsed_settings


async def save_dual_side_settings(user_id: str, settings: Dict[str, Any]) -> None:
    """양방향 매매 설정을 저장합니다."""
    settings_key = f"user:{user_id}:dual_side"
    # bool 값을 문자열로 변환
    settings_to_save = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in settings.items()}
    await get_redis_client().hset(settings_key, mapping=settings_to_save)


@router.get("/{user_id}/dual_side",
    response_model=DualSideSettingsResponse,
    summary="양방향 매매 설정 조회",
    description="사용자의 양방향 매매 설정을 조회합니다.",
    responses={
        200: {
            "description": "양방향 매매 설정 조회 성공",
            "model": DualSideSettingsResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def get_dual_settings(user_id: str):
    try:
        # 사용자 존재 여부 확인
        api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            # 사용자가 없는 경우, TimescaleDB에서 정보 가져오기
            timescale_api_keys = await get_api_keys_from_timescale(user_id)
            
            if timescale_api_keys:
                # Timescale에서 가져온 API 키로 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    timescale_api_keys['api_key'], 
                    timescale_api_keys['api_secret'], 
                    timescale_api_keys['passphrase']
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
            else:
                # TimescaleDB에도 사용자 정보가 없는 경우 기본값으로 생성
                default_api_key = "default_api_key"
                default_api_secret = "default_api_secret"
                default_passphrase = "default_passphrase"
                
                # 새 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    default_api_key, 
                    default_api_secret, 
                    default_passphrase
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
            
        # 양방향 매매 설정 조회
        settings = await get_dual_side_settings(str(user_id))
        
        return DualSideSettingsResponse(
            user_id=user_id,
            settings=settings
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"양방향 매매 설정 조회 중 오류 발생: {str(e)}"
        )


@router.put("/{user_id}/dual_side",
    response_model=DualSideSettingsResponse,
    summary="양방향 매매 설정 업데이트",
    description="사용자의 양방향 매매 설정을 업데이트합니다.",
    responses={
        200: {
            "description": "양방향 매매 설정 업데이트 성공",
            "model": DualSideSettingsResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def update_dual_settings(
    user_id: str,
    request: DualSideSettingsUpdateRequest = Body(
        ...,
        description="업데이트할 양방향 매매 설정 데이터"
    )
):
    try:
        # 사용자 존재 여부 확인
        api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            # 사용자가 없는 경우, TimescaleDB에서 정보 가져오기
            timescale_api_keys = await get_api_keys_from_timescale(user_id)
            
            if timescale_api_keys:
                # Timescale에서 가져온 API 키로 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    timescale_api_keys['api_key'], 
                    timescale_api_keys['api_secret'], 
                    timescale_api_keys['passphrase']
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
            else:
                # TimescaleDB에도 사용자 정보가 없는 경우 기본값으로 생성
                default_api_key = "default_api_key"
                default_api_secret = "default_api_secret"
                default_passphrase = "default_passphrase"
                
                # 새 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    default_api_key, 
                    default_api_secret, 
                    default_passphrase
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
        
        # 기존 설정 가져오기
        current_settings = await get_dual_side_settings(str(user_id))
        
        # 새 설정과 기존 설정 병합
        updated_settings = {**current_settings, **request.settings}
        
        # 업데이트된 설정 저장
        await save_dual_side_settings(str(user_id), updated_settings)
        
        # JSON 설정에도 use_dual_side_entry 값 동기화
        if 'use_dual_side_entry' in request.settings:
            user_settings = await redis_service.get_user_settings(str(user_id))
            if user_settings:
                user_settings['use_dual_side_entry'] = request.settings['use_dual_side_entry']
                await redis_service.set_user_settings(str(user_id), user_settings)
        
        return DualSideSettingsResponse(
            user_id=user_id,
            settings=updated_settings
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"양방향 매매 설정 업데이트 중 오류 발생: {str(e)}"
        )


@router.post("/{user_id}/dual_side/reset",
    response_model=DualSideSettingsResponse,
    summary="양방향 매매 설정 초기화",
    description="사용자의 양방향 매매 설정을 기본값으로 초기화합니다.",
    responses={
        200: {
            "description": "양방향 매매 설정 초기화 성공",
            "model": DualSideSettingsResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def reset_dual_settings(user_id: str):
    try:
        # 사용자 존재 여부 확인
        api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            # 사용자가 없는 경우, TimescaleDB에서 정보 가져오기
            timescale_api_keys = await get_api_keys_from_timescale(user_id)
            
            if timescale_api_keys:
                # Timescale에서 가져온 API 키로 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    timescale_api_keys['api_key'], 
                    timescale_api_keys['api_secret'], 
                    timescale_api_keys['passphrase']
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
            else:
                # TimescaleDB에도 사용자 정보가 없는 경우 기본값으로 생성
                default_api_key = "default_api_key"
                default_api_secret = "default_api_secret"
                default_passphrase = "default_passphrase"
                
                # 새 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    default_api_key, 
                    default_api_secret, 
                    default_passphrase
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
        
        # 기본 설정으로 초기화
        default_settings = {k: v for k, v in DEFAULT_DUAL_SIDE_ENTRY_SETTINGS.items()}
        await save_dual_side_settings(str(user_id), default_settings)
        
        return DualSideSettingsResponse(
            user_id=user_id,
            settings=default_settings
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"양방향 매매 설정 초기화 중 오류 발생: {str(e)}"
        )


# TimescaleDB 정보 관련 모델
class TimescaleUserInfo(BaseModel):
    id: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    okx_uid: Optional[str] = None
    telegram_linked: Optional[bool] = None
    telegram_id: Optional[str] = None
    telegram_userid: Optional[str] = None
    telegram_username: Optional[str] = None
    okx_api_connected: Optional[bool] = None
    okx_linked: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TimescaleAPIInfo(BaseModel):
    id: Optional[str] = None
    user_id: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    passphrase: Optional[str] = None
    telegram_id: Optional[str] = None
    telegram_linked: Optional[bool] = None
    okx_uid: Optional[str] = None
    exchange: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TimescaleResponse(BaseModel):
    user_info: Optional[TimescaleUserInfo] = None
    api_info: Optional[TimescaleAPIInfo] = None
    status: str
    message: str


class TimescaleUserUpdateRequest(BaseModel):
    telegram_id: Optional[str] = None
    telegram_username: Optional[str] = None
    name: Optional[str] = None
    telegram_linked: Optional[bool] = None


class TimescaleApiUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    passphrase: Optional[str] = None
    telegram_id: Optional[str] = None
    telegram_linked: Optional[bool] = None

@router.get("/{user_id}/timescale",
    response_model=TimescaleResponse,
    summary="사용자 정보 조회 (TimescaleDB)",
    description="TimescaleDB에서 사용자 및 API 정보를 조회합니다.",
    responses={
        200: {
            "description": "Timescale 정보 조회 성공",
            "model": TimescaleResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def get_timescale_info(user_id: str):
    try:
        record = await get_timescale_user(user_id)
        if record is None:
            return TimescaleResponse(
                status="error",
                message=f"TimescaleDB에서 사용자 정보를 찾을 수 없음: {user_id}",
            )

        return TimescaleResponse(
            user_info=TimescaleUserInfo(**record.user),
            api_info=TimescaleAPIInfo(**record.api) if record.api else None,
            status="success",
            message="Timescale 정보 조회 성공"
        )
    except Exception as exc:
        logger.error(f"Timescale 정보 조회 중 오류 발생: {exc}")
        return TimescaleResponse(
            status="error",
            message=f"Timescale 정보 조회 중 오류 발생: {exc}",
        )


@router.put("/{user_id}/timescale/user",
    response_model=TimescaleResponse,
    summary="Timescale 사용자 정보 업데이트",
    description="TimescaleDB 사용자 레코드를 업데이트합니다.",
    responses={
        200: {
            "description": "Timescale 사용자 정보 업데이트 성공",
            "model": TimescaleResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def update_timescale_user(
    user_id: str,
    request: TimescaleUserUpdateRequest = Body(
        ...,
        description="업데이트할 사용자 정보"
    )
):
    try:
        record = await get_timescale_user(user_id)
        if record is None:
            return TimescaleResponse(
                status="error",
                message=f"TimescaleDB에서 사용자 정보를 찾을 수 없음: {user_id}"
            )

        updates: Dict[str, Any] = {}

        if request.telegram_linked is False:
            updates.update({
                "telegram_id": None,
                "telegram_userid": None,
                "telegram_username": None,
                "telegram_linked": False
            })

        if request.telegram_id is not None:
            updates.update({
                "telegram_id": request.telegram_id,
                "telegram_userid": request.telegram_id,
                "telegram_linked": request.telegram_linked if request.telegram_linked is not None else bool(request.telegram_id)
            })
        elif request.telegram_linked is True and "telegram_linked" not in updates:
            updates["telegram_linked"] = True

        if request.telegram_username is not None:
            updates["telegram_username"] = request.telegram_username
        if request.name is not None:
            updates["name"] = request.name

        if updates:
            updates["updated_at"] = "now()"
            await TimescaleUserService.update_app_user(record.user["id"], updates)

        updated = await get_timescale_user(user_id)

        return TimescaleResponse(
            user_info=TimescaleUserInfo(**updated.user) if updated else None,
            api_info=TimescaleAPIInfo(**updated.api) if updated and updated.api else None,
            status="success",
            message="Timescale 사용자 정보 업데이트 성공"
        )
    except Exception as exc:
        logger.error(f"Timescale 사용자 정보 업데이트 중 오류 발생: {exc}")
        return TimescaleResponse(
            status="error",
            message=f"Timescale 사용자 정보 업데이트 중 오류 발생: {exc}",
        )


@router.put("/{user_id}/timescale/api",
    response_model=TimescaleResponse,
    summary="Timescale API 정보 업데이트",
    description="TimescaleDB okx_api_info 정보를 업데이트합니다.",
    responses={
        200: {
            "description": "Timescale API 정보 업데이트 성공",
            "model": TimescaleResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def update_timescale_api(
    user_id: str,
    request: TimescaleApiUpdateRequest = Body(
        ...,
        description="업데이트할 API 정보"
    )
):
    try:
        record = await get_timescale_user(user_id)
        if record is None:
            return TimescaleResponse(
                status="error",
                message=f"TimescaleDB에서 사용자 정보를 찾을 수 없음: {user_id}"
            )

        api_updates: Dict[str, Any] = {}

        if request.telegram_linked is False:
            api_updates.update({
                "telegram_id": None,
                "telegram_linked": False
            })

        if request.telegram_id is not None:
            api_updates.update({
                "telegram_id": request.telegram_id,
                "telegram_linked": request.telegram_linked if request.telegram_linked is not None else True
            })

        if request.api_key is not None:
            api_updates["api_key"] = request.api_key
        if request.api_secret is not None:
            api_updates["api_secret"] = request.api_secret
        if request.passphrase is not None:
            api_updates["passphrase"] = request.passphrase

        if record.api and record.api.get("id"):
            if api_updates:
                api_updates["updated_at"] = "now()"
                await TimescaleUserService.update_api_record(record.api["id"], api_updates)
        else:
            await TimescaleUserService.upsert_api_credentials(
                identifier=user_id,
                api_key=request.api_key,
                api_secret=request.api_secret,
                passphrase=request.passphrase,
            )
            if request.telegram_id is not None or request.telegram_linked is not None:
                refreshed = await get_timescale_user(user_id)
                if refreshed and refreshed.api and refreshed.api.get("id"):
                    follow_up: Dict[str, Any] = {}
                    if request.telegram_linked is False:
                        follow_up.update({
                            "telegram_id": None,
                            "telegram_linked": False
                        })
                    if request.telegram_id is not None:
                        follow_up.update({
                            "telegram_id": request.telegram_id,
                            "telegram_linked": request.telegram_linked if request.telegram_linked is not None else True
                        })
                    if follow_up:
                        follow_up["updated_at"] = "now()"
                        await TimescaleUserService.update_api_record(refreshed.api["id"], follow_up)

        updated = await get_timescale_user(user_id)

        if updated and updated.api:
            await ApiKeyService.set_user_api_keys(
                str(user_id),
                updated.api.get("api_key"),
                updated.api.get("api_secret"),
                updated.api.get("passphrase")
            )

        return TimescaleResponse(
            user_info=TimescaleUserInfo(**updated.user) if updated else None,
            api_info=TimescaleAPIInfo(**updated.api) if updated and updated.api else None,
            status="success",
            message="Timescale API 정보 업데이트 성공"
        )
    except Exception as exc:
        logger.error(f"Timescale API 정보 업데이트 중 오류 발생: {exc}")
        return TimescaleResponse(
            status="error",
            message=f"Timescale API 정보 업데이트 중 오류 발생: {exc}",
        )


@router.get("/debug-api-keys/{user_id}",
    summary="API 키 디버깅",
    description="사용자의 API 키 정보를 마스킹하여 확인하고 TimescaleDB와 Redis 상태를 비교합니다.",
    responses={
        200: {
            "description": "API 키 디버깅 성공"
        }
    })
async def debug_api_keys(user_id: str):
    try:
        logger.info(f"===== API 키 디버깅 시작: user_id={user_id} =====")

        redis_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")

        def mask_key(key: Optional[str]) -> Optional[str]:
            if not key:
                return None
            if len(key) <= 8:
                return "****"
            return key[:4] + "*" * (len(key) - 8) + key[-4:]

        redis_result = {
            "found": bool(redis_keys),
            "api_key_masked": mask_key(redis_keys.get('api_key')) if redis_keys else None,
            "api_secret_length": len(redis_keys.get('api_secret', "")) if redis_keys else 0,
            "passphrase_length": len(redis_keys.get('passphrase', "")) if redis_keys else 0
        }

        record = await get_timescale_user(user_id)
        timescale_api = record.api if record else None

        timescale_result = {
            "found": bool(timescale_api),
            "api_key_masked": mask_key(timescale_api.get('api_key')) if timescale_api else None,
            "api_secret_length": len(timescale_api.get('api_secret', "")) if timescale_api else 0,
            "passphrase_length": len(timescale_api.get('passphrase', "")) if timescale_api else 0,
            "telegram_id": timescale_api.get('telegram_id') if timescale_api else None,
            "telegram_linked": timescale_api.get('telegram_linked') if timescale_api else None
        }

        in_sync = False
        if redis_keys and timescale_api:
            in_sync = (
                redis_keys.get('api_key') == timescale_api.get('api_key') and
                redis_keys.get('api_secret') == timescale_api.get('api_secret') and
                redis_keys.get('passphrase') == timescale_api.get('passphrase')
            )

        return {
            "status": "success",
            "message": "API 키 디버깅 완료",
            "redis_keys": redis_result,
            "timescale_keys": timescale_result,
            "keys_in_sync": in_sync
        }

    except Exception as exc:
        logger.error(f"API 키 디버깅 중 오류 발생: {exc}")
        return {
            "status": "error",
            "message": f"API 키 디버깅 중 오류 발생: {exc}"
        }


@router.get("/debug-timescale/{user_id}",
    summary="Timescale 데이터 디버깅",
    description="TimescaleDB 연결 상태와 사용자 레코드를 점검합니다.",
    responses={
        200: {
            "description": "디버깅 성공"
        }
    })
async def debug_timescale(user_id: str):
    try:
        record = await get_timescale_user(user_id)
        return {
            "status": "success",
            "message": "Timescale 디버깅 완료",
            "user_found": bool(record),
            "user": record.user if record else None,
            "api": record.api if record and record.api else None
        }
    except Exception as exc:
        logger.error(f"Timescale 디버깅 중 오류 발생: {exc}")
        return {
            "status": "error",
            "message": f"Timescale 디버깅 중 오류 발생: {exc}"
        }


@router.get("/api-key-logging-guide",
    summary="API 키 로깅 가이드",
    description="TradingService에 API 키 로깅을 추가하는 방법을 안내합니다.",
    responses={
        200: {
            "description": "로깅 가이드 안내"
        }
    })
async def api_key_logging_guide():
    trading_service_code_example = """
# src/trading/trading_service.py에 다음 로깅 코드 추가:

async def initialize_exchange(self, user_id: str, symbol: str):
    # ... 기존 코드 ...
    api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
    
    # API 키 로깅 (마스킹 처리)
    api_key = api_keys.get('api_key', '')
    api_secret = api_keys.get('api_secret', '')
    passphrase = api_keys.get('passphrase', '')
    
    # 마스킹 함수
    def mask_key(key: str) -> str:
        if not key:
            return "비어있음"
        if len(key) <= 8:
            return "****" 
        return key[:4] + "*" * (len(key) - 8) + key[-4:]
    
    logger.info(f"사용자 {user_id}의 OKX API 키 정보:")
    logger.info(f"API 키: {mask_key(api_key)}, 길이: {len(api_key)}")
    logger.info(f"API 시크릿: 길이 {len(api_secret)}")
    logger.info(f"패스프레이즈: 길이 {len(passphrase)}")
    
    # CCXT 초기화 직전에 로깅
    try:
        logger.info(f"CCXT 초기화 시작: user_id={user_id}, symbol={symbol}")
        exchange = ccxt.okx({
            'apiKey': api_key,
            'secret': api_secret,
            'password': passphrase,
            'enableRateLimit': True
        })
        logger.info(f"CCXT 초기화 성공: user_id={user_id}")
        return exchange
    except Exception as e:
        logger.error(f"CCXT 초기화 오류: {str(e)}")
        raise
"""

    fetch_with_retry_code = """
# src/trading/trading_service.py에 다음 로깅 코드 추가:

async def fetch_with_retry(self, exchange, symbol, max_retries=3):
    retry_count = 0
    while retry_count < max_retries:
        try:
            logger.info(f"OKX API 요청 시도 (시도 {retry_count+1}/{max_retries}): fetch_positions, symbol={symbol}")
            positions = await exchange.fetch_positions([symbol], params={
                'instType': 'SWAP'
            })
            logger.info(f"OKX API 응답 성공: positions_count={len(positions)}")
            return positions
        except Exception as e:
            retry_count += 1
            error_msg = str(e)
            logger.error(f"OKX API 오류 (시도 {retry_count}/{max_retries}): {error_msg}")
            
            # API 키 관련 오류인 경우 즉시 중단
            if "Invalid OK-ACCESS-KEY" in error_msg or "50111" in error_msg:
                logger.critical(f"API 키 인증 오류 - 더 이상 재시도하지 않음: {error_msg}")
                raise
                
            if retry_count < max_retries:
                await asyncio.sleep(1)  # 1초 대기 후 재시도
    
    # 최대 재시도 횟수 초과
    raise Exception(f"최대 재시도 횟수({max_retries})를 초과했습니다.")
"""

    check_api_keys_code = """
# 추가 유틸리티 함수: API 키 유효성 확인

async def check_api_keys(self, user_id: str):
    # Redis에서 API 키 조회
    try:
        api_keys = await get_redis_client().hgetall(f"user:{user_id}:api:keys")
        
        if not api_keys:
            logger.error(f"사용자 {user_id}의 API 키가 존재하지 않습니다.")
            return False, "API 키가 존재하지 않습니다."
            
        api_key = api_keys.get('api_key', '')
        api_secret = api_keys.get('api_secret', '')
        passphrase = api_keys.get('passphrase', '')
        
        # 키 유효성 기본 검사
        if not api_key or not api_secret or not passphrase:
            logger.error(f"사용자 {user_id}의 API 키가 누락되었습니다: key={bool(api_key)}, secret={bool(api_secret)}, passphrase={bool(passphrase)}")
            return False, "API 키 정보가 불완전합니다."
            
        # CCXT로 간단한 요청 테스트
        try:
            exchange = ccxt.okx({
                'apiKey': api_key,
                'secret': api_secret,
                'password': passphrase,
                'enableRateLimit': True
            })
            
            # 밸런스 조회로 API 키 유효성 테스트
            await exchange.fetch_balance()
            await exchange.close()
            
            logger.info(f"사용자 {user_id}의 API 키 유효성 검사 성공")
            return True, "API 키가 유효합니다."
            
        except Exception as api_error:
            error_msg = str(api_error)
            logger.error(f"사용자 {user_id}의 API 키 유효성 검사 실패: {error_msg}")
            return False, f"API 키 오류: {error_msg}"
            
    except Exception as e:
        logger.error(f"API 키 검사 중 오류 발생: {str(e)}")
        return False, f"API 키 검사 중 오류 발생: {str(e)}"
"""

    return {
        "status": "success",
        "message": "API 키 로깅 가이드",
        "instructions": """
1. src/trading/trading_service.py 파일에 API 키 로깅 코드를 추가하세요.
2. 아래의 세 가지 코드 예제를 참고하세요:
   a. initialize_exchange 함수에 API 키 로깅 추가
   b. fetch_with_retry 함수에 상세 로깅 추가
   c. 새로운 유틸리티 함수 check_api_keys 추가

이 로깅을 추가하면 어떤 API 키가 사용되고 있는지, 그리고 어떤 오류가 발생하는지 정확히 확인할 수 있습니다.
API 키가 마스킹 처리되어 로그에 기록되므로 보안상 안전합니다.
        """,
        "code_examples": {
            "initialize_exchange": trading_service_code_example,
            "fetch_with_retry": fetch_with_retry_code,
            "check_api_keys": check_api_keys_code
        }
    } 
