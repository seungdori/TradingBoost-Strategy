import asyncio
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Query, WebSocket, WebSocketDisconnect
from pydantic import Field

from GRID.dtos.feature import CoinDto
from GRID.dtos.symbol import AccessListDto
from GRID.repositories.symbol_repository import (
    add_symbols,
    get_ban_list_from_db,
    get_white_list_from_db,
    remove_symbols,
)
from GRID.routes.connection_manager import ConnectionManager
from GRID.services import trading_data_service, trading_service
from shared.dtos.response import ResponseDto
from shared.dtos.trading import WinrateDto

router = APIRouter(prefix="/trading", tags=["trading"])
import logging

logging.basicConfig(level=logging.DEBUG)


        
#@router.get("/messages/{user_id}")
#async def get_user_messages(user_id: int):
#    messages = manager.get_user_messages(user_id)  # 저장된 메시지를 조회합니다.
#    print("[GET USER MESSAGES]", messages)
#    return {"user_id": user_id, "messages": messages}
        
#@router.post("/logs/{user_id}/")
#async def add_log_endpoint(user_id: int, log_message: str = Query(...)):
#    message = f"User {user_id}: {log_message}"
#    await manager.add_user_message(user_id, message)  # 메시지를 저장합니다.
#    print("[LOG BROADCASTED]", message)
#    return {"message": "Log broadcasted successfully"}
#
# Do not remove {enter_strategy}
@router.get(
    '/{exchange_name}/{enter_strategy}/winrate',
    response_model=ResponseDto,
    summary="전략별 승률 조회",
    description="""
# 전략별 승률 조회

특정 거래소와 진입 전략에 대한 심볼별 승률 통계를 조회합니다.

## URL 파라미터

- **exchange_name** (string): 거래소 이름
  - 지원: `okx`, `binance`, `upbit`, `bitget`, `okx_spot`, `binance_spot`, `bitget_spot`, `bybit`, `bybit_spot`
- **enter_strategy** (string): 진입 전략
  - `long`: 롱 포지션 전략
  - `short`: 숏 포지션 전략
  - `long-short`: 양방향 포지션 전략

## 반환 정보 (WinrateDto 배열)

각 심볼별로 다음 통계 제공:
- **symbol** (string): 거래 심볼 (예: "BTC/USDT")
- **win_rate** (float): 승률 (%, 0-100)
- **total_trades** (integer): 총 거래 횟수
- **wins** (integer): 승리한 거래 수
- **losses** (integer): 손실 거래 수
- **profit_factor** (float, optional): 수익 비율
- **average_win** (float, optional): 평균 수익 (USDT)
- **average_loss** (float, optional): 평균 손실 (USDT)

## 사용 시나리오

-  **전략 성과 분석**: 각 전략의 효과성 평가
-  **심볼 선택**: 승률 높은 심볼 우선 거래
-  **포트폴리오 최적화**: 수익성 높은 코인에 집중
-  **리스크 관리**: 승률 낮은 심볼 블랙리스트 추가
- 📋 **리포트 생성**: 전략별 성과 리포트 작성

## 예시 URL

```
GET /trading/okx/long/winrate
GET /trading/binance/short/winrate
GET /trading/upbit/long-short/winrate
```
""",
    responses={
        200: {
            "description": " 승률 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "with_data": {
                            "summary": "승률 데이터 있음",
                            "value": {
                                "success": True,
                                "message": "Success to fetch win rates.",
                                "meta": {"win_rates_length": 10},
                                "data": [
                                    {
                                        "symbol": "BTC/USDT",
                                        "win_rate": 65.5,
                                        "total_trades": 100,
                                        "wins": 66,
                                        "losses": 34,
                                        "profit_factor": 1.8,
                                        "average_win": 50.25,
                                        "average_loss": -28.10
                                    },
                                    {
                                        "symbol": "ETH/USDT",
                                        "win_rate": 58.3,
                                        "total_trades": 80,
                                        "wins": 47,
                                        "losses": 33,
                                        "profit_factor": 1.5,
                                        "average_win": 42.50,
                                        "average_loss": -25.30
                                    }
                                ]
                            }
                        },
                        "no_data": {
                            "summary": "거래 기록 없음",
                            "value": {
                                "success": True,
                                "message": "Success to fetch win rates.",
                                "meta": {"win_rates_length": 0},
                                "data": []
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
                        "invalid_exchange": {
                            "summary": "지원하지 않는 거래소",
                            "value": {
                                "success": False,
                                "message": "Invalid exchange_name",
                                "meta": {"error": "Exchange 'invalid_exchange' not supported"},
                                "data": None
                            }
                        },
                        "invalid_strategy": {
                            "summary": "잘못된 전략 이름",
                            "value": {
                                "success": False,
                                "message": "Invalid enter_strategy",
                                "meta": {"error": "Strategy 'invalid' not recognized"},
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 데이터 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "no_trades": {
                            "summary": "해당 전략의 거래 기록 없음",
                            "value": {
                                "success": True,
                                "message": "Success to fetch win rates.",
                                "meta": {"win_rates_length": 0, "note": "No trading history for this strategy"},
                                "data": []
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "데이터베이스 조회 실패",
                            "value": {
                                "success": False,
                                "message": "Failed to fetch win rates",
                                "meta": {
                                    "error": "Database connection error",
                                    "hint": "Check database connection"
                                },
                                "data": None
                            }
                        },
                        "calculation_error": {
                            "summary": "승률 계산 오류",
                            "value": {
                                "success": False,
                                "message": "Failed to calculate win rates",
                                "meta": {
                                    "error": "Division by zero in calculation",
                                    "hint": "Check trade data integrity"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_winrate(exchange_name: str, enter_strategy: str) -> ResponseDto[List[WinrateDto]]:
    print('[GET WIN RATE]', exchange_name, enter_strategy)
    win_rates: List[WinrateDto] = await trading_data_service.get_win_rates(
        exchange_name=exchange_name, enter_strategy=enter_strategy
    )
    return ResponseDto[List[WinrateDto]](
        success=True,
        message="Success to fetch win rates.",
        meta={'win_rates_length': len(win_rates)},
        data=win_rates,
    )


@router.post('/{exchange_name}/target_pnl')
async def set_target_pnl(exchange_name : str, user_id : int, target_pnl : float, target_type : str) -> None:
    print('[SET TARGET PNL]', exchange_name, user_id, target_pnl, target_type)
    



# Do not remove {enter_strategy}
@router.post(
    '/{exchange_name}/{enter_strategy}/chart',
    response_model=ResponseDto,
    summary="차트 이미지 생성",
    description="""
# 차트 이미지 생성

선택한 코인의 거래 차트 이미지를 생성하고 URL을 반환합니다.

## URL 파라미터

- **exchange_name** (string): 거래소 이름
  - 지원: `okx`, `binance`, `upbit`, `bitget`, `okx_spot`, `binance_spot`, `bitget_spot`, `bybit`, `bybit_spot`
- **enter_strategy** (string): 진입 전략
  - `long`: 롱 포지션 전략
  - `short`: 숏 포지션 전략
  - `long-short`: 양방향 포지션 전략

## 요청 본문 (CoinDto)

```json
{
  "symbol": "BTC/USDT"
}
```

- **symbol** (string, required): 차트를 생성할 거래 심볼
  - 형식: "BASE/QUOTE" (예: "BTC/USDT", "ETH/USDT")
  - 거래소별 지원 심볼 조회 필요

## 동작 방식

1. **가격 데이터 조회**: 거래소에서 OHLCV 데이터 수집
2. **그리드 레벨 표시**: 진입/청산 가격 레벨을 차트에 표시
3. **이미지 생성**: matplotlib/plotly를 이용한 차트 이미지 파일 생성
4. **저장 및 URL 반환**: 이미지를 서버/클라우드에 저장 후 접근 URL 반환

## 반환 정보

- **data** (string): 생성된 차트 이미지의 URL
  - 예: "https://example.com/charts/BTC_USDT_20250112.png"

## 사용 시나리오

-  **거래 분석**: 진입/청산 포인트 시각화
-  **리포트 생성**: 트레이딩 성과 리포트에 차트 포함
-  **텔레그램 알림**: 차트 이미지를 포함한 거래 알림 발송
- 🖼️ **웹 대시보드**: 실시간 차트 표시
- 📋 **백테스팅 분석**: 과거 전략 성과 시각화

## 예시 URL

```
POST /trading/okx/long/chart
POST /trading/binance/short/chart
POST /trading/upbit/long-short/chart
```
""",
    responses={
        200: {
            "description": " 차트 생성 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "chart_created": {
                            "summary": "차트 이미지 생성 성공",
                            "value": {
                                "success": True,
                                "message": "Success to fetch trading logs.",
                                "meta": {
                                    "symbol": "BTC/USDT",
                                    "file_size": "342KB",
                                    "generation_time_ms": 1250
                                },
                                "data": "https://example.com/charts/BTC_USDT_20250112_153045.png"
                            }
                        },
                        "cloud_storage": {
                            "summary": "클라우드 스토리지 URL",
                            "value": {
                                "success": True,
                                "message": "Success to fetch trading logs.",
                                "meta": {
                                    "symbol": "ETH/USDT",
                                    "storage": "AWS S3",
                                    "expires_at": "2025-01-19T15:30:45Z"
                                },
                                "data": "https://s3.amazonaws.com/trading-charts/ETH_USDT_grid.png"
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
                        "invalid_symbol": {
                            "summary": "잘못된 심볼 형식",
                            "value": {
                                "success": False,
                                "message": "Invalid symbol format",
                                "meta": {
                                    "error": "Symbol must be in BASE/QUOTE format",
                                    "provided": "BTCUSDT",
                                    "hint": "Use 'BTC/USDT' instead"
                                },
                                "data": None
                            }
                        },
                        "unsupported_symbol": {
                            "summary": "지원하지 않는 심볼",
                            "value": {
                                "success": False,
                                "message": "Symbol not supported on exchange",
                                "meta": {
                                    "error": "DOGE/USDT not available on upbit",
                                    "hint": "Check supported symbols for this exchange"
                                },
                                "data": None
                            }
                        },
                        "no_price_data": {
                            "summary": "가격 데이터 없음",
                            "value": {
                                "success": False,
                                "message": "No price data available",
                                "meta": {
                                    "error": "Insufficient historical data for XYZ/USDT",
                                    "hint": "Symbol may be newly listed or delisted"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        422: {
            "description": "🚫 유효성 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_symbol": {
                            "summary": "심볼 필드 누락",
                            "value": {
                                "success": False,
                                "message": "Validation error",
                                "meta": {
                                    "error": "Field 'symbol' is required",
                                    "hint": "Provide symbol in request body"
                                },
                                "data": None
                            }
                        },
                        "invalid_json": {
                            "summary": "잘못된 JSON 형식",
                            "value": {
                                "success": False,
                                "message": "Invalid JSON in request body",
                                "meta": {
                                    "error": "Expecting property name enclosed in double quotes",
                                    "hint": "Check JSON syntax"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "image_generation_error": {
                            "summary": "이미지 생성 실패",
                            "value": {
                                "success": False,
                                "message": "Failed to generate chart image",
                                "meta": {
                                    "error": "matplotlib rendering error",
                                    "hint": "Check server dependencies and fonts"
                                },
                                "data": None
                            }
                        },
                        "storage_error": {
                            "summary": "이미지 저장 실패",
                            "value": {
                                "success": False,
                                "message": "Failed to save chart image",
                                "meta": {
                                    "error": "Disk space full or permission denied",
                                    "hint": "Check server storage capacity"
                                },
                                "data": None
                            }
                        },
                        "database_error": {
                            "summary": "데이터 조회 실패",
                            "value": {
                                "success": False,
                                "message": "Failed to fetch trading data",
                                "meta": {
                                    "error": "Database connection timeout",
                                    "hint": "Retry after a moment"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        503: {
            "description": " 거래소 서비스 이용 불가",
            "content": {
                "application/json": {
                    "examples": {
                        "exchange_unavailable": {
                            "summary": "거래소 API 응답 없음",
                            "value": {
                                "success": False,
                                "message": "Exchange API unavailable",
                                "meta": {
                                    "error": "OKX API not responding",
                                    "retry_after": 60,
                                    "hint": "Exchange may be under maintenance"
                                },
                                "data": None
                            }
                        },
                        "rate_limit_exchange": {
                            "summary": "거래소 API 요청 한도 초과",
                            "value": {
                                "success": False,
                                "message": "Exchange rate limit exceeded",
                                "meta": {
                                    "error": "Binance: Too many requests",
                                    "retry_after": 120,
                                    "hint": "Wait and retry"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def create_chart_image(exchange_name: str, dto: CoinDto, enter_strategy: str,) -> ResponseDto[str | None]:
    print("[CREATE CHART]", exchange_name, dto)
    try:
        file_url = await trading_data_service.create_chart_image(
            exchange_name=exchange_name,
            selected_coin_name=dto.symbol,
            enter_strategy=enter_strategy
        )
        return ResponseDto[str | None](
            success=True,
            message="Success to fetch trading logs.",
            data=file_url
        )

    except Exception as e:
        return ResponseDto[str | None](
            success=False,
            message=str(e),
            data=None
        )





@router.get(
    "/blacklist/{exchange_name}/{user_id}",
    response_model=ResponseDto,
    summary="거래 금지 심볼 목록 조회",
    description="""
# 거래 금지 심볼 목록 조회 (블랙리스트)

사용자가 설정한 거래 금지(블랙리스트) 심볼 목록을 조회합니다.

## URL 파라미터

- **exchange_name** (string): 거래소 이름
  - 지원: `okx`, `binance`, `upbit`, `bitget`, `okx_spot`, `binance_spot`, `bitget_spot`, `bybit`, `bybit_spot`
- **user_id** (integer): 사용자 ID
  - 예: 12345, 67890

## 반환 정보

- **data** (array of strings): 블랙리스트에 등록된 심볼 목록
  - 형식: ["SYMBOL1/QUOTE", "SYMBOL2/QUOTE", ...]
  - 빈 배열: 블랙리스트가 없는 경우

## 사용 시나리오

- 🚫 **특정 코인 제외**: 손실이 큰 코인을 거래에서 제외
-  **변동성 필터링**: 변동성이 너무 큰 코인 차단
-  **리스크 관리**: 안전한 거래를 위한 코인 필터
-  **전략 최적화**: 승률 낮은 심볼 제외
- 👤 **사용자 맞춤 설정**: 개인 선호도에 따른 거래 설정

## 예시 URL

```
GET /trading/blacklist/okx/12345
GET /trading/blacklist/binance/67890
GET /trading/blacklist/upbit/11111
```
""",
    responses={
        200: {
            "description": " 블랙리스트 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "with_blacklist": {
                            "summary": "블랙리스트 있음",
                            "value": {
                                "success": True,
                                "message": "Success to get blacklist",
                                "meta": {"count": 5},
                                "data": ["DOGE/USDT", "SHIB/USDT", "PEPE/USDT", "FLOKI/USDT", "MEME/USDT"]
                            }
                        },
                        "empty_blacklist": {
                            "summary": "블랙리스트 없음",
                            "value": {
                                "success": True,
                                "message": "Success to get blacklist",
                                "meta": {"count": 0, "note": "No symbols in blacklist"},
                                "data": []
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
                        "invalid_exchange": {
                            "summary": "지원하지 않는 거래소",
                            "value": {
                                "success": False,
                                "message": "Error to get blacklist",
                                "meta": {
                                    "error": "Exchange 'invalid_exchange' not supported",
                                    "hint": "Use okx, binance, upbit, bitget, etc."
                                },
                                "data": None
                            }
                        },
                        "invalid_user_id": {
                            "summary": "잘못된 사용자 ID",
                            "value": {
                                "success": False,
                                "message": "Error to get blacklist",
                                "meta": {
                                    "error": "Invalid user_id format",
                                    "hint": "user_id must be a positive integer"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자를 찾을 수 없음",
                            "value": {
                                "success": False,
                                "message": "Error to get blacklist",
                                "meta": {
                                    "error": "User ID 99999 not found",
                                    "hint": "Check if user is registered"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "데이터베이스 조회 실패",
                            "value": {
                                "success": False,
                                "message": "Error to get blacklist",
                                "meta": {
                                    "error": "Database connection failed",
                                    "hint": "Retry after a moment"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_black_list_endpoint(exchange_name: str, user_id: int) -> ResponseDto:
    try:
        symbols = await get_ban_list_from_db(user_id, exchange_name)
        logging.debug(f"Returning symbols: {symbols}")
        return ResponseDto(
            success=True,
            message="Success to get blacklist",
            data=symbols
        )
    except Exception as e:
        logging.error(f"Error: {e}")
        return ResponseDto(
            success=False,
            message="Error to get blacklist",
            meta={"error": str(e)},
            data=None
        )

@router.get(
    "/whitelist/{exchange_name}/{user_id}",
    response_model=ResponseDto,
    summary="거래 허용 심볼 목록 조회",
    description="""
# 거래 허용 심볼 목록 조회 (화이트리스트)

사용자가 설정한 거래 허용(화이트리스트) 심볼 목록을 조회합니다.

## URL 파라미터

- **exchange_name** (string): 거래소 이름
  - 지원: `okx`, `binance`, `upbit`, `bitget`, `okx_spot`, `binance_spot`, `bitget_spot`, `bybit`, `bybit_spot`
- **user_id** (integer): 사용자 ID
  - 예: 12345, 67890

## 반환 정보

- **data** (array of strings): 화이트리스트에 등록된 심볼 목록
  - 형식: ["SYMBOL1/QUOTE", "SYMBOL2/QUOTE", ...]
  - 빈 배열: 화이트리스트가 없는 경우 (모든 심볼 허용)

## 사용 시나리오

-  **특정 코인만 거래**: 승률 높은 코인만 선택적으로 거래
-  **안전한 코인 풀**: 메이저 코인만 거래하여 리스크 최소화
- 💎 **고수익 코인 집중**: 높은 수익을 내는 코인에만 투자
-  **전략 최적화**: 백테스팅에서 검증된 심볼만 활용
- 👤 **사용자 맞춤 설정**: 개인 선호도와 전략에 맞는 코인 선택

## 블랙리스트와 화이트리스트 우선순위

- 화이트리스트가 설정되어 있으면 **해당 심볼만** 거래
- 블랙리스트는 화이트리스트보다 **우선순위가 높음**
- 화이트리스트가 비어있으면 **모든 심볼 허용** (블랙리스트 제외)

## 예시 URL

```
GET /trading/whitelist/okx/12345
GET /trading/whitelist/binance/67890
GET /trading/whitelist/upbit/11111
```
""",
    responses={
        200: {
            "description": " 화이트리스트 조회 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "with_whitelist": {
                            "summary": "화이트리스트 있음",
                            "value": {
                                "success": True,
                                "message": "Success to get whitelist",
                                "meta": {"count": 5},
                                "data": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
                            }
                        },
                        "empty_whitelist": {
                            "summary": "화이트리스트 없음 (모든 심볼 허용)",
                            "value": {
                                "success": True,
                                "message": "Success to get whitelist",
                                "meta": {"count": 0, "note": "All symbols allowed except blacklist"},
                                "data": []
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
                        "invalid_exchange": {
                            "summary": "지원하지 않는 거래소",
                            "value": {
                                "success": False,
                                "message": "Error to get whitelist",
                                "meta": {
                                    "error": "Exchange 'invalid_exchange' not supported",
                                    "hint": "Use okx, binance, upbit, bitget, etc."
                                },
                                "data": None
                            }
                        },
                        "invalid_user_id": {
                            "summary": "잘못된 사용자 ID",
                            "value": {
                                "success": False,
                                "message": "Error to get whitelist",
                                "meta": {
                                    "error": "Invalid user_id format",
                                    "hint": "user_id must be a positive integer"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자를 찾을 수 없음",
                            "value": {
                                "success": False,
                                "message": "Error to get whitelist",
                                "meta": {
                                    "error": "User ID 99999 not found",
                                    "hint": "Check if user is registered"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "데이터베이스 조회 실패",
                            "value": {
                                "success": False,
                                "message": "Error to get whitelist",
                                "meta": {
                                    "error": "Database connection failed",
                                    "hint": "Retry after a moment"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_white_list_endpoint(exchange_name: str, user_id: int) -> ResponseDto:
    try:
        symbols = await get_white_list_from_db(user_id, exchange_name)
        logging.debug(f"Returning symbols: {symbols}")
        return ResponseDto(
            success=True,
            message="Success to get whitelist",
            data=symbols
        )
    except Exception as e:
        logging.error(f"Error: {e}")
        return ResponseDto(
            success=False,
            message="Error to get whitelist",
            meta={"error": str(e)},
            data=None
        )

@router.put(
    '/symbols/access',
    response_model=ResponseDto,
    summary="블랙/화이트리스트 심볼 추가",
    description="""
# 블랙/화이트리스트 심볼 추가

블랙리스트 또는 화이트리스트에 심볼을 추가합니다.

## 쿼리 파라미터

- **exchange_name** (string, required): 거래소 이름
  - 예: `okx`, `binance`, `upbit`, `bitget`, `okx_spot`, `binance_spot`, `bitget_spot`
- **user_id** (integer, required): 사용자 ID
  - 예: 12345, 67890
- **symbols** (string, required): 쉼표로 구분된 심볼
  - 형식: "SYMBOL1,SYMBOL2,SYMBOL3"
  - 예: "BTC,ETH,XRP", "DOGE,SHIB,PEPE"
  - 공백은 자동으로 제거됨
- **type** (string, required): 리스트 유형
  - `blacklist`: 거래 금지 심볼 추가
  - `whitelist`: 거래 허용 심볼 추가

## 동작 방식

1. 쉼표로 구분된 심볼 문자열을 배열로 파싱
2. 각 심볼 앞뒤 공백 제거
3. 지정된 리스트(blacklist/whitelist)에 심볼 추가
4. 업데이트된 전체 리스트 반환

## 반환 정보

- **data** (array of strings): 업데이트된 전체 심볼 목록
  - 기존 심볼 + 새로 추가된 심볼
  - 중복 제거됨

## 사용 시나리오

- 🚫 **블랙리스트 추가**: 손실 발생 코인을 거래에서 제외
-  **화이트리스트 추가**: 수익성 좋은 코인을 거래 허용 목록에 추가
-  **전략 조정**: 실시간으로 거래 대상 심볼 조정
-  **리스크 관리**: 변동성 큰 코인을 즉시 블랙리스트 처리
- 💎 **수익 최적화**: 백테스팅 결과를 반영하여 화이트리스트 구성

## 예시 URL

```
PUT /trading/symbols/access?exchange_name=okx&user_id=12345&symbols=BTC,ETH,XRP&type=blacklist
PUT /trading/symbols/access?exchange_name=binance&user_id=67890&symbols=DOGE,SHIB&type=whitelist
PUT /trading/symbols/access?exchange_name=upbit&user_id=11111&symbols=BTC,ETH&type=whitelist
```
""",
    responses={
        200: {
            "description": " 심볼 추가 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "blacklist_added": {
                            "summary": "블랙리스트에 심볼 추가",
                            "value": {
                                "success": True,
                                "message": "Success to add symbols to list",
                                "meta": {
                                    "list_type": "blacklist",
                                    "added_count": 2,
                                    "total_count": 5
                                },
                                "data": ["DOGE/USDT", "SHIB/USDT", "PEPE/USDT", "BTC/USDT", "ETH/USDT"]
                            }
                        },
                        "whitelist_added": {
                            "summary": "화이트리스트에 심볼 추가",
                            "value": {
                                "success": True,
                                "message": "Success to add symbols to list",
                                "meta": {
                                    "list_type": "whitelist",
                                    "added_count": 3,
                                    "total_count": 8
                                },
                                "data": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOT/USDT", "MATIC/USDT"]
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
                        "invalid_type": {
                            "summary": "잘못된 리스트 유형",
                            "value": {
                                "success": False,
                                "message": "Error to add symbols to list",
                                "meta": {
                                    "error": "Invalid list type: invalid_type",
                                    "hint": "Use 'blacklist' or 'whitelist'"
                                },
                                "data": None
                            }
                        },
                        "empty_symbols": {
                            "summary": "빈 심볼 문자열",
                            "value": {
                                "success": False,
                                "message": "Error to add symbols to list",
                                "meta": {
                                    "error": "No symbols provided",
                                    "hint": "Provide comma-separated symbols"
                                },
                                "data": None
                            }
                        },
                        "invalid_symbol_format": {
                            "summary": "잘못된 심볼 형식",
                            "value": {
                                "success": False,
                                "message": "Error to add symbols to list",
                                "meta": {
                                    "error": "Invalid symbol format: BTCUSDT",
                                    "hint": "Use BASE/QUOTE format (e.g., BTC/USDT)"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        422: {
            "description": "🚫 유효성 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_parameters": {
                            "summary": "필수 파라미터 누락",
                            "value": {
                                "success": False,
                                "message": "Validation error",
                                "meta": {
                                    "error": "Missing required parameters: exchange_name, user_id, symbols, type",
                                    "hint": "Provide all required query parameters"
                                },
                                "data": None
                            }
                        },
                        "invalid_user_id": {
                            "summary": "잘못된 user_id 형식",
                            "value": {
                                "success": False,
                                "message": "Validation error",
                                "meta": {
                                    "error": "user_id must be an integer",
                                    "hint": "Provide numeric user ID"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자를 찾을 수 없음",
                            "value": {
                                "success": False,
                                "message": "Error to add symbols to list",
                                "meta": {
                                    "error": "User ID 99999 not found",
                                    "hint": "Check if user is registered"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "데이터베이스 업데이트 실패",
                            "value": {
                                "success": False,
                                "message": "Error to add symbols to list",
                                "meta": {
                                    "error": "Failed to update database",
                                    "hint": "Retry after a moment"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def add_symbol_access_list(
    exchange_name: str = Query(..., description="Name of the exchange", example="okx"),
    user_id: int = Query(..., description="User ID", example=1234),
    symbols: str = Query(..., description="Comma-separated symbols to add", example="BTC,ETH,XRP"),
    type: str = Query(..., description="Type of the list, either 'blacklist' or 'whitelist'", example="blacklist")
) -> ResponseDto:
    try:
        # Split the comma-separated string into a list and strip whitespace
        symbol_list = [symbol.strip() for symbol in symbols.split(',') if symbol.strip()]
        list_type = type.lower()
        if list_type not in {"blacklist", "whitelist"}:
            raise ValueError(f"Invalid list type: {type}")

        await add_symbols(user_id, exchange_name, symbol_list, list_type)

        updated = await trading_service.get_list_from_db(exchange_name, user_id, list_type)
        return ResponseDto(
            success=True,
            message="Success to add symbols to list",
            data=updated
        )
    except Exception as e:
        return ResponseDto(
            success=False,
            message="Error to add symbols to list",
            meta={"error": str(e)},
            data=None
        )


@router.delete(
    '/symbols/access',
    response_model=ResponseDto,
    summary="블랙/화이트리스트 심볼 제거",
    description="""
# 블랙/화이트리스트 심볼 제거

블랙리스트 또는 화이트리스트에서 심볼을 제거합니다.

## 요청 본문 (AccessListDto)

```json
{
  "exchange_name": "okx",
  "user_id": 12345,
  "symbols": ["BTC/USDT", "ETH/USDT"],
  "type": "blacklist"
}
```

### 필드 설명

- **exchange_name** (string, required): 거래소 이름
  - 예: `okx`, `binance`, `upbit`, `bitget`
- **user_id** (integer, required): 사용자 ID
  - 예: 12345, 67890
- **symbols** (array of strings, required): 제거할 심볼 목록
  - 형식: ["SYMBOL1/QUOTE", "SYMBOL2/QUOTE", ...]
  - 예: ["BTC/USDT", "ETH/USDT"], ["DOGE/USDT", "SHIB/USDT"]
- **type** (string, required): 리스트 유형
  - `blacklist`: 블랙리스트에서 제거
  - `whitelist`: 화이트리스트에서 제거

## 동작 방식

1. 요청 본문에서 제거할 심볼 목록 파싱
2. 지정된 리스트(blacklist/whitelist)에서 해당 심볼들 제거
3. 업데이트된 전체 리스트 반환
4. 존재하지 않는 심볼은 무시됨

## 반환 정보

- **data** (array of strings): 업데이트된 전체 심볼 목록
  - 기존 심볼 - 제거된 심볼
  - 빈 배열: 모든 심볼이 제거된 경우

## 사용 시나리오

-  **블랙리스트 해제**: 손실 원인 해결 후 거래 재개
-  **화이트리스트 조정**: 수익성 낮은 코인을 목록에서 제거
-  **전략 재조정**: 실시간으로 거래 대상 심볼 변경
-  **선택적 제거**: 일부 심볼만 제거하여 유연하게 관리
- 🧹 **리스트 정리**: 불필요한 심볼 일괄 제거

## 예시 요청

```json
// 블랙리스트에서 BTC, ETH 제거
{
  "exchange_name": "okx",
  "user_id": 12345,
  "symbols": ["BTC/USDT", "ETH/USDT"],
  "type": "blacklist"
}

// 화이트리스트에서 여러 심볼 제거
{
  "exchange_name": "binance",
  "user_id": 67890,
  "symbols": ["DOGE/USDT", "SHIB/USDT", "PEPE/USDT"],
  "type": "whitelist"
}
```
""",
    responses={
        200: {
            "description": " 심볼 제거 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "blacklist_removed": {
                            "summary": "블랙리스트에서 심볼 제거",
                            "value": {
                                "success": True,
                                "message": "Success to delete symbols from list",
                                "meta": {
                                    "list_type": "blacklist",
                                    "removed_count": 2,
                                    "remaining_count": 3
                                },
                                "data": ["DOGE/USDT", "SHIB/USDT", "PEPE/USDT"]
                            }
                        },
                        "whitelist_removed": {
                            "summary": "화이트리스트에서 심볼 제거",
                            "value": {
                                "success": True,
                                "message": "Success to delete symbols from list",
                                "meta": {
                                    "list_type": "whitelist",
                                    "removed_count": 3,
                                    "remaining_count": 5
                                },
                                "data": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
                            }
                        },
                        "all_removed": {
                            "summary": "모든 심볼 제거됨",
                            "value": {
                                "success": True,
                                "message": "Success to delete symbols from list",
                                "meta": {
                                    "list_type": "blacklist",
                                    "removed_count": 5,
                                    "remaining_count": 0,
                                    "note": "All symbols removed from list"
                                },
                                "data": []
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
                        "invalid_type": {
                            "summary": "잘못된 리스트 유형",
                            "value": {
                                "success": False,
                                "message": "Error to delete symbols from list",
                                "meta": {
                                    "error": "Invalid list type: invalid_type",
                                    "hint": "Use 'blacklist' or 'whitelist'"
                                },
                                "data": None
                            }
                        },
                        "empty_symbols": {
                            "summary": "빈 심볼 배열",
                            "value": {
                                "success": False,
                                "message": "Error to delete symbols from list",
                                "meta": {
                                    "error": "No symbols provided for removal",
                                    "hint": "Provide at least one symbol in the array"
                                },
                                "data": None
                            }
                        },
                        "symbols_not_found": {
                            "summary": "제거할 심볼이 리스트에 없음",
                            "value": {
                                "success": False,
                                "message": "Error to delete symbols from list",
                                "meta": {
                                    "error": "Symbols not found in list: ['XYZ/USDT', 'ABC/USDT']",
                                    "hint": "Check if symbols are in the list"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        422: {
            "description": "🚫 유효성 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_json": {
                            "summary": "잘못된 JSON 형식",
                            "value": {
                                "success": False,
                                "message": "Validation error",
                                "meta": {
                                    "error": "Invalid JSON in request body",
                                    "hint": "Check JSON syntax and field types"
                                },
                                "data": None
                            }
                        },
                        "missing_fields": {
                            "summary": "필수 필드 누락",
                            "value": {
                                "success": False,
                                "message": "Validation error",
                                "meta": {
                                    "error": "Missing required fields: exchange_name, user_id, symbols, type",
                                    "hint": "Provide all required fields"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": " 사용자 또는 리스트 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "user_not_found": {
                            "summary": "사용자를 찾을 수 없음",
                            "value": {
                                "success": False,
                                "message": "Error to delete symbols from list",
                                "meta": {
                                    "error": "User ID 99999 not found",
                                    "hint": "Check if user is registered"
                                },
                                "data": None
                            }
                        },
                        "list_empty": {
                            "summary": "리스트가 비어있음",
                            "value": {
                                "success": False,
                                "message": "Error to delete symbols from list",
                                "meta": {
                                    "error": "List is already empty",
                                    "hint": "No symbols to remove"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": " 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "데이터베이스 업데이트 실패",
                            "value": {
                                "success": False,
                                "message": "Error to delete symbols from list",
                                "meta": {
                                    "error": "Failed to update database",
                                    "hint": "Retry after a moment"
                                },
                                "data": None
                            }
                        }
                    }
                }
            }
        }
    }
)
async def delete_symbol_access_item(dto: AccessListDto = Body(...)) -> ResponseDto:
    print("[SYMBOL ACCESS LIST]", dto)
    try:
        list_type = dto.type.lower()
        if list_type not in {"blacklist", "whitelist"}:
            raise ValueError(f"Invalid list type: {dto.type}")

        removed = await remove_symbols(
            dto.user_id,
            dto.exchange_name,
            dto.symbols,
            list_type,
        )
        logging.debug(
            "Removed symbols from access list",
            extra={
                "exchange": dto.exchange_name,
                "user_id": dto.user_id,
                "type": dto.type,
                "count": removed
            }
        )

        updated = await trading_service.get_list_from_db(
            dto.exchange_name,
            dto.user_id,
            list_type
        )

        return ResponseDto(
            success=True,
            message="Success to delete symbols from list",
            data=updated
        )
    except Exception as e:
        return ResponseDto(
            success=False,
            message="Error to delete symbols from list",
            meta={"error": str(e)},
            data=None
        )
        
        
