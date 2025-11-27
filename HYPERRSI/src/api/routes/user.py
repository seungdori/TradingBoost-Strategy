import asyncio
import time
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shared.database.session import get_db
from HYPERRSI.src.utils.check_invitee import get_uid_from_api_keys
from HYPERRSI.src.utils.uid_manager import (
    get_okx_uid_by_telegram_id,
    get_or_create_okx_uid,
    update_user_okx_uid,
)
from shared.constants.default_settings import DEFAULT_TRADING_SETTINGS
from shared.database.redis_helper import get_redis_client
from shared.database.redis_patterns import scan_keys_pattern, redis_context, RedisTimeout
from shared.helpers.user_id_resolver import get_okx_uid_from_telegram, store_user_id_mapping


# Module-level attribute for backward compatibility
def __getattr__(name):
    if name == "redis_client":
        return get_redis_client()
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
                "user_id": "123456789",
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

@router.post(
    "/register",
    response_model=UserResponse,
    summary="새로운 사용자 등록 및 초기화",
    description="""
# 새로운 사용자 등록 및 초기화

OKX API 자격증명을 사용하여 새로운 사용자를 등록하고 초기 설정을 생성합니다.

## 요청 본문

- **user_id** (string, required): 사용자 식별자 (텔레그램 ID 등)
  - 예시: "1709556958"
- **api_key** (string, required): OKX API 키
  - OKX 거래소에서 발급받은 API 키
- **api_secret** (string, required): OKX API 시크릿
  - API 키와 쌍을 이루는 비밀 키
- **passphrase** (string, required): OKX API 패스프레이즈
  - API 생성 시 설정한 패스프레이즈

## 동작 방식

1. **중복 확인**: 이미 등록된 사용자인지 확인
2. **API 키 저장**: Redis에 암호화된 API 자격증명 저장
3. **OKX UID 조회**: API 키를 사용하여 OKX UID 자동 조회 및 저장
4. **기본 설정 초기화**:
   - 트레이딩 설정 (레버리지, 방향, TP/SL 등)
   - 거래 상태 (stopped)
   - 통계 정보 (거래 횟수, 수익률 등)
5. **응답 반환**: 등록된 사용자 정보 반환

## 반환 데이터 구조

- **user_id** (string): 사용자 식별자
- **status** (string): 등록 상태 ("registered")
- **registration_date** (integer): 등록 타임스탬프 (Unix timestamp)
- **okx_uid** (string, optional): OKX UID (자동 조회 성공 시)

## 초기화되는 설정

### Redis 키 구조
- `user:{user_id}:api:keys` - API 자격증명
- `user:{user_id}:preferences` - 트레이딩 설정
- `user:{user_id}:symbol:{symbol}:status` - 심볼별 거래 상태
- `user:{user_id}:stats` - 통계 정보
- `user:{user_id}:okx_uid` - OKX UID 매핑

### 기본 설정 값
- leverage: 10
- direction: "롱숏"
- 트레이딩 상태: "stopped"
- 거래 통계: 0으로 초기화

## 사용 시나리오

- 🆕 **신규 가입**: 첫 사용자 등록 및 초기화
- 🔑 **API 연동**: OKX 거래소 계정 연결
- ⚙️ **자동 설정**: 기본 설정 자동 생성
-  **UID 매핑**: 텔레그램 ID ↔ OKX UID 연결

## 예시 URL

```
POST /user/register
```

## 예시 curl 명령

```bash
curl -X POST "http://localhost:8000/user/register" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": "1709556958",
    "api_key": "your-okx-api-key",
    "api_secret": "your-okx-api-secret",
    "passphrase": "your-okx-passphrase"
  }'
```
""",
    responses={
        200: {
            "description": " 사용자 등록 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "registration_success": {
                            "summary": "등록 성공 (OKX UID 포함)",
                            "value": {
                                "user_id": "1709556958",
                                "status": "registered",
                                "registration_date": 1678901234,
                                "okx_uid": "646396755365762614"
                            }
                        },
                        "registration_without_uid": {
                            "summary": "등록 성공 (OKX UID 미조회)",
                            "value": {
                                "user_id": "1709556958",
                                "status": "registered",
                                "registration_date": 1678901234,
                                "okx_uid": None
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": " 등록 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "already_registered": {
                            "summary": "이미 등록된 사용자",
                            "value": {
                                "detail": "이미 등록된 사용자입니다."
                            }
                        },
                        "registration_error": {
                            "summary": "등록 중 오류",
                            "value": {
                                "detail": "사용자 등록 중 오류 발생: API key validation failed"
                            }
                        }
                    }
                }
            }
        },
        422: {
            "description": "🚫 잘못된 입력 데이터",
            "content": {
                "application/json": {
                    "examples": {
                        "validation_error": {
                            "summary": "필수 필드 누락",
                            "value": {
                                "detail": "Field required: api_key"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def register_user(
    request: UserRegistrationRequest = Body(
        ...,
        description="사용자 등록을 위한 요청 데이터"
    ),
    db: Session = Depends(get_db)
):
    try:
        # Use context manager for proper connection management and timeout protection
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            # 이미 등록된 사용자인지 확인
            existing_keys = await asyncio.wait_for(
                redis.hgetall(f"user:{request.user_id}:api:keys"),
                timeout=RedisTimeout.FAST_OPERATION
            )
            if existing_keys:
                raise HTTPException(
                    status_code=400,
                    detail="이미 등록된 사용자입니다."
                )

            # Redis에 API 키 정보 저장
            await asyncio.wait_for(
                redis.hmset(f"user:{request.user_id}:api:keys", {
                    'api_key': request.api_key,
                    'api_secret': request.api_secret,
                    'passphrase': request.passphrase
                }),
                timeout=RedisTimeout.FAST_OPERATION
            )

            # TimescaleDB에 API 정보 저장 (필요 시 확장 가능)



            # OKX UID 가져오기 및 저장 시도
            okx_uid = None
            try:
                is_invitee, uid = get_uid_from_api_keys(request.api_key, request.api_secret, request.passphrase)
                if uid:
                    # OKX UID를 Redis에 저장
                    await store_user_id_mapping(request.user_id, uid)
                    okx_uid = uid
                    print(f"사용자 {request.user_id}의 OKX UID {uid} 저장 완료")
            except Exception as e:
                # OKX UID 가져오기 실패해도 사용자 등록은 계속 진행
                print(f"OKX UID 가져오기 실패: {str(e)}")



            # 기본 트레이딩 설정 저장
            await asyncio.wait_for(
                redis.hmset(
                    f"user:{request.user_id}:preferences",
                    {k: str(v) for k, v in DEFAULT_TRADING_SETTINGS.items()}
                ),
                timeout=RedisTimeout.FAST_OPERATION
            )
            # 심볼별 상태는 트레이딩 시작 시 생성됨 (user:{okx_uid}:symbol:{symbol}:status)
            # 등록 시점에는 특정 심볼이 없으므로 상태 키를 생성하지 않음

            if okx_uid is not None:
                await asyncio.wait_for(
                    redis.hmset(
                        f"user:{okx_uid}:preferences",
                        {k: str(v) for k, v in DEFAULT_TRADING_SETTINGS.items()}
                    ),
                    timeout=RedisTimeout.FAST_OPERATION
                )
                # 심볼별 상태는 트레이딩 시작 시 생성됨
                print("❤️‍❤️‍❤️‍❤️‍ ")



            # 트레이딩 통계 초기화
            registration_time = int(time.time())
            await asyncio.wait_for(
                redis.hmset(f"user:{request.user_id}:stats", {
                    'total_trades': '0',
                    'entry_trade': '0',
                    'successful_trades': '0',
                    'profit_percentage': '0',
                    'registration_date': str(registration_time),
                    'last_trade_date': '0'
                }),
                timeout=RedisTimeout.FAST_OPERATION
            )

            if okx_uid is not None:
                await asyncio.wait_for(
                    redis.hmset(f"user:{okx_uid}:stats", {
                        'total_trades': '0',
                        'entry_trade': '0',
                        'successful_trades': '0',
                        'profit_percentage': '0',
                        'registration_date': str(registration_time),
                        'last_trade_date': '0'
                    }),
                    timeout=RedisTimeout.FAST_OPERATION
                )

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

@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="사용자 정보 조회",
    description="""
# 사용자 정보 조회

등록된 사용자의 상태 정보를 조회합니다.

## 경로 파라미터

- **user_id** (string, required): 사용자 식별자

## 동작 방식

1. **API 키 확인**: Redis에서 사용자의 API 키 존재 여부 확인
2. **통계 조회**: 거래 통계 정보 조회
3. **상태 조회**: 현재 트레이딩 상태 확인
4. **OKX UID 조회**: 매핑된 OKX UID 확인
5. **응답 반환**: 사용자 정보 반환

## 반환 데이터 구조

- **user_id** (string): 사용자 식별자
- **status** (string): 트레이딩 상태 ("running", "stopped")
- **registration_date** (integer): 등록 타임스탬프
- **okx_uid** (string, optional): OKX UID

## 사용 시나리오

- 👤 **프로필 조회**: 사용자 기본 정보 확인
-  **상태 확인**: 현재 트레이딩 상태 모니터링
-  **존재 여부 확인**: 사용자 등록 상태 검증
""",
    responses={
        200: {
            "description": " 사용자 정보 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "active_user": {
                            "summary": "활성 사용자",
                            "value": {
                                "user_id": "1709556958",
                                "status": "running",
                                "registration_date": 1678901234,
                                "okx_uid": "646396755365762614"
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
                        "not_registered": {
                            "summary": "미등록 사용자",
                            "value": {
                                "detail": "등록되지 않은 사용자입니다."
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_user(user_id: str, db: Session = Depends(get_db)):
    try:
        # Use context manager for proper connection management and timeout protection
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            # 사용자 존재 여부 확인
            api_keys = await asyncio.wait_for(
                redis.hgetall(f"user:{user_id}:api:keys"),
                timeout=RedisTimeout.FAST_OPERATION
            )
            if not api_keys:
                raise HTTPException(
                    status_code=404,
                    detail="등록되지 않은 사용자입니다."
                )

            # 사용자 상태 정보 조회
            stats = await asyncio.wait_for(
                redis.hgetall(f"user:{user_id}:stats"),
                timeout=RedisTimeout.FAST_OPERATION
            )

        # OKX UID 조회
        okx_uid = await get_okx_uid_from_telegram(user_id)

        # 심볼별 상태 확인 - 하나라도 running이면 running
        status_str = "stopped"
        async with asyncio.timeout(RedisTimeout.FAST_OPERATION):
            symbol_status_keys = await redis.keys(f"user:{user_id}:symbol:*:status")
            for key in symbol_status_keys:
                status = await redis.get(key)
                if status:
                    s = status.decode() if isinstance(status, bytes) else status
                    if s == "running":
                        status_str = "running"
                        break

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

@router.get(
    "/{user_id}/okx_uid",
    response_model=OkxUidResponse,
    summary="사용자 OKX UID 조회 및 자동 생성",
    description="""
# 사용자 OKX UID 조회 및 자동 생성

등록된 사용자의 OKX UID를 조회하고, 없는 경우 API 키를 사용하여 자동으로 조회 및 저장합니다.

## 동작 방식

1. **UID 조회**: Redis에서 매핑된 OKX UID 확인
2. **자동 조회**: UID가 없으면 API 키로 OKX UID 가져오기
3. **자동 저장**: 조회된 UID를 Redis에 저장
4. **응답 반환**: OKX UID 및 초대 여부 정보 반환

## 반환 정보

- **user_id**: 사용자 식별자
- **okx_uid**: OKX UID (18자리 숫자)
- **is_invitee**: 초대 여부 (OKX 친구 초대 프로그램)
""",
    responses={
        200: {
            "description": " OKX UID 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "uid_found": {
                            "summary": "OKX UID 조회 성공",
                            "value": {
                                "user_id": "1709556958",
                                "okx_uid": "646396755365762614",
                                "is_invitee": True
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " OKX UID를 찾을 수 없음"
        }
    }
)
async def get_okx_uid(user_id: str, db: Session = Depends(get_db)):
    try:
        # Use context manager for proper connection management and timeout protection
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            # 사용자 존재 여부 확인
            api_keys = await asyncio.wait_for(
                redis.hgetall(f"user:{user_id}:api:keys"),
                timeout=RedisTimeout.FAST_OPERATION
            )
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
                    await store_user_id_mapping(user_id, uid)
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

@router.post(
    "/{user_id}/okx_uid/{okx_uid}",
    response_model=OkxUidResponse,
    summary="사용자 OKX UID 수동 설정",
    description="""
# 사용자 OKX UID 수동 설정

사용자의 OKX UID를 수동으로 설정합니다. 자동 조회가 실패한 경우 또는 UID 매핑을 강제로 변경해야 할 때 사용합니다.

## 경로 파라미터

- **user_id** (string): 사용자 식별자 (텔레그램 ID)
- **okx_uid** (string): OKX UID (18자리 숫자)

## 동작 방식

1. **사용자 확인**: API 키 존재 여부 확인
2. **UID 저장**: Redis에 user_id ↔ okx_uid 매핑 저장
3. **응답 반환**: 설정된 UID 정보 반환
""",
    responses={
        200: {
            "description": " OKX UID 설정 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "uid_set": {
                            "summary": "UID 설정 완료",
                            "value": {
                                "user_id": "1709556958",
                                "okx_uid": "646396755365762614",
                                "is_invitee": True
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
async def set_okx_uid(user_id: str, okx_uid: str):
    try:
        # Use context manager for proper connection management and timeout protection
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            # 사용자 존재 여부 확인
            api_keys = await asyncio.wait_for(
                redis.hgetall(f"user:{user_id}:api:keys"),
                timeout=RedisTimeout.FAST_OPERATION
            )
            if not api_keys:
                raise HTTPException(
                    status_code=404,
                    detail="등록되지 않은 사용자입니다."
                )

        # OKX UID를 Redis에 저장
        await store_user_id_mapping(user_id, okx_uid)

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

@router.get(
    "/okx/{okx_uid}/telegram",
    summary="OKX UID → 텔레그램 ID 역방향 조회",
    description="""
# OKX UID → 텔레그램 ID 역방향 조회

OKX UID에 매핑된 텔레그램 ID를 역방향으로 조회합니다. 여러 계정이 동일한 OKX UID를 사용하는 경우 모두 반환합니다.

## 경로 파라미터

- **okx_uid** (string): OKX UID (18자리 숫자)

## 동작 방식

1. **패턴 검색**: Redis에서 user:*:okx_uid 패턴으로 모든 매핑 조회
2. **UID 일치 확인**: 요청된 OKX UID와 일치하는 항목 필터링
3. **활동 기준 정렬**: 최근 거래 활동 순으로 정렬
4. **응답 반환**: 주 계정 + 전체 계정 목록 반환

## 반환 정보

- **primary_telegram_id** (integer): 가장 최근 활동한 주 텔레그램 ID
- **all_telegram_ids** (array): 모든 매핑된 텔레그램 ID 목록 (활동순)
- **okx_uid** (string): 조회한 OKX UID

## 사용 시나리오

-  **계정 통합**: 동일 OKX 계정 사용하는 여러 텔레그램 계정 확인
-  **UID 추적**: OKX UID로 사용자 식별
-  **다중 계정 관리**: 한 OKX 계정의 모든 연결된 계정 조회
""",
    responses={
        200: {
            "description": " 텔레그램 ID 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "single_account": {
                            "summary": "단일 계정",
                            "value": {
                                "primary_telegram_id": 1709556958,
                                "all_telegram_ids": [1709556958],
                                "okx_uid": "646396755365762614"
                            }
                        },
                        "multiple_accounts": {
                            "summary": "다중 계정",
                            "value": {
                                "primary_telegram_id": 1709556958,
                                "all_telegram_ids": [1709556958, 1234567890, 9876543210],
                                "okx_uid": "646396755365762614"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " OKX UID에 매핑된 텔레그램 ID 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "uid_not_found": {
                            "summary": "매핑 없음",
                            "value": {
                                "detail": "OKX UID 646396755365762614에 해당하는 텔레그램 ID를 찾을 수 없습니다."
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_telegram_id_from_okx_uid(okx_uid: str):
    try:
        # Use context manager for proper connection management and timeout protection
        async with redis_context(timeout=RedisTimeout.NORMAL_OPERATION) as redis:
            # 모든 사용자 키를 검색하기 위한 패턴
            pattern = "user:*:okx_uid"
            # Use SCAN instead of KEYS to avoid blocking Redis
            keys = await scan_keys_pattern(pattern, redis=redis)

            valid_telegram_ids = []

            for key in keys:
                # Redis 키에서 저장된 OKX UID 값 가져오기
                stored_uid = await asyncio.wait_for(
                    redis.get(key),
                    timeout=RedisTimeout.FAST_OPERATION
                )

                # stored_uid 값 처리 (bytes일 수도 있고 str일 수도 있음)
                stored_uid_str = stored_uid.decode() if isinstance(stored_uid, bytes) else stored_uid

                # 요청된 OKX UID와 일치하는 경우
                if stored_uid and stored_uid_str == okx_uid:
                    # user:123456789:okx_uid 형식에서 user_id(텔레그램 ID) 추출
                    user_key = key.decode() if isinstance(key, bytes) else key
                    user_id = user_key.split(':')[1]

                    # 숫자로 시작하는 텔레그램 ID만 추가 (13자리 미만은 텔레그램 ID)
                    if user_id.isdigit() and len(user_id) < 13:
                        # 최근 활동 시간 확인 (가능한 경우)
                        last_activity = 0
                        try:
                            stats = await asyncio.wait_for(
                                redis.hgetall(f"user:{user_id}:stats"),
                                timeout=RedisTimeout.FAST_OPERATION
                            )
                            if stats and b'last_trade_date' in stats:
                                last_trade_date = stats[b'last_trade_date'] if isinstance(stats[b'last_trade_date'], bytes) else stats[b'last_trade_date'].encode()
                                last_activity = int(last_trade_date.decode() or '0')
                        except Exception as e:
                            print(f"통계 정보 가져오기 오류: {str(e)}")
                            pass

                        # telegram_id는 정수여야 하므로 안전하게 변환
                        try:
                            telegram_id = int(user_id)
                        except (ValueError, TypeError):
                            # UUID인 경우 건너뛰기 (텔레그램 ID가 아님)
                            continue

                        valid_telegram_ids.append({
                            "telegram_id": telegram_id,
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
