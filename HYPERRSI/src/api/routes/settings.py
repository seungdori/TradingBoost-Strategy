from fastapi import APIRouter, Body, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
from HYPERRSI.src.core.database import redis_client
from shared.constants.default_settings import DEFAULT_PARAMS_SETTINGS, SETTINGS_CONSTRAINTS, DEFAULT_DUAL_SIDE_ENTRY_SETTINGS
from HYPERRSI.src.services.redis_service import RedisService, ApiKeyService
import json
import httpx
import logging
import os
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

# Supabase 연결 정보
SUPABASE_URL = "https://fsobvtcxqndccnekasqw.supabase.co"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZzb2J2dGN4cW5kY2NuZWthc3F3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTczMDY0MTIyNywiZXhwIjoyMDQ2MjE3MjI3fQ.Pni49lbWfdQBt7azJE_I_-1rM5jjp7Ri1L44I3F_hNQ"

router = APIRouter(prefix="/settings", tags=["User Settings"])
redis_service = RedisService()
logger = logging.getLogger(__name__)


# Supabase API 호출 함수
async def supabase_api_call(endpoint, method="GET", data=None, auth_key=SUPABASE_SERVICE_KEY):
    """Supabase API 호출 함수"""
    headers = {
        "apikey": auth_key,
        "Authorization": f"Bearer {auth_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    
    # 요청 URL과 헤더 로깅
    logger.info(f"Supabase API 요청: {method} {url}")
    logger.info(f"요청 헤더: {headers}")
    if data:
        logger.info(f"요청 데이터: {data}")
    
    async with httpx.AsyncClient() as client:
        try:
            if method == "GET":
                response = await client.get(url, headers=headers)
            elif method == "POST":
                response = await client.post(url, json=data, headers=headers)
            elif method == "PUT":
                response = await client.put(url, json=data, headers=headers)
            elif method == "PATCH":
                response = await client.patch(url, json=data, headers=headers)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers)
            
            # 응답 상태와 내용 로깅
            logger.info(f"응답 상태: {response.status_code}")
            logger.info(f"응답 헤더: {dict(response.headers)}")
            logger.info(f"응답 내용: {response.text[:300]}{'...' if len(response.text) > 300 else ''}")
            
            return response
        except Exception as e:
            logger.error(f"Supabase API 요청 중 오류: {str(e)}")
            raise


