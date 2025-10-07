from fastapi import APIRouter, Body, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional
from HYPERRSI.src.core.database import get_db
from shared.constants.default_settings import DEFAULT_TRADING_SETTINGS
from sqlalchemy.orm import Session

from HYPERRSI.src.utils.uid_manager import get_or_create_okx_uid, get_okx_uid_by_telegram_id, update_user_okx_uid
from HYPERRSI.src.utils.check_invitee import get_uid_from_api_keys, store_okx_uid, get_okx_uid_from_telegram
import time

# Dynamic redis_client access
def _get_redis_client():
    """Get redis_client dynamically to avoid import-time errors"""
    from HYPERRSI.src.core import database as db_module
    return db_module.redis_client

redis_client = _get_redis_client()

# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return _get_redis_client()
    raise AttributeError(f"module has no attribute {name}")

router = APIRouter(prefix="/user", tags=["User Management"])

class UserRegistrationRequest(BaseModel):
    user_id: str
    api_key: str = Field(..., description="OKX API Key")
    api_secret: str = Field(..., description="OKX API Secret")
    passphrase: str = Field(..., description="OKX API Passphrase")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": 123456789,
                "api_key": "your-api-key",
                "api_secret": "your-api-secret",
                "passphrase": "your-passphrase"
            }
        }
    }

class UserResponse(BaseModel):
    user_id: str
    status: str
    registration_date: int
    okx_uid: Optional[str] = None
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": 123456789,
                "status": "registered",
                "registration_date": 1678901234,
                "okx_uid": "646396755365762614"
            }
        }
    }

class OkxUidResponse(BaseModel):
    user_id: str
    okx_uid: str
    is_invitee: bool
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": 123456789,
                "okx_uid": "646396755365762614",
                "is_invitee": True
            }
        }
    }

@router.post("/register",
    response_model=UserResponse,
    summary="새로운 사용자 등록",
    description="OKX API 키와 함께 새로운 사용자를 등록합니다.",
    responses={
        200: {
            "description": "사용자 등록 성공",
            "model": UserResponse
        },
        400: {"description": "사용자 등록 실패 또는 이미 존재하는 사용자"},
        422: {"description": "잘못된 입력 데이터"}
    })
async def register_user(
    request: UserRegistrationRequest = Body(
        ...,
        description="사용자 등록을 위한 요청 데이터"
    ),
    db: Session = Depends(get_db)
):
    try:
        # 이미 등록된 사용자인지 확인
        existing_keys = await redis_client.hgetall(f"user:{request.user_id}:api:keys")
        if existing_keys:
            raise HTTPException(
                status_code=400,
                detail="이미 등록된 사용자입니다."
            )
            
        # Redis에 API 키 정보 저장
        await redis_client.hmset(f"user:{request.user_id}:api:keys", {
            'api_key': request.api_key,
            'api_secret': request.api_secret,
            'passphrase': request.passphrase
        })
        
        # TimescaleDB에 API 정보 저장 (필요 시 확장 가능)
        
        
        
        # OKX UID 가져오기 및 저장 시도
        okx_uid = None
        try:
            is_invitee, uid = get_uid_from_api_keys(request.api_key, request.api_secret, request.passphrase)
            if uid:
                # OKX UID를 Redis에 저장
                await store_okx_uid(request.user_id, uid)
                okx_uid = uid
                print(f"사용자 {request.user_id}의 OKX UID {uid} 저장 완료")
        except Exception as e:
            # OKX UID 가져오기 실패해도 사용자 등록은 계속 진행
            print(f"OKX UID 가져오기 실패: {str(e)}")
            
        
        
        # 기본 트레이딩 설정 저장
        await redis_client.hmset(
            f"user:{request.user_id}:preferences", 
            {k: str(v) for k, v in DEFAULT_TRADING_SETTINGS.items()}
        )
        # 사용자 상태 초기화
        await redis_client.set(f"user:{request.user_id}:trading:status", "stopped")
        
        if okx_uid is not None:
            await redis_client.hmset(
                f"user:{okx_uid}:preferences", 
                {k: str(v) for k, v in DEFAULT_TRADING_SETTINGS.items()}
            )
            await redis_client.hmset(f"user:{okx_uid}:trading:status", "stopped")
            print("❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥 ")
        

        
        # 트레이딩 통계 초기화
        registration_time = int(time.time())
        await redis_client.hmset(f"user:{request.user_id}:stats", {
            'total_trades': '0',
            'entry_trade': '0',
            'successful_trades': '0',
            'profit_percentage': '0',
            'registration_date': str(registration_time),
            'last_trade_date': '0'
        })
        
        if okx_uid is not None:
            await redis_client.hmset(f"user:{okx_uid}:stats", {
                'total_trades': '0',
                'entry_trade': '0',
                'successful_trades': '0',
                'profit_percentage': '0',
                'registration_date': str(registration_time),
                'last_trade_date': '0'
            })
        
        return UserResponse(
            user_id=request.user_id,
            status="registered",
            registration_date=registration_time,
            okx_uid=okx_uid
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"사용자 등록 중 오류 발생: {str(e)}"
        )

