from typing import Any, List

from fastapi import APIRouter

from GRID.services import api_key_service, exchange_service
from shared.docs import error_content, error_example
from shared.dtos.exchange import ApiKeyDto, ApiKeys, ExchangeApiKeyDto, WalletDto
from shared.dtos.response import ResponseDto

router = APIRouter(prefix="/exchange", tags=["exchange"])


@router.get(
    "/{exchange_name}/wallet",
    response_model=ResponseDto[WalletDto],
    summary="지갑 정보 조회",
    description="""
거래소의 지갑 잔고 정보를 조회합니다.

## 파라미터

- **exchange_name**: 거래소 이름
  - 지원: okx, binance, upbit, bitget, okx_spot, binance_spot, bitget_spot, bybit, bybit_spot

## 반환 정보

- **total_balance**: 총 잔고 (USDT 또는 KRW)
  - 가용 잔고 + 사용 중인 증거금 + 미실현 손익
- **wallet_balance**: 지갑 잔고 (거래소에 실제로 있는 금액)
- **total_unrealized_profit**: 미실현 손익 (현재 오픈 포지션의 평가 손익)

## 사용 시나리오

- 거래 가능한 자금 확인
- 포트폴리오 자산 현황 모니터링
- 레버리지 사용률 계산
- 리스크 관리 (증거금율 확인)

## 주의사항

- API 키가 미리 등록되어 있어야 합니다 (`/exchange/keys`로 등록)
- 거래소 API 키에 '잔고 조회' 권한이 있어야 합니다
- 거래소 API 요청 한도에 영향을 줄 수 있습니다
""",
    responses={
        200: {
            "description": "✅ 지갑 정보 조회 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Get okx wallet success",
                        "meta": {},
                        "data": {
                            "exchange_name": "okx",
                            "total_balance": 10542.75,
                            "wallet_balance": 10000.00,
                            "total_unrealized_profit": 542.75
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 잘못된 요청 - 지원하지 않는 거래소",
            "content": error_content(
                message="Unknown exchange name: invalid_exchange",
                path="/exchange/{exchange_name}/wallet",
                method="GET",
                status_code=400,
                details={"exchange_name": "invalid_exchange"},
                extra_meta={"error": "ValueError: Unknown exchange name: invalid_exchange"},
            ),
        },
        401: {
            "description": "🔒 인증 실패 - API 키 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_api_key": {
                            "summary": "잘못된 API 키",
                            "value": error_example(
                                message="Exchange API authentication failed",
                                path="/exchange/{exchange_name}/wallet",
                                method="GET",
                                status_code=401,
                                details={"exchange": "okx"},
                                extra_meta={
                                    "error": "Invalid API key or secret",
                                    "exchange": "okx",
                                    "error_code": "50113",
                                },
                            ),
                        },
                        "expired_api_key": {
                            "summary": "만료된 API 키",
                            "value": error_example(
                                message="API key expired or revoked",
                                path="/exchange/{exchange_name}/wallet",
                                method="GET",
                                status_code=401,
                                details={"exchange": "okx"},
                                extra_meta={
                                    "error": "API key timestamp expired",
                                    "exchange": "okx",
                                },
                            ),
                        },
                    }
                }
            }
        },
        403: {
            "description": "🚫 권한 없음 - API 키 권한 부족",
            "content": error_content(
                message="Insufficient API key permissions",
                path="/exchange/{exchange_name}/wallet",
                method="GET",
                status_code=403,
                details={"exchange": "okx"},
                extra_meta={
                    "error": "API key does not have 'Read' permission",
                    "exchange": "okx",
                    "required_permissions": ["Read"],
                },
            ),
        },
        429: {
            "description": "⏱️ 요청 한도 초과",
            "content": error_content(
                message="Exchange API rate limit exceeded",
                path="/exchange/{exchange_name}/wallet",
                method="GET",
                status_code=429,
                extra_meta={
                    "error": "Too many requests",
                    "retry_after": 60,
                    "exchange": "okx",
                },
            ),
        },
        500: {
            "description": "💥 서버 오류 - 내부 처리 실패",
            "content": error_content(
                message="Failed to fetch wallet information",
                path="/exchange/{exchange_name}/wallet",
                method="GET",
                status_code=500,
                extra_meta={
                    "error": "Internal server error while processing wallet data",
                    "exchange": "okx",
                },
            ),
        },
        503: {
            "description": "🔧 거래소 서비스 이용 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_maintenance": {
                            "summary": "거래소 점검 중",
                            "value": error_example(
                                message="Exchange is under maintenance",
                                path="/exchange/{exchange_name}/wallet",
                                method="GET",
                                status_code=503,
                                details={"exchange": "okx"},
                                extra_meta={
                                    "error": "Service temporarily unavailable",
                                    "exchange": "okx",
                                    "retry_after": 3600,
                                },
                            ),
                        },
                        "exchange_timeout": {
                            "summary": "거래소 API 타임아웃",
                            "value": error_example(
                                message="Exchange API request timeout",
                                path="/exchange/{exchange_name}/wallet",
                                method="GET",
                                status_code=503,
                                details={"exchange": "okx"},
                                extra_meta={
                                    "error": "Connection timeout after 30 seconds",
                                    "exchange": "okx",
                                },
                            ),
                        },
                    }
                }
            }
        }
    }
)
async def get_wallet(exchange_name: str) -> ResponseDto[WalletDto | None]:
    try:
        wallet: WalletDto = await exchange_service.get_wallet(exchange_name)
        return ResponseDto[WalletDto | None](
            success=True,
            message=f"Get {exchange_name} wallet success",
            data=wallet
        )

    except Exception as e:
        print(e)
        return ResponseDto[WalletDto | None](
            success=False,
            message=f"{e}",
            data=None
        )