# Supabase에서 API 키 정보 가져오는 함수
async def get_api_keys_from_supabase(user_id: str):
    try:
        logger.info(f"===== get_api_keys_from_supabase 시작: user_id={user_id} =====")
        
        # 1. 먼저 okx_uid로 검색 (문자열로 변환)
        okx_uid_str = str(user_id)
        response = await supabase_api_call(f"users?okx_uid=eq.{okx_uid_str}", method="GET")
        
        # 디버깅 로그 추가
        logger.info(f"okx_uid(문자열) 검색 결과: {okx_uid_str}, 상태코드: {response.status_code}, 데이터: {response.text[:100]}")
        
        # 2. telegram_id로 검색
        if response.status_code != 200 or not response.json():
            logger.info(f"{okx_uid_str}를 okx_uid로 찾지 못했습니다. telegram_id로 검색합니다.")
            response = await supabase_api_call(f"users?telegram_id=eq.{okx_uid_str}", method="GET")
            logger.info(f"telegram_id(문자열) 검색 결과: {okx_uid_str}, 상태코드: {response.status_code}, 데이터: {response.text[:100]}")
            
            # 3. 추가 검색 방법: 사용자 ID가 허용된 UID 목록에 있는지 확인
            if response.status_code != 200 or not response.json():
                logger.info(f"{okx_uid_str}를 telegram_id로도 찾지 못했습니다. 테이블 전체 검색을 시도합니다.")
                # 매우 특수한 경우 - 전체 사용자를 가져와서 확인 (사용자 수가 많지 않을 때만 유효)
                full_response = await supabase_api_call("users?select=*", method="GET")
                logger.info(f"전체 사용자 검색 결과: 상태코드: {full_response.status_code}, 데이터 길이: {len(full_response.text) if full_response.text else 0}")
                
                if full_response.status_code == 200 and full_response.json():
                    # 모든 사용자에서 해당 ID 관련 사용자 찾기
                    users = full_response.json()
                    found_user = None
                    
                    for user in users:
                        user_okx_uid = str(user.get('okx_uid', ''))
                        user_telegram_id = str(user.get('telegram_id', ''))
                        
                        if user_okx_uid == okx_uid_str or user_telegram_id == okx_uid_str:
                            found_user = user
                            logger.info(f"전체 검색에서 사용자 찾음: {found_user}")
                            break
                    
                    if found_user:
                        # 사용자를 찾았으면 해당 사용자 정보로 response 대체
                        response = type('DummyResponse', (), {
                            'status_code': 200,
                            'json': lambda: [found_user]
                        })
        
        # 4. 모든 검색이 실패한 경우
        if response.status_code != 200 or not response.json():
            logger.error(f"Supabase에서 사용자 정보를 찾을 수 없음 (모든 방법 시도): {user_id}")
            
            # 테이블 구조 확인을 위해 몇 개의 레코드 샘플링
            sample_response = await supabase_api_call("users?limit=3", method="GET")
            if sample_response.status_code == 200 and sample_response.json():
                logger.info(f"Users 테이블 샘플: {sample_response.text}")
            else:
                logger.warning("Users 테이블 샘플 조회 실패")
                
            return None
            
        supabase_user = response.json()[0]
        supabase_user_id = supabase_user.get('id')
        
        if not supabase_user_id:
            logger.error(f"사용자 ID를 찾을 수 없음: {user_id}")
            return None
        
        # 검색된 사용자 정보 로깅    
        logger.info(f"Supabase 사용자 찾음: {supabase_user_id}, okx_uid: {supabase_user.get('okx_uid')}, telegram_id: {supabase_user.get('telegram_id')}")
            
        # 5. okx_api_info 테이블에서 API 키 정보 조회
        api_response = await supabase_api_call(f"okx_api_info?user_id=eq.{supabase_user_id}&deleted_at=is.null", method="GET")
        
        if api_response.status_code != 200 or not api_response.json():
            logger.error(f"Supabase에서 API 키 정보를 찾을 수 없음: {supabase_user_id}")
            
            # API 키 테이블 구조 확인
            sample_api_response = await supabase_api_call("okx_api_info?limit=3", method="GET")
            if sample_api_response.status_code == 200 and sample_api_response.json():
                logger.info(f"okx_api_info 테이블 샘플: {sample_api_response.text}")
            else:
                logger.warning("okx_api_info 테이블 샘플 조회 실패")
                
            return None
            
        api_info = api_response.json()[0]
        logger.info(f"API 키 정보 찾음: user_id={supabase_user_id}, api_id={api_info.get('id')}")
        
        # 6. API 키 정보 반환
        result = {
            'api_key': api_info.get('api_key'),
            'api_secret': api_info.get('api_secret'),
            'passphrase': api_info.get('passphrase')
        }
        
        logger.info(f"===== get_api_keys_from_supabase 완료: user_id={user_id} =====")
        return result
        
    except Exception as e:
        logger.error(f"Supabase API 호출 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
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


@router.get("/{user_id}",
    response_model=SettingsResponse,
    summary="사용자 설정 조회",
    description="등록된 사용자의 설정을 조회합니다.",
    responses={
        200: {
            "description": "사용자 설정 조회 성공",
            "model": SettingsResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def get_settings(user_id: str):
    try:
        # 사용자 존재 여부 확인
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        
        if not api_keys:
            # 사용자가 없는 경우, Supabase에서 정보 가져오기
            supabase_api_keys = await get_api_keys_from_supabase(user_id)
            
            if supabase_api_keys:
                # Supabase에서 가져온 API 키로 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    supabase_api_keys['api_key'], 
                    supabase_api_keys['api_secret'], 
                    supabase_api_keys['passphrase']
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
            else:
                # Supabase에도 사용자 정보가 없는 경우 기본값으로 생성
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
                api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
            
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


@router.put("/{user_id}",
    response_model=SettingsResponse,
    summary="사용자 설정 업데이트",
    description="사용자 설정을 업데이트합니다.",
    responses={
        200: {
            "description": "사용자 설정 업데이트 성공",
            "model": SettingsResponse
        },
        400: {"description": "유효하지 않은 설정값"},
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def update_settings(
    user_id: str,
    request: SettingsUpdateRequest = Body(
        ...,
        description="업데이트할 설정 데이터"
    )
):
    try:
        # 사용자 존재 여부 확인
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            # 사용자가 없는 경우, Supabase에서 정보 가져오기
            supabase_api_keys = await get_api_keys_from_supabase(user_id)
            
            if supabase_api_keys:
                # Supabase에서 가져온 API 키로 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    supabase_api_keys['api_key'], 
                    supabase_api_keys['api_secret'], 
                    supabase_api_keys['passphrase']
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
            else:
                # Supabase에도 사용자 정보가 없는 경우 기본값으로 생성
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
                api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        
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


@router.post("/{user_id}/reset",
    response_model=SettingsResponse,
    summary="사용자 설정 초기화",
    description="사용자 설정을 기본값으로 초기화합니다.",
    responses={
        200: {
            "description": "사용자 설정 초기화 성공",
            "model": SettingsResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def reset_settings(user_id: str):
    try:
        # 사용자 존재 여부 확인
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            # 사용자가 없는 경우, Supabase에서 정보 가져오기
            supabase_api_keys = await get_api_keys_from_supabase(user_id)
            
            if supabase_api_keys:
                # Supabase에서 가져온 API 키로 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    supabase_api_keys['api_key'], 
                    supabase_api_keys['api_secret'], 
                    supabase_api_keys['passphrase']
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
            else:
                # Supabase에도 사용자 정보가 없는 경우 기본값으로 생성
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
                api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        
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
    settings = await redis_client.hgetall(settings_key)
    
    if not settings:
        # 기본 설정
        settings = {k: str(v) if isinstance(v, bool) else str(v) for k, v in DEFAULT_DUAL_SIDE_ENTRY_SETTINGS.items()}
        await redis_client.hset(settings_key, mapping=settings)
    
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
    await redis_client.hset(settings_key, mapping=settings_to_save)


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
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            # 사용자가 없는 경우, Supabase에서 정보 가져오기
            supabase_api_keys = await get_api_keys_from_supabase(user_id)
            
            if supabase_api_keys:
                # Supabase에서 가져온 API 키로 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    supabase_api_keys['api_key'], 
                    supabase_api_keys['api_secret'], 
                    supabase_api_keys['passphrase']
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
            else:
                # Supabase에도 사용자 정보가 없는 경우 기본값으로 생성
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
                api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
            
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
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            # 사용자가 없는 경우, Supabase에서 정보 가져오기
            supabase_api_keys = await get_api_keys_from_supabase(user_id)
            
            if supabase_api_keys:
                # Supabase에서 가져온 API 키로 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    supabase_api_keys['api_key'], 
                    supabase_api_keys['api_secret'], 
                    supabase_api_keys['passphrase']
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
            else:
                # Supabase에도 사용자 정보가 없는 경우 기본값으로 생성
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
                api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        
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
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            # 사용자가 없는 경우, Supabase에서 정보 가져오기
            supabase_api_keys = await get_api_keys_from_supabase(user_id)
            
            if supabase_api_keys:
                # Supabase에서 가져온 API 키로 사용자 생성
                await ApiKeyService.set_user_api_keys(
                    str(user_id), 
                    supabase_api_keys['api_key'], 
                    supabase_api_keys['api_secret'], 
                    supabase_api_keys['passphrase']
                )
                
                # 생성 후 API 키 다시 조회
                api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
            else:
                # Supabase에도 사용자 정보가 없는 경우 기본값으로 생성
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
                api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        
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


# Supabase 정보 관련 모델
class SupabaseUserInfo(BaseModel):
    id: Optional[str] = None
    telegram_id: Optional[str] = None
    okx_uid: str
    name: Optional[str] = None
    telegram_linked: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class SupabaseAPIInfo(BaseModel):
    id: Optional[str] = None
    user_id: str
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    passphrase: Optional[str] = None
    exchange: Optional[str] = "okx"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None

class SupabaseResponse(BaseModel):
    user_info: Optional[SupabaseUserInfo] = None
    api_info: Optional[SupabaseAPIInfo] = None
    status: str
    message: str

# Supabase 사용자 정보 업데이트 모델
class SupabaseUserUpdateRequest(BaseModel):
    telegram_id: Optional[str] = None
    name: Optional[str] = None
    telegram_linked: Optional[bool] = None

# Supabase API 정보 업데이트 모델
class SupabaseApiUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    passphrase: Optional[str] = None

@router.get("/{user_id}/supabase",
    response_model=SupabaseResponse,
    summary="Supabase에서 사용자 정보 조회",
    description="Supabase에서 사용자 및 API 정보를 조회합니다.",
    responses={
        200: {
            "description": "Supabase 정보 조회 성공",
            "model": SupabaseResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def get_supabase_info(user_id: str):
    try:
        logger.info(f"===== get_supabase_info 시작: user_id={user_id} =====")
        
        # 1. 먼저 okx_uid로 검색 (문자열로 변환)
        okx_uid_str = str(user_id)
        response = await supabase_api_call(f"users?okx_uid=eq.{okx_uid_str}", method="GET")
        logger.info(f"okx_uid(문자열) 검색 결과: {okx_uid_str}, 상태코드: {response.status_code}, 데이터 길이: {len(response.text)}")
        
        # 2. telegram_id로 검색
        if response.status_code != 200 or not response.json():
            logger.info(f"{okx_uid_str}를 okx_uid로 찾지 못했습니다. telegram_id로 검색합니다.")
            response = await supabase_api_call(f"users?telegram_id=eq.{okx_uid_str}", method="GET")
            logger.info(f"telegram_id(문자열) 검색 결과: {okx_uid_str}, 상태코드: {response.status_code}, 데이터 길이: {len(response.text)}")
            
            # 3. 추가 검색 방법: 전체 사용자 테이블에서 검색
            if response.status_code != 200 or not response.json():
                logger.info(f"{okx_uid_str}를 telegram_id로도 찾지 못했습니다. 테이블 전체 검색을 시도합니다.")
                # 매우 특수한 경우 - 전체 사용자를 가져와서 확인 (사용자 수가 많지 않을 때만 유효)
                full_response = await supabase_api_call("users?select=*", method="GET")
                logger.info(f"전체 사용자 검색 결과: 상태코드: {full_response.status_code}, 데이터 길이: {len(full_response.text) if full_response.text else 0}")
                
                if full_response.status_code == 200 and full_response.json():
                    # 모든 사용자에서 해당 ID 관련 사용자 찾기
                    users = full_response.json()
                    found_user = None
                    
                    for user in users:
                        user_okx_uid = str(user.get('okx_uid', ''))
                        user_telegram_id = str(user.get('telegram_id', ''))
                        
                        logger.info(f"사용자 확인: okx_uid={user_okx_uid}, telegram_id={user_telegram_id}, 검색 ID={okx_uid_str}")
                        
                        if user_okx_uid == okx_uid_str or user_telegram_id == okx_uid_str:
                            found_user = user
                            logger.info(f"전체 검색에서 사용자 찾음: {found_user}")
                            break
                    
                    if found_user:
                        # 사용자를 찾았으면 해당 사용자 정보로 response 대체
                        response = type('DummyResponse', (), {
                            'status_code': 200,
                            'json': lambda: [found_user]
                        })
                    else:
                        logger.info(f"전체 검색에서도 {okx_uid_str}를 찾지 못했습니다.")
                        # 찾은 사용자들의 정보를 로깅
                        logger.info(f"찾은 모든 사용자: {[(u.get('id'), u.get('okx_uid'), u.get('telegram_id')) for u in users]}")
        
        if response.status_code != 200 or not response.json():
            logger.error(f"Supabase에서 사용자 정보를 찾을 수 없음 (모든 방법 시도): {user_id}")
            
            # 테이블 구조 확인을 위해 몇 개의 레코드 샘플링
            sample_response = await supabase_api_call("users?limit=3", method="GET")
            if sample_response.status_code == 200 and sample_response.json():
                logger.info(f"Users 테이블 샘플: {sample_response.text}")
            
            return SupabaseResponse(
                status="error",
                message=f"Supabase에서 사용자 정보를 찾을 수 없음 (okx_uid/telegram_id): {user_id}"
            )
            
        user_info = response.json()[0]
        user_id_in_supabase = user_info.get('id')
        
        logger.info(f"사용자 정보 찾음: supabase_id={user_id_in_supabase}, okx_uid={user_info.get('okx_uid')}, telegram_id={user_info.get('telegram_id')}")
        
        # API 정보 조회
        api_response = await supabase_api_call(f"okx_api_info?user_id=eq.{user_id_in_supabase}&deleted_at=is.null", method="GET")
        
        api_info = None
        if api_response.status_code == 200 and api_response.json():
            api_info = api_response.json()[0]
            logger.info(f"API 정보 찾음: api_id={api_info.get('id')}")
        else:
            logger.warning(f"API 정보 없음: user_id={user_id_in_supabase}, 응답 코드={api_response.status_code}")
        
        # 로그 기록
        logger.info(f"Supabase 사용자 정보 조회 완료: {user_id}, 결과: {user_info.get('id')}")
        logger.info(f"===== get_supabase_info 완료: user_id={user_id} =====")
        
        # 응답 생성 중 발생하는 타입 변환 오류를 방지하기 위해 try-except 블록 사용
        try:
            return SupabaseResponse(
                user_info=SupabaseUserInfo(**user_info),
                api_info=SupabaseAPIInfo(**api_info) if api_info else None,
                status="success",
                message="Supabase 정보 조회 성공"
            )
        except Exception as validation_error:
            logger.error(f"응답 생성 중 유효성 검사 오류: {str(validation_error)}")
            
            # 문제가 되는 필드 값 로깅
            logger.info(f"User Info: {user_info}")
            if api_info:
                logger.info(f"API Info: {api_info}")
                
            # 수동으로 필드 타입 변환하여 응답 생성
            clean_user_info = {k: str(v) if k in ['id', 'okx_uid', 'telegram_id'] else v for k, v in user_info.items()}
            clean_api_info = {k: str(v) if k in ['id', 'user_id'] else v for k, v in api_info.items()} if api_info else None
            
            return SupabaseResponse(
                user_info=SupabaseUserInfo(**clean_user_info),
                api_info=SupabaseAPIInfo(**clean_api_info) if clean_api_info else None,
                status="success",
                message="Supabase 정보 조회 성공 (필드 타입 변환 적용됨)"
            )
        
    except Exception as e:
        logger.error(f"Supabase 정보 조회 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return SupabaseResponse(
            status="error",
            message=f"Supabase 정보 조회 중 오류 발생: {str(e)}"
        )


@router.put("/{user_id}/supabase/user",
    response_model=SupabaseResponse,
    summary="Supabase 사용자 정보 업데이트",
    description="Supabase에서 사용자 정보를 업데이트합니다.",
    responses={
        200: {
            "description": "Supabase 사용자 정보 업데이트 성공",
            "model": SupabaseResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def update_supabase_user(
    user_id: str,
    request: SupabaseUserUpdateRequest = Body(
        ...,
        description="업데이트할 Supabase 사용자 정보"
    )
):
    try:
        # 먼저 사용자 정보 조회
        response = await supabase_api_call(f"users?okx_uid=eq.{user_id}", method="GET")
        
        if response.status_code != 200 or not response.json():
            return SupabaseResponse(
                status="error",
                message=f"Supabase에서 사용자 정보를 찾을 수 없음: {user_id}"
            )
            
        # 업데이트 데이터 준비
        update_data = {
            "updated_at": "now()"
        }
        
        # 요청에 있는 필드만 업데이트
        if request.telegram_id is not None:
            update_data["telegram_id"] = request.telegram_id
        
        if request.name is not None:
            update_data["name"] = request.name
            
        if request.telegram_linked is not None:
            update_data["telegram_linked"] = request.telegram_linked
        
        # Supabase 업데이트
        update_response = await supabase_api_call(f"users?okx_uid=eq.{user_id}", method="PATCH", data=update_data)
        
        if update_response.status_code not in [200, 201, 204]:
            return SupabaseResponse(
                status="error",
                message=f"사용자 정보 업데이트 실패: {update_response.status_code}"
            )
        
        # 업데이트 후 조회
        updated_response = await supabase_api_call(f"users?okx_uid=eq.{user_id}", method="GET")
        updated_user = updated_response.json()[0] if updated_response.json() else None
        
        # 로그 기록
        logger.info(f"Supabase 사용자 정보 업데이트: {user_id}, 필드: {list(update_data.keys())}")
        
        return SupabaseResponse(
            user_info=SupabaseUserInfo(**updated_user) if updated_user else None,
            status="success",
            message="Supabase 사용자 정보 업데이트 성공"
        )
        
    except Exception as e:
        logger.error(f"Supabase 사용자 정보 업데이트 중 오류 발생: {str(e)}")
        return SupabaseResponse(
            status="error",
            message=f"Supabase 사용자 정보 업데이트 중 오류 발생: {str(e)}"
        )


@router.put("/{user_id}/supabase/api",
    response_model=SupabaseResponse,
    summary="Supabase API 정보 업데이트",
    description="Supabase에서 API 정보를 업데이트합니다.",
    responses={
        200: {
            "description": "Supabase API 정보 업데이트 성공",
            "model": SupabaseResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def update_supabase_api(
    user_id: str,
    request: SupabaseApiUpdateRequest = Body(
        ...,
        description="업데이트할 Supabase API 정보"
    )
):
    try:
        # 먼저 사용자 정보 조회
        response = await supabase_api_call(f"users?okx_uid=eq.{user_id}", method="GET")
        
        if response.status_code != 200 or not response.json():
            return SupabaseResponse(
                status="error",
                message=f"Supabase에서 사용자 정보를 찾을 수 없음: {user_id}"
            )
            
        user_info = response.json()[0]
        user_id_in_supabase = user_info.get('id')
        
        # API 정보 조회
        api_response = await supabase_api_call(f"okx_api_info?user_id=eq.{user_id_in_supabase}&deleted_at=is.null", method="GET")
        
        # 업데이트 데이터 준비
        update_data = {
            "updated_at": "now()"
        }
        
        # 요청에 있는 필드만 업데이트
        if request.api_key is not None:
            update_data["api_key"] = request.api_key
        
        if request.api_secret is not None:
            update_data["api_secret"] = request.api_secret
            
        if request.passphrase is not None:
            update_data["passphrase"] = request.passphrase
        
        if api_response.status_code == 200 and api_response.json():
            # API 정보가 있으면 업데이트
            api_info = api_response.json()[0]
            api_id = api_info.get('id')
            
            # 기존 API 정보가 기본값인지 확인
            current_api_key = api_info.get('api_key', '')
            current_api_secret = api_info.get('api_secret', '')
            current_passphrase = api_info.get('passphrase', '')
            
            # 기본값이 있는 경우에도 업데이트 데이터에 추가
            if 'api_key' not in update_data and (not current_api_key or current_api_key == "default_api_key") and request.api_key is not None:
                update_data["api_key"] = request.api_key
                
            if 'api_secret' not in update_data and (not current_api_secret or current_api_secret == "default_api_secret") and request.api_secret is not None:
                update_data["api_secret"] = request.api_secret
                
            if 'passphrase' not in update_data and (not current_passphrase or current_passphrase == "default_passphrase") and request.passphrase is not None:
                update_data["passphrase"] = request.passphrase
            
            update_response = await supabase_api_call(f"okx_api_info?id=eq.{api_id}", method="PATCH", data=update_data)
            
            if update_response.status_code not in [200, 201, 204]:
                return SupabaseResponse(
                    status="error",
                    message=f"API 정보 업데이트 실패: {update_response.status_code}"
                )
        else:
            # API 정보가 없으면 새로 생성
            new_api_data = {
                "user_id": user_id_in_supabase,
                "exchange": "okx",
                "created_at": "now()",
                "updated_at": "now()"
            }
            
            # 요청에 있는 필드 추가
            if request.api_key is not None:
                new_api_data["api_key"] = request.api_key
            else:
                new_api_data["api_key"] = "default_api_key"
                
            if request.api_secret is not None:
                new_api_data["api_secret"] = request.api_secret
            else:
                new_api_data["api_secret"] = "default_api_secret"
                
            if request.passphrase is not None:
                new_api_data["passphrase"] = request.passphrase
            else:
                new_api_data["passphrase"] = "default_passphrase"
            
            create_response = await supabase_api_call("okx_api_info", method="POST", data=new_api_data)
            
            if create_response.status_code not in [200, 201, 204]:
                return SupabaseResponse(
                    status="error",
                    message=f"API 정보 생성 실패: {create_response.status_code}"
                )
        
        # 업데이트 후 조회
        updated_api_response = await supabase_api_call(f"okx_api_info?user_id=eq.{user_id_in_supabase}&deleted_at=is.null", method="GET")
        updated_api = updated_api_response.json()[0] if updated_api_response.json() else None
        
        # Redis에도 API 키 정보 업데이트
        if updated_api:
            await ApiKeyService.set_user_api_keys(
                str(user_id),
                updated_api.get('api_key'),
                updated_api.get('api_secret'),
                updated_api.get('passphrase')
            )
        
        # 로그 기록
        logger.info(f"Supabase API 정보 업데이트: {user_id}, 사용자 ID: {user_id_in_supabase}")
        
        return SupabaseResponse(
            user_info=SupabaseUserInfo(**user_info),
            api_info=SupabaseAPIInfo(**updated_api) if updated_api else None,
            status="success",
            message="Supabase API 정보 업데이트 성공"
        )
        
    except Exception as e:
        logger.error(f"Supabase API 정보 업데이트 중 오류 발생: {str(e)}")
        return SupabaseResponse(
            status="error",
            message=f"Supabase API 정보 업데이트 중 오류 발생: {str(e)}"
        )


@router.get("/logs",
    summary="로그 확인",
    description="최근 로그를 확인합니다.",
    responses={
        200: {
            "description": "로그 조회 성공"
        }
    })
async def get_logs(limit: int = 50):
    try:
        # 로그 파일 경로
        log_file = os.getenv("LOG_FILE", "app.log")
        
        if not os.path.exists(log_file):
            return {
                "status": "error",
                "message": "로그 파일이 존재하지 않습니다.",
                "logs": []
            }
        
        # 로그 파일에서 마지막 N줄 읽기
        logs = []
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            logs = lines[-limit:] if len(lines) > limit else lines
        
        return {
            "status": "success",
            "message": f"최근 {len(logs)} 로그 조회 성공",
            "logs": logs
        }
        
    except Exception as e:
        logger.error(f"로그 조회 중 오류 발생: {str(e)}")
        return {
            "status": "error",
            "message": f"로그 조회 중 오류 발생: {str(e)}",
            "logs": []
        }


@router.get("/debug-api-keys/{user_id}",
    summary="API 키 디버깅",
    description="사용자의 API 키 정보를 마스킹하여 디버깅합니다.",
    responses={
        200: {
            "description": "API 키 디버깅 성공"
        }
    })
async def debug_api_keys(user_id: str):
    try:
        logger.info(f"===== API 키 디버깅 시작: user_id={user_id} =====")
        
        # 1. Redis에서 API 키 조회
        redis_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        
        # API 키 마스킹 함수
        def mask_key(key: str) -> str:
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
        
        # 2. Supabase에서 조회
        # 먼저 사용자 ID 조회
        okx_uid_str = str(user_id)
        user_search_methods = [
            f"users?okx_uid=eq.{okx_uid_str}",
            f"users?telegram_id=eq.{okx_uid_str}"
        ]
        
        supabase_user = None
        for search_method in user_search_methods:
            response = await supabase_api_call(search_method, method="GET")
            if response.status_code == 200 and response.json():
                supabase_user = response.json()[0]
                logger.info(f"Supabase 사용자 찾음: {search_method}")
                break
                
        supabase_api_keys = None
        if supabase_user:
            supabase_user_id = supabase_user.get('id')
            api_response = await supabase_api_call(f"okx_api_info?user_id=eq.{supabase_user_id}&deleted_at=is.null", method="GET")
            if api_response.status_code == 200 and api_response.json():
                supabase_api_keys = api_response.json()[0]
        
        supabase_result = {
            "user_found": bool(supabase_user),
            "user_id": supabase_user.get('id') if supabase_user else None,
            "okx_uid": supabase_user.get('okx_uid') if supabase_user else None,
            "telegram_id": supabase_user.get('telegram_id') if supabase_user else None,
            "api_keys_found": bool(supabase_api_keys),
            "api_key_masked": mask_key(supabase_api_keys.get('api_key')) if supabase_api_keys else None,
            "api_secret_length": len(supabase_api_keys.get('api_secret', "")) if supabase_api_keys else 0,
            "passphrase_length": len(supabase_api_keys.get('passphrase', "")) if supabase_api_keys else 0
        }
        
        # 3. Redis와 Supabase 키 비교
        keys_match = False
        if redis_keys and supabase_api_keys:
            redis_api_key = redis_keys.get('api_key', '')
            supabase_api_key = supabase_api_keys.get('api_key', '')
            redis_api_secret = redis_keys.get('api_secret', '')
            supabase_api_secret = supabase_api_keys.get('api_secret', '')
            redis_passphrase = redis_keys.get('passphrase', '')
            supabase_passphrase = supabase_api_keys.get('passphrase', '')
            
            keys_match = (
                redis_api_key == supabase_api_key and
                redis_api_secret == supabase_api_secret and
                redis_passphrase == supabase_passphrase
            )
            
        # 4. OKX API 키 유효성 테스트
        import ccxt.async_support as ccxt
        import asyncio
        
        okx_test_result = {"tested": False}
        
        if redis_keys:
            try:
                logger.info("Redis API 키로 OKX 연결 테스트 시작")
                exchange = ccxt.okx({
                    'apiKey': redis_keys.get('api_key'),
                    'secret': redis_keys.get('api_secret'),
                    'password': redis_keys.get('passphrase'),
                    'enableRateLimit': True
                })
                
                # 간단한 API 요청 (밸런스 조회)
                try:
                    balance = await exchange.fetch_balance()
                    okx_test_result = {
                        "tested": True,
                        "status": "success",
                        "message": "OKX API 키 유효함",
                        "source": "Redis"
                    }
                    logger.info(f"OKX API 키 테스트 성공 (Redis)")
                except Exception as api_error:
                    error_msg = str(api_error)
                    okx_test_result = {
                        "tested": True,
                        "status": "error",
                        "message": f"OKX API 오류: {error_msg}",
                        "source": "Redis",
                        "error_code": error_msg.split("code\":\"")[1].split("\"")[0] if "code\":\"" in error_msg else "알 수 없음"
                    }
                    logger.error(f"OKX API 키 테스트 실패 (Redis): {error_msg}")
                
                await exchange.close()
                
            except Exception as e:
                logger.error(f"OKX 연결 테스트 도중 오류: {str(e)}")
                okx_test_result = {
                    "tested": True,
                    "status": "error",
                    "message": f"OKX 연결 테스트 도중 오류: {str(e)}",
                    "source": "Redis"
                }
        
        logger.info(f"===== API 키 디버깅 완료: user_id={user_id} =====")
        
        # 5. 결과 반환
        return {
            "status": "success",
            "message": "API 키 디버깅 완료",
            "user_id": user_id,
            "redis_keys": redis_result,
            "supabase_keys": supabase_result,
            "keys_match": keys_match,
            "okx_test": okx_test_result
        }
        
    except Exception as e:
        logger.error(f"API 키 디버깅 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"API 키 디버깅 중 오류 발생: {str(e)}",
            "traceback": traceback.format_exc()
        }


@router.get("/debug-supabase/{user_id}",
    summary="Supabase 데이터 디버깅",
    description="Supabase 연결 및 데이터 구조를 디버깅합니다.",
    responses={
        200: {
            "description": "디버깅 성공"
        }
    })
async def debug_supabase(user_id: str):
    try:
        logger.info(f"===== Supabase 디버깅 시작: user_id={user_id} =====")
        
        # 1. Supabase 연결 테스트
        test_response = await supabase_api_call("users?limit=1", method="GET")
        connection_ok = test_response.status_code == 200
        
        # 2. Users 테이블 구조 확인
        users_sample = None
        if connection_ok:
            sample_response = await supabase_api_call("users?limit=3", method="GET")
            if sample_response.status_code == 200 and sample_response.json():
                users_sample = sample_response.json()
        
        # 3. API 정보 테이블 구조 확인
        api_sample = None
        if connection_ok:
            api_sample_response = await supabase_api_call("okx_api_info?limit=3", method="GET")
            if api_sample_response.status_code == 200 and api_sample_response.json():
                api_sample = api_sample_response.json()
        
        # 4. 특정 사용자 검색 (여러 방법)
        user_str = str(user_id)
        okx_uid_search = await supabase_api_call(f"users?okx_uid=eq.{user_id}", method="GET")
        okx_uid_str_search = await supabase_api_call(f"users?okx_uid=eq.{user_str}", method="GET")
        telegram_id_search = await supabase_api_call(f"users?telegram_id=eq.{user_str}", method="GET")
        
        # 5. 결과 반환
        result = {
            "status": "success" if connection_ok else "error",
            "connection": "정상" if connection_ok else "실패",
            "users_table_sample": users_sample,
            "api_table_sample": api_sample,
            "user_search_results": {
                "okx_uid_numeric": {
                    "status_code": okx_uid_search.status_code,
                    "found": bool(okx_uid_search.json()) if okx_uid_search.status_code == 200 else False,
                    "count": len(okx_uid_search.json()) if okx_uid_search.status_code == 200 else 0
                },
                "okx_uid_string": {
                    "status_code": okx_uid_str_search.status_code,
                    "found": bool(okx_uid_str_search.json()) if okx_uid_str_search.status_code == 200 else False,
                    "count": len(okx_uid_str_search.json()) if okx_uid_str_search.status_code == 200 else 0
                },
                "telegram_id": {
                    "status_code": telegram_id_search.status_code,
                    "found": bool(telegram_id_search.json()) if telegram_id_search.status_code == 200 else False,
                    "count": len(telegram_id_search.json()) if telegram_id_search.status_code == 200 else 0
                }
            }
        }
        
        logger.info(f"===== Supabase 디버깅 완료: user_id={user_id} =====")
        return result
        
    except Exception as e:
        logger.error(f"Supabase 디버깅 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "message": f"Supabase 디버깅 중 오류 발생: {str(e)}",
            "traceback": traceback.format_exc()
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
    api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
    
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
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        
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