@router.get("/{user_id}",
    response_model=UserResponse,
    summary="사용자 정보 조회",
    description="등록된 사용자의 정보를 조회합니다.",
    responses={
        200: {
            "description": "사용자 정보 조회 성공",
            "model": UserResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def get_user(user_id: str, db: Session = Depends(get_db)):
    try:
        # 사용자 존재 여부 확인
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            raise HTTPException(
                status_code=404,
                detail="등록되지 않은 사용자입니다."
            )
            
        # 사용자 상태 정보 조회
        stats = await redis_client.hgetall(f"user:{user_id}:stats")
        status = await redis_client.get(f"user:{user_id}:trading:status")
        
        # OKX UID 조회
        okx_uid = await get_okx_uid_from_telegram(user_id)
        
        # status 처리 - bytes일 수도 있고 str일 수도 있음
        status_str = status.decode() if isinstance(status, bytes) else status
        if not status_str:
            status_str = "stopped"
            print("❤️‍🔥❤️‍🔥❤️‍🔥❤️‍🔥 !!!")

        # registration_date 처리 - bytes일 수도 있고 str일 수도 있음
        registration_date_bytes = stats.get(b'registration_date', b'0')
        if isinstance(registration_date_bytes, bytes):
            registration_date = int(registration_date_bytes.decode() or '0')
        else:
            # 이미 문자열이거나 다른 형태인 경우
            registration_date = int(str(registration_date_bytes) or '0')
        
        return UserResponse(
            user_id=user_id,
            status=status_str,
            registration_date=registration_date,
            okx_uid=okx_uid
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"사용자 정보 조회 중 오류 발생: {str(e)}"
        )

@router.get("/{user_id}/okx_uid",
    response_model=OkxUidResponse,
    summary="사용자 OKX UID 조회",
    description="등록된 사용자의 OKX UID를 조회합니다.",
    responses={
        200: {
            "description": "OKX UID 조회 성공",
            "model": OkxUidResponse
        },
        404: {"description": "사용자를 찾을 수 없거나 OKX UID가 없음"}
    })
async def get_okx_uid(user_id: str, db: Session = Depends(get_db)):
    try:
        # 사용자 존재 여부 확인
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            raise HTTPException(
                status_code=404,
                detail="등록되지 않은 사용자입니다."
            )
            
        # OKX UID 조회
        okx_uid = await get_okx_uid_from_telegram(user_id)
        
        # is_invitee 초기화
        is_invitee = False
        
        # OKX UID가 없는 경우 API 키로 가져오기 시도
        if not okx_uid:
            try:
                # API 키를 사용하여 OKX UID 가져오기
                api_key = api_keys.get(b'api_key', b'').decode() if isinstance(api_keys.get(b'api_key', b''), bytes) else api_keys.get(b'api_key', '')
                api_secret = api_keys.get(b'api_secret', b'').decode() if isinstance(api_keys.get(b'api_secret', b''), bytes) else api_keys.get(b'api_secret', '')
                passphrase = api_keys.get(b'passphrase', b'').decode() if isinstance(api_keys.get(b'passphrase', b''), bytes) else api_keys.get(b'passphrase', '')
                
                is_invitee, uid = get_uid_from_api_keys(api_key, api_secret, passphrase)
                
                if uid:
                    # OKX UID를 Redis에 저장
                    await store_okx_uid(user_id, uid)
                    okx_uid = uid
                else:
                    raise HTTPException(
                        status_code=404,
                        detail="OKX UID를 가져올 수 없습니다."
                    )
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"OKX UID 가져오기 중 오류 발생: {str(e)}"
                )
        else:
            # 이미 UID가 있는 경우 초대 여부만 확인
            is_invitee = True  # 실제로는 초대 여부 확인 로직이 필요할 수 있음
            
        return OkxUidResponse(
            user_id=user_id,
            okx_uid=okx_uid,
            is_invitee=is_invitee
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"OKX UID 조회 중 오류 발생: {str(e)}"
        )

@router.post("/{user_id}/okx_uid/{okx_uid}",
    response_model=OkxUidResponse,
    summary="사용자 OKX UID 설정",
    description="사용자의 OKX UID를 수동으로 설정합니다.",
    responses={
        200: {
            "description": "OKX UID 설정 성공",
            "model": OkxUidResponse
        },
        404: {"description": "사용자를 찾을 수 없음"}
    })
async def set_okx_uid(user_id: str, okx_uid: str):
    try:
        # 사용자 존재 여부 확인
        api_keys = await redis_client.hgetall(f"user:{user_id}:api:keys")
        if not api_keys:
            raise HTTPException(
                status_code=404,
                detail="등록되지 않은 사용자입니다."
            )
            
        # OKX UID를 Redis에 저장
        await store_okx_uid(user_id, okx_uid)
        
        # 초대 여부 확인 (실제 구현에서는 이 부분에 로직 추가 필요)
        is_invitee = True
        
        return OkxUidResponse(
            user_id=user_id,
            okx_uid=okx_uid,
            is_invitee=is_invitee
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"OKX UID 설정 중 오류 발생: {str(e)}"
        )

@router.get("/okx/{okx_uid}/telegram",
    summary="OKX UID로 텔레그램 ID 조회",
    description="OKX UID에 해당하는 텔레그램 ID를 조회합니다.",
    responses={
        200: {
            "description": "텔레그램 ID 조회 성공"
        },
        404: {"description": "OKX UID에 해당하는 텔레그램 ID를 찾을 수 없음"}
    })
async def get_telegram_id_from_okx_uid(okx_uid: str):
    try:
        # 모든 사용자 키를 검색하기 위한 패턴
        pattern = "user:*:okx_uid"
        keys = await redis_client.keys(pattern)
        
        valid_telegram_ids = []
        
        for key in keys:
            # Redis 키에서 저장된 OKX UID 값 가져오기
            stored_uid = await redis_client.get(key)
            
            # stored_uid 값 처리 (bytes일 수도 있고 str일 수도 있음)
            stored_uid_str = stored_uid.decode() if isinstance(stored_uid, bytes) else stored_uid
            
            # 요청된 OKX UID와 일치하는 경우
            if stored_uid and stored_uid_str == okx_uid:
                # user:123456789:okx_uid 형식에서 user_id(텔레그램 ID) 추출
                user_key = key.decode() if isinstance(key, bytes) else key
                user_id = user_key.split(':')[1]
                
                # 숫자로 시작하는 텔레그램 ID만 추가 (OKX UID는 일반적으로 매우 긴 숫자)
                if user_id.isdigit() and len(user_id) < 15:
                    # 최근 활동 시간 확인 (가능한 경우)
                    last_activity = 0
                    try:
                        stats = await redis_client.hgetall(f"user:{user_id}:stats")
                        if stats and b'last_trade_date' in stats:
                            last_trade_date = stats[b'last_trade_date'] if isinstance(stats[b'last_trade_date'], bytes) else stats[b'last_trade_date'].encode()
                            last_activity = int(last_trade_date.decode() or '0')
                    except Exception as e:
                        print(f"통계 정보 가져오기 오류: {str(e)}")
                        pass
                    
                    valid_telegram_ids.append({
                        "telegram_id": int(user_id),
                        "last_activity": last_activity
                    })
        
        if valid_telegram_ids:
            # 최근 활동순으로 정렬
            valid_telegram_ids.sort(key=lambda x: x["last_activity"], reverse=True)
            
            # 모든 가능한 텔레그램 ID 반환 (최근 활동순)
            return {
                "primary_telegram_id": valid_telegram_ids[0]["telegram_id"],
                "all_telegram_ids": [id_info["telegram_id"] for id_info in valid_telegram_ids],
                "okx_uid": okx_uid
            }
        
        # 일치하는 OKX UID가 없는 경우
        raise HTTPException(
            status_code=404,
            detail=f"OKX UID {okx_uid}에 해당하는 텔레그램 ID를 찾을 수 없습니다."
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"텔레그램 ID 조회 중 오류 발생: {str(e)}"
        ) 