@router.post(
    '/{exchange_name}',
    response_model=ResponseDto[List[Any]],
    summary="포지션 목록 조회",
    description="""
거래소의 모든 오픈 포지션 정보를 조회합니다.

## 파라미터

- **exchange_name**: 거래소 이름
  - 지원: okx, binance, upbit, bitget, okx_spot, binance_spot, bitget_spot, bybit, bybit_spot

## 반환 정보

각 포지션의 상세 정보를 배열로 반환:
- **symbol**: 거래 심볼 (예: BTC/USDT, ETH-USDT-SWAP)
- **contracts**: 계약 수량
- **entry_price**: 평균 진입 가격
- **unrealized_pnl**: 미실현 손익
- **side**: 포지션 방향 (long/short)
- **leverage**: 적용된 레버리지
- **liquidation_price**: 청산 가격 (선물)

## 사용 시나리오

- 현재 오픈 포지션 확인
- 포트폴리오 분산도 분석
- 리스크 노출도 계산
- 청산 위험 모니터링

## 주의사항

- 포지션이 없으면 빈 배열 반환
- 스팟 거래소(upbit 등)는 보유 중인 자산 목록 반환
- 거래소별로 반환 필드가 약간 다를 수 있음
""",
    responses={
        200: {
            "description": "✅ 포지션 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "with_positions": {
                            "summary": "포지션 있음",
                            "value": {
                                "success": True,
                                "message": "okx",
                                "meta": {},
                                "data": [
                                    {
                                        "symbol": "BTC-USDT-SWAP",
                                        "contracts": 0.5,
                                        "entry_price": 43500.0,
                                        "mark_price": 43750.0,
                                        "unrealized_pnl": 125.50,
                                        "side": "long",
                                        "leverage": 20,
                                        "liquidation_price": 41200.0,
                                        "margin": 1087.5
                                    },
                                    {
                                        "symbol": "ETH-USDT-SWAP",
                                        "contracts": 2.0,
                                        "entry_price": 2300.0,
                                        "mark_price": 2320.0,
                                        "unrealized_pnl": 40.0,
                                        "side": "long",
                                        "leverage": 10,
                                        "liquidation_price": 2070.0,
                                        "margin": 460.0
                                    }
                                ]
                            }
                        },
                        "no_positions": {
                            "summary": "포지션 없음",
                            "value": {
                                "success": True,
                                "message": "okx",
                                "meta": {},
                                "data": []
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 잘못된 요청",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "Invalid exchange: invalid_exchange",
                        "meta": {"error": "ValueError: Invalid exchange"},
                        "data": []
                    }
                }
            }
        },
        401: {
            "description": "🔒 인증 실패",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "API authentication failed",
                        "meta": {
                            "error": "Invalid API credentials",
                            "exchange": "okx"
                        },
                        "data": []
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "Failed to fetch positions",
                        "meta": {
                            "error": "Internal error while processing position data",
                            "exchange": "okx"
                        },
                        "data": []
                    }
                }
            }
        },
        503: {
            "description": "🔧 거래소 서비스 불가",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "Exchange API unavailable",
                        "meta": {
                            "error": "Exchange is under maintenance",
                            "exchange": "okx",
                            "retry_after": 3600
                        },
                        "data": []
                    }
                }
            }
        }
    }
)
async def get_balance(exchange_name: str) -> ResponseDto[List[Any]]:
    try:
        positions = await exchange_service.fetch_position(exchange_name)

        return ResponseDto[List[Any]](
            success=True,
            message=exchange_name,
            data=positions
        )

    except Exception as e:
        print(e)
        return ResponseDto[List[Any]](
            success=False,
            message=f"{e}",
            data=[]
        )


@router.get(
    '/keys/{exchange_name}',
    response_model=ResponseDto[ApiKeyDto],
    summary="거래소 API 키 조회",
    description="""
저장된 거래소 API 키 정보를 조회합니다 (마스킹됨).

## 파라미터

- **exchange_name**: 거래소 이름
  - 지원: okx, binance, upbit, bitget, okx_spot, binance_spot, bitget_spot, bybit, bybit_spot

## 반환 정보

보안을 위해 실제 키 값은 마스킹되어 반환됩니다:
- **api_key**: API 키 (예: 89d5c...7cdb42 → xxxxx***xxxxx)
- **secret_key**: Secret 키 (예: 135CF...32B90 → xxxxx***xxxxx)
- **password**: Passphrase (OKX 등에서 사용, 마스킹됨)

## 사용 시나리오

- API 키 등록 여부 확인
- 키 유효성 검증 전 확인
- 디버깅 시 키 존재 확인

## 보안 주의사항

- **실제 키 값은 절대 반환되지 않습니다**
- 키의 존재 여부와 형식만 확인 가능
- 전체 키를 확인하려면 키 저장소에 직접 접근 필요
""",
    responses={
        200: {
            "description": "✅ API 키 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "with_passphrase": {
                            "summary": "Passphrase 있음 (OKX 등)",
                            "value": {
                                "success": True,
                                "message": "Get okx api key success.",
                                "meta": {},
                                "data": {
                                    "api_key": "xxxxx***xxxxx",
                                    "secret_key": "xxxxx***xxxxx",
                                    "password": "xxxxx***xxxxx"
                                }
                            }
                        },
                        "without_passphrase": {
                            "summary": "Passphrase 없음 (Binance 등)",
                            "value": {
                                "success": True,
                                "message": "Get binance api key success.",
                                "meta": {},
                                "data": {
                                    "api_key": "xxxxx***xxxxx",
                                    "secret_key": "xxxxx***xxxxx",
                                    "password": None
                                }
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": "❌ API 키 없음",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "API key not found for exchange: okx",
                        "meta": {
                            "error": "No API key registered",
                            "exchange": "okx",
                            "hint": "Please register API key using PATCH /exchange/keys"
                        },
                        "data": None
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "Failed to retrieve API key",
                        "meta": {
                            "error": "Database connection error",
                            "exchange": "okx"
                        },
                        "data": None
                    }
                }
            }
        }
    }
)
async def get_exchange_keys(exchange_name: str) -> ResponseDto[ApiKeyDto]:
    api_keys: ApiKeyDto = await api_key_service.get_exchange_api_keys(exchange_name)

    return ResponseDto[ApiKeyDto](
        success=True,
        message=f"Get {exchange_name} api key success.",
        data=api_keys
    )


@router.patch(
    '/keys',
    response_model=ResponseDto[ApiKeyDto],
    summary="거래소 API 키 등록/업데이트",
    description="""
거래소 API 키 정보를 등록하거나 업데이트합니다.

## 요청 본문

```json
{
  "exchange_name": "okx",
  "api_key": "89d5cdd8-192b-4b7e-a4ce-d5666b7cdb42",
  "secret_key": "135CF39F458BC20E0FA9FB3A9EA32B90",
  "password": "MyPassphrase123"
}
```

### 필드 설명
- **exchange_name** (필수): 거래소 이름
- **api_key** (필수): 거래소에서 발급한 API 키 (평문)
- **secret_key** (필수): 거래소에서 발급한 Secret 키 (평문)
- **password** (선택): Passphrase (OKX, KuCoin 등에서 필요)

## 동작 방식

1. **API 키 형식 검증**: 키 길이, 형식 확인
2. **거래소 연결 테스트**: 키 유효성 실시간 검증
3. **암호화 저장**: AES-256으로 암호화하여 데이터베이스 저장
4. **CCXT 인스턴스 재초기화**: 새 키로 거래소 클라이언트 갱신
5. **캐시 무효화**: 기존 API 응답 캐시 삭제

## 사용 시나리오

- **최초 설정**: 데스크탑 앱 설치 후 첫 API 키 등록
- **키 갱신**: 만료되거나 유출된 키 교체
- **권한 변경**: 더 많은/적은 권한의 키로 교체
- **거래소 추가**: 새로운 거래소 계정 연동

## 보안 주의사항

⚠️ **API 키 권한 설정**
- **필수 권한**: 읽기 (Read), 거래 (Trade)
- **권장하지 않음**: 출금 (Withdraw), 자금 이체 (Transfer)
- **이유**: 키 유출 시 피해 최소화

⚠️ **키 관리**
- IP 화이트리스트 설정 권장
- 주기적인 키 갱신 (3-6개월)
- 2FA 인증 활성화
- 절대 공개 저장소에 커밋하지 말 것

⚠️ **전송 보안**
- HTTPS 필수
- 평문 키는 요청 시에만 전송
- 저장 시 AES-256 암호화
""",
    responses={
        200: {
            "description": "✅ API 키 등록/업데이트 성공",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "okx credential update success",
                        "meta": {
                            "encrypted": True,
                            "validated": True,
                            "cache_cleared": True
                        },
                        "data": {
                            "api_key": "xxxxx***xxxxx",
                            "secret_key": "xxxxx***xxxxx",
                            "password": "xxxxx***xxxxx"
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 잘못된 요청 - 키 형식 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_format": {
                            "summary": "키 형식 오류",
                            "value": {
                                "success": False,
                                "message": "okx credential update fail",
                                "meta": {
                                    "error": "Invalid API key format",
                                    "details": "API key must be at least 8 characters"
                                },
                                "data": None
                            }
                        },
                        "missing_passphrase": {
                            "summary": "Passphrase 누락 (OKX)",
                            "value": {
                                "success": False,
                                "message": "okx credential update fail",
                                "meta": {
                                    "error": "Passphrase required for OKX",
                                    "exchange": "okx"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        401: {
            "description": "🔒 인증 실패 - 키 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_credentials": {
                            "summary": "잘못된 인증 정보",
                            "value": {
                                "success": False,
                                "message": "okx credential update fail",
                                "meta": {
                                    "error": "Exchange API authentication failed",
                                    "details": "Invalid API key or secret",
                                    "exchange": "okx",
                                    "error_code": "50113"
                                },
                                "data": None
                            }
                        },
                        "wrong_passphrase": {
                            "summary": "잘못된 Passphrase",
                            "value": {
                                "success": False,
                                "message": "okx credential update fail",
                                "meta": {
                                    "error": "Invalid passphrase",
                                    "exchange": "okx"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        403: {
            "description": "🚫 권한 부족",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "okx credential update fail",
                        "meta": {
                            "error": "Insufficient API key permissions",
                            "required_permissions": ["Read", "Trade"],
                            "current_permissions": ["Read"],
                            "exchange": "okx"
                        },
                        "data": None
                    }
                }
            }
        },
        429: {
            "description": "⏱️ 요청 한도 초과",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "okx credential update fail",
                        "meta": {
                            "error": "Too many API key update attempts",
                            "retry_after": 300,
                            "remaining_attempts": 0,
                            "max_attempts": 5
                        },
                        "data": None
                    }
                }
            }
        },
        500: {
            "description": "💥 서버 오류",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "okx credential update fail",
                        "meta": {
                            "error": "Failed to encrypt and store API key",
                            "exchange": "okx"
                        },
                        "data": None
                    }
                }
            }
        },
        503: {
            "description": "🔧 거래소 서비스 불가",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "message": "okx credential update fail",
                        "meta": {
                            "error": "Cannot validate API key: Exchange is under maintenance",
                            "exchange": "okx",
                            "retry_after": 3600
                        },
                        "data": None
                    }
                }
            }
        }
    }
)
async def update_api_keys(dto: ExchangeApiKeyDto) -> ResponseDto[ApiKeyDto | None]:
    try:
        updated_api_keys: ApiKeyDto = await api_key_service.update_exchange_api_keys(dto)

        exchange_service.revalidate_cache(dto.exchange_name)

        return ResponseDto[ApiKeyDto | None](
            success=True,
            message=f"{dto.exchange_name} credential update success",
            data=updated_api_keys
        )
    except Exception as e:
        print('[UPDATE API KEYS EXCEPTION]', e)
        return ResponseDto[ApiKeyDto | None](
            success=False,
            message=f"{dto.exchange_name} credential update fail",
            meta={"error": str(e)},
            data=None
        )
