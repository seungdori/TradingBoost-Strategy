"""
Backtest API routes.
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from uuid import uuid4, UUID
from typing import Optional

from BACKTEST.api.schemas import (
    BacktestRunRequest,
    BacktestDetailResponse,
    ErrorResponse
)
from BACKTEST.engine import BacktestEngine
from BACKTEST.data import TimescaleProvider
from BACKTEST.strategies import HyperrsiStrategy
from shared.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "/run",
    response_model=BacktestDetailResponse,
    summary="백테스트 실행",
    description="""
# 백테스트 실행

지정된 전략과 파라미터로 과거 데이터 기반 백테스트를 실행합니다.

## 요청 본문 (BacktestRunRequest)

### 필수 파라미터
- **symbol** (string, required): 거래 심볼
  - 형식: "BTC-USDT-SWAP", "ETH-USDT-SWAP"
  - TimescaleDB에 데이터가 있어야 함
  - OKX 거래소 영구선물 형식

- **timeframe** (string, required): 시간 프레임
  - 지원: 1m, 3m, 5m, 15m, 30m, 1h, 4h, 1d
  - 작은 timeframe일수록 정확도 높음, 실행 시간 증가
  - 권장: 5m 이상 (데이터 품질 및 성능 고려)

- **start_date/end_date** (datetime, required): 백테스트 기간
  - ISO 8601 형식: "2025-01-01T00:00:00Z"
  - end_date는 start_date보다 이후여야 함
  - 최소 기간: 1일 이상 권장
  - 최대 기간: 데이터 가용성에 따름

- **strategy_name** (string, required): 전략 이름
  - 현재 지원: "hyperrsi"
  - 향후 추가 예정: "grid", "bollinger", "macd"

### 선택 파라미터
- **strategy_params** (dict, optional): 전략별 파라미터
  - hyperrsi: rsi_oversold, rsi_overbought, leverage 등
  - 기본값: 전략별 기본 설정 적용
  - 자세한 파라미터는 하단 예시 참조

- **initial_balance** (float, optional): 초기 자산
  - 기본값: 10000.0 USDT
  - 범위: 100.0 ~ 1000000.0
  - 실제 투자 규모와 유사하게 설정 권장

- **fee_rate** (float, optional): 수수료율
  - 기본값: 0.0005 (0.05%)
  - OKX 기준: Maker 0.02%, Taker 0.05%
  - 실제 거래소 수수료 반영 필요

- **slippage_percent** (float, optional): 슬리피지
  - 기본값: 0.05 (0.05%)
  - 시장 상황에 따라 조정
  - 변동성 높을수록 높게 설정

## 동작 방식

1. **파라미터 검증**: 날짜, timeframe, strategy 유효성 확인
2. **데이터 로드**: TimescaleProvider에서 캔들 데이터 조회
3. **엔진 초기화**: BacktestEngine 생성 (잔고, 수수료, 슬리피지 설정)
4. **전략 실행**: HyperrsiStrategy로 매매 신호 생성
5. **주문 시뮬레이션**: 가상 주문 체결 및 포지션 관리
6. **성과 분석**: 수익률, Sharpe Ratio, MDD 계산
7. **결과 반환**: 거래 내역, 성과 지표, 자산 곡선

## 반환 정보 (BacktestDetailResponse)

### 메타데이터
- **id**: 백테스트 고유 ID (UUID)
- **symbol**: 거래 심볼
- **timeframe**: 시간 프레임
- **start_date/end_date**: 백테스트 기간
- **strategy_name**: 전략 이름
- **strategy_params**: 전략 파라미터

### 성과 지표
- **final_balance**: 최종 자산 (USDT)
- **total_return_percent**: 총 수익률 (%)
- **sharpe_ratio**: 샤프 비율 (위험 대비 수익)
- **max_drawdown_percent**: 최대 낙폭 (%)
- **win_rate**: 승률 (%)
- **profit_factor**: 손익비

### 거래 분석
- **total_trades**: 총 거래 수
- **winning_trades/losing_trades**: 수익/손실 거래 수
- **avg_win/avg_loss**: 평균 수익/손실 (USDT)
- **largest_win/largest_loss**: 최대 수익/손실 (USDT)
- **total_fees_paid**: 총 수수료 (USDT)

### 상세 데이터
- **trades**: 거래 내역 배열 (각 거래의 진입/청산 정보)
- **equity_curve**: 자산 곡선 데이터 (시간별 자산 변화)

## DCA (Dollar Cost Averaging) 지원

전략 파라미터에 DCA 설정을 포함할 수 있습니다:

- **pyramiding_enabled** (bool): DCA 활성화 여부
- **pyramiding_limit** (int, 1-10): 최대 추가 진입 횟수
- **entry_multiplier** (float, 0.1-1.0): 진입 규모 배율
- **pyramiding_entry_type** (str): 진입 기준 ("퍼센트 기준", "금액 기준", "ATR 기준")
- **pyramiding_value** (float): 진입 간격 값
- **entry_criterion** (str): 기준 가격 ("평균 단가", "최근 진입가")

DCA가 활성화되면 포지션당 여러 번 진입하여 평균 단가를 조정하고,
거래 결과에 `dca_count`, `entry_history`, `total_investment` 필드가 포함됩니다.

## 사용 시나리오

🎯 **전략 검증**: 실전 투입 전 과거 성과 확인
📊 **파라미터 최적화**: 다양한 파라미터 조합 테스트
⚡ **성과 비교**: 여러 전략 간 성과 비교
📉 **리스크 분석**: MDD, Sharpe Ratio로 리스크 평가
🔍 **백데이터 분석**: 특정 기간 시장 패턴 분석

## 주의사항

⚠️ 백테스트 결과는 미래 수익을 보장하지 않음
⚠️ 슬리피지와 수수료를 현실적으로 설정 필요
⚠️ 오버피팅 주의 (과거 데이터 과적합)
⚠️ 데이터 품질이 결과에 영향을 미침
⚠️ 긴 기간 백테스트는 실행 시간이 증가할 수 있음

## 예시 요청

```json
{
  "symbol": "BTC-USDT-SWAP",
  "timeframe": "5m",
  "start_date": "2025-01-01T00:00:00Z",
  "end_date": "2025-01-31T23:59:59Z",
  "strategy_name": "hyperrsi",
  "strategy_params": {
    "entry_option": "rsi_trend",
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "leverage": 10,
    "investment": 100,
    "stop_loss_percent": 2.0,
    "take_profit_percent": 4.0,
    "pyramiding_enabled": True,
    "pyramiding_limit": 3,
    "entry_multiplier": 0.5
  },
  "initial_balance": 10000.0,
  "fee_rate": 0.0005,
  "slippage_percent": 0.05
}
```
""",
    responses={
        200: {
            "description": "✅ 백테스트 실행 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "profitable_backtest": {
                            "summary": "수익형 백테스트 결과",
                            "value": {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "symbol": "BTC-USDT-SWAP",
                                "timeframe": "5m",
                                "start_date": "2025-01-01T00:00:00Z",
                                "end_date": "2025-01-31T23:59:59Z",
                                "strategy_name": "hyperrsi",
                                "strategy_params": {
                                    "entry_option": "rsi_trend",
                                    "rsi_oversold": 30,
                                    "leverage": 10
                                },
                                "initial_balance": 10000.0,
                                "final_balance": 12500.0,
                                "total_return_percent": 25.0,
                                "sharpe_ratio": 1.8,
                                "max_drawdown_percent": -8.5,
                                "total_trades": 45,
                                "winning_trades": 30,
                                "losing_trades": 15,
                                "win_rate": 66.67,
                                "profit_factor": 2.1,
                                "avg_win": 150.0,
                                "avg_loss": -80.0,
                                "total_fees_paid": 125.0
                            }
                        },
                        "loss_backtest": {
                            "summary": "손실형 백테스트 결과",
                            "value": {
                                "id": "660e8400-e29b-41d4-a716-446655440001",
                                "symbol": "ETH-USDT-SWAP",
                                "timeframe": "1h",
                                "start_date": "2025-01-01T00:00:00Z",
                                "end_date": "2025-01-31T23:59:59Z",
                                "strategy_name": "hyperrsi",
                                "strategy_params": {
                                    "entry_option": "rsi_only",
                                    "rsi_oversold": 20,
                                    "leverage": 5
                                },
                                "initial_balance": 10000.0,
                                "final_balance": 8500.0,
                                "total_return_percent": -15.0,
                                "sharpe_ratio": -0.5,
                                "max_drawdown_percent": -22.3,
                                "total_trades": 28,
                                "winning_trades": 10,
                                "losing_trades": 18,
                                "win_rate": 35.71,
                                "profit_factor": 0.7,
                                "total_fees_paid": 75.0
                            }
                        },
                        "dca_backtest": {
                            "summary": "DCA 전략 백테스트 결과",
                            "value": {
                                "id": "770e8400-e29b-41d4-a716-446655440002",
                                "symbol": "SOL-USDT-SWAP",
                                "timeframe": "15m",
                                "start_date": "2025-01-01T00:00:00Z",
                                "end_date": "2025-01-31T23:59:59Z",
                                "strategy_name": "hyperrsi",
                                "strategy_params": {
                                    "pyramiding_enabled": True,
                                    "pyramiding_limit": 5,
                                    "entry_multiplier": 0.5
                                },
                                "initial_balance": 10000.0,
                                "final_balance": 11800.0,
                                "total_return_percent": 18.0,
                                "sharpe_ratio": 1.5,
                                "max_drawdown_percent": -12.0,
                                "total_trades": 35,
                                "winning_trades": 25,
                                "losing_trades": 10,
                                "win_rate": 71.43,
                                "profit_factor": 2.5
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "❌ 잘못된 요청 - 검증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_dates": {
                            "summary": "잘못된 날짜 범위",
                            "value": {
                                "detail": "end_date must be after start_date"
                            }
                        },
                        "invalid_timeframe": {
                            "summary": "지원하지 않는 시간 프레임",
                            "value": {
                                "detail": "Unsupported timeframe: 2m. Supported: 1m, 3m, 5m, 15m, 30m, 1h, 4h, 1d"
                            }
                        },
                        "invalid_strategy": {
                            "summary": "지원하지 않는 전략",
                            "value": {
                                "detail": "Unknown strategy: bollinger. Supported strategies: hyperrsi"
                            }
                        },
                        "invalid_params": {
                            "summary": "잘못된 전략 파라미터",
                            "value": {
                                "detail": "Invalid strategy parameters: leverage must be between 1 and 125"
                            }
                        },
                        "invalid_balance": {
                            "summary": "잘못된 초기 자산",
                            "value": {
                                "detail": "initial_balance must be greater than 100.0"
                            }
                        },
                        "invalid_fee": {
                            "summary": "잘못된 수수료율",
                            "value": {
                                "detail": "fee_rate must be between 0.0 and 0.01 (0-1%)"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": "❌ 데이터 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "no_data": {
                            "summary": "데이터 없음",
                            "value": {
                                "detail": "No data available for BTC-USDT-SWAP on 5m timeframe for the specified period"
                            }
                        },
                        "insufficient_data": {
                            "summary": "데이터 부족",
                            "value": {
                                "detail": "Insufficient data: Only 50 candles found, minimum 100 required"
                            }
                        },
                        "symbol_not_found": {
                            "summary": "심볼 찾을 수 없음",
                            "value": {
                                "detail": "Symbol INVALID-USDT-SWAP not found in database"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "🚨 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "execution_error": {
                            "summary": "백테스트 실행 실패",
                            "value": {
                                "detail": "Backtest execution failed: Strategy execution error"
                            }
                        },
                        "database_error": {
                            "summary": "데이터베이스 오류",
                            "value": {
                                "detail": "Backtest execution failed: Database connection lost"
                            }
                        },
                        "calculation_error": {
                            "summary": "계산 오류",
                            "value": {
                                "detail": "Backtest execution failed: Division by zero in performance metrics"
                            }
                        },
                        "timeout_error": {
                            "summary": "실행 시간 초과",
                            "value": {
                                "detail": "Backtest execution failed: Timeout after 300 seconds"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def run_backtest(
    request: BacktestRunRequest,
    background_tasks: BackgroundTasks
):
    """
    백테스트 시뮬레이션을 실행합니다.

    이 엔드포인트는 제공된 파라미터로 백테스트를 실행하고,
    거래 내역, 자산 곡선, 성과 지표를 포함한 전체 결과를 반환합니다.
    """
    # Create data provider
    data_provider = TimescaleProvider()

    try:
        logger.info(
            f"Starting backtest: {request.symbol} {request.timeframe} "
            f"from {request.start_date} to {request.end_date}"
        )

        # Create backtest engine
        engine = BacktestEngine(
            data_provider=data_provider,
            initial_balance=request.initial_balance,
            fee_rate=request.fee_rate,
            slippage_percent=request.slippage_percent
        )

        # Create strategy instance based on strategy_name
        if request.strategy_name.lower() == "hyperrsi":
            strategy = HyperrsiStrategy(request.strategy_params)
            strategy.validate_params()
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown strategy: {request.strategy_name}. Supported strategies: hyperrsi"
            )

        # Run backtest
        result = await engine.run(
            user_id=UUID("00000000-0000-0000-0000-000000000000"),  # TODO: Get from auth
            symbol=request.symbol,
            timeframe=request.timeframe,
            start_date=request.start_date,
            end_date=request.end_date,
            strategy_name=request.strategy_name,
            strategy_params=request.strategy_params,
            strategy_executor=strategy
        )

        return BacktestDetailResponse(**result.model_dump())

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"Backtest execution failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Backtest execution failed: {str(e)}"
        )

    finally:
        # Ensure database session is closed
        await data_provider.close()


@router.get(
    "/{backtest_id}",
    response_model=BacktestDetailResponse,
    summary="백테스트 결과 조회 (Coming Soon)",
    description="""
# 백테스트 결과 조회

저장된 백테스트 결과를 ID로 조회합니다.

## 경로 파라미터

- **backtest_id** (UUID, required): 백테스트 고유 ID
  - 형식: UUID v4 (예: 550e8400-e29b-41d4-a716-446655440000)
  - POST /run 실행 시 반환된 ID 사용

## 동작 방식 (구현 예정)

1. **ID 검증**: UUID 형식 및 유효성 확인
2. **데이터베이스 조회**: TimescaleDB/PostgreSQL에서 백테스트 결과 조회
3. **거래 내역 로드**: 백테스트에 포함된 모든 거래 상세 정보 조회
4. **자산 곡선 로드**: 시간별 자산 변화 데이터 조회
5. **완전한 결과 반환**: 메타데이터, 성과 지표, 거래 내역, 자산 곡선 포함

## 예상 반환 정보 (BacktestDetailResponse)

### 메타데이터
- **id**: 백테스트 고유 ID
- **created_at**: 백테스트 실행 시각
- **symbol**: 거래 심볼
- **timeframe**: 시간 프레임
- **strategy_name**: 전략 이름
- **strategy_params**: 전략 파라미터

### 성과 지표
- **final_balance**: 최종 자산
- **total_return_percent**: 총 수익률
- **sharpe_ratio**: 샤프 비율
- **max_drawdown_percent**: 최대 낙폭
- **win_rate**: 승률
- **profit_factor**: 손익비

### 상세 데이터
- **trades**: 전체 거래 내역 배열
- **equity_curve**: 자산 곡선 데이터
- **execution_time**: 백테스트 실행 시간

## 사용 시나리오

📊 **결과 재조회**: 이전 백테스트 결과 다시 확인
📈 **성과 분석**: 거래 내역 및 자산 곡선 상세 분석
🔍 **비교 분석**: 여러 백테스트 결과 비교
💾 **데이터 내보내기**: 결과 데이터를 외부 도구로 분석

## 구현 상태

🚧 **Coming Soon**: 데이터베이스 통합 작업 진행 중
📅 **예정 기능**:
  - PostgreSQL/TimescaleDB 저장소 구현
  - 백테스트 결과 영구 저장
  - 페이지네이션 지원 (거래 내역)
  - 필터링 및 정렬 옵션
  - 결과 캐싱 (Redis)

## 임시 해결 방법

현재는 POST /run 실행 시 즉시 결과를 받아야 합니다.
저장 기능이 구현되면 이 엔드포인트를 통해 조회할 수 있습니다.

## 예시 요청

```bash
GET /backtest/550e8400-e29b-41d4-a716-446655440000
```
""",
    responses={
        200: {
            "description": "✅ 백테스트 결과 조회 성공 (구현 예정)",
            "content": {
                "application/json": {
                    "examples": {
                        "sample_result": {
                            "summary": "백테스트 결과 예시",
                            "value": {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "created_at": "2025-11-01T10:30:00Z",
                                "symbol": "BTC-USDT-SWAP",
                                "timeframe": "5m",
                                "start_date": "2025-01-01T00:00:00Z",
                                "end_date": "2025-01-31T23:59:59Z",
                                "strategy_name": "hyperrsi",
                                "final_balance": 12500.0,
                                "total_return_percent": 25.0,
                                "sharpe_ratio": 1.8,
                                "max_drawdown_percent": -8.5,
                                "total_trades": 45,
                                "win_rate": 66.67,
                                "execution_time": 12.5
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": "❌ 백테스트 결과를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found": {
                            "summary": "결과 없음",
                            "value": {
                                "detail": "Backtest not found"
                            }
                        },
                        "invalid_id": {
                            "summary": "잘못된 ID",
                            "value": {
                                "detail": "Invalid backtest ID format"
                            }
                        }
                    }
                }
            }
        },
        501: {
            "description": "🚧 구현되지 않음 (Coming Soon)",
            "content": {
                "application/json": {
                    "examples": {
                        "not_implemented": {
                            "summary": "기능 구현 중",
                            "value": {
                                "detail": "Result retrieval not yet implemented. Database integration pending."
                            }
                        }
                    }
                }
            }
        }
    }
)
async def get_backtest_result(backtest_id: UUID):
    """
    ID로 저장된 백테스트 결과를 조회합니다.

    모든 거래, 자산 곡선, 성과 지표를 포함한 완전한 백테스트 결과를 반환합니다.

    **구현 예정**: 데이터베이스 통합 작업 진행 중입니다.
    """
    try:
        # TODO: Implement database query to fetch backtest result
        raise HTTPException(
            status_code=501,
            detail="Result retrieval not yet implemented. Database integration pending."
        )

    except Exception as e:
        logger.error(f"Failed to retrieve backtest result: {e}")
        raise HTTPException(status_code=404, detail="Backtest not found")


@router.delete(
    "/{backtest_id}",
    summary="백테스트 결과 삭제 (Coming Soon)",
    description="""
# 백테스트 결과 삭제

저장된 백테스트 결과를 영구적으로 삭제합니다.

## 경로 파라미터

- **backtest_id** (UUID, required): 백테스트 고유 ID
  - 형식: UUID v4 (예: 550e8400-e29b-41d4-a716-446655440000)
  - 삭제할 백테스트의 ID

## 동작 방식 (구현 예정)

1. **ID 검증**: UUID 형식 및 유효성 확인
2. **존재 여부 확인**: 백테스트가 데이터베이스에 존재하는지 확인
3. **관련 데이터 삭제**: 거래 내역, 자산 곡선 스냅샷 삭제
4. **백테스트 삭제**: 메타데이터 및 성과 지표 삭제
5. **캐시 무효화**: Redis 캐시에서 관련 데이터 제거
6. **삭제 확인 반환**: 성공 메시지 반환

## 삭제 대상 데이터

- **백테스트 메타데이터**: 전략, 파라미터, 실행 정보
- **거래 내역**: 모든 진입/청산 거래 기록
- **자산 곡선**: 시간별 자산 변화 스냅샷
- **성과 지표**: 계산된 모든 성과 지표
- **캐시 데이터**: Redis에 저장된 임시 데이터

## 사용 시나리오

🗑️ **테스트 결과 정리**: 불필요한 백테스트 결과 삭제
💾 **저장 공간 확보**: 오래된 백테스트 결과 정리
🔒 **데이터 관리**: 실패한 백테스트 제거
📊 **결과 재실행**: 이전 결과 삭제 후 새로 실행

## 주의사항

⚠️ **영구 삭제**: 삭제된 데이터는 복구할 수 없습니다
⚠️ **확인 필요**: 중요한 백테스트는 삭제 전 확인
⚠️ **관련 데이터 모두 삭제**: 거래 내역, 자산 곡선 등 모두 삭제됨
⚠️ **CASCADE 삭제**: 외래 키 관계의 모든 데이터 자동 삭제

## 구현 상태

🚧 **Coming Soon**: 데이터베이스 통합 작업 진행 중
📅 **예정 기능**:
  - PostgreSQL/TimescaleDB 저장소 구현
  - CASCADE 삭제 (거래 내역, 스냅샷)
  - 삭제 전 확인 옵션
  - 소프트 삭제 (휴지통) 기능
  - 일괄 삭제 지원

## 임시 해결 방법

현재는 백테스트 결과가 영구 저장되지 않으므로 삭제가 불필요합니다.
저장 기능이 구현되면 이 엔드포인트로 삭제할 수 있습니다.

## 예시 요청

```bash
DELETE /backtest/550e8400-e29b-41d4-a716-446655440000
```
""",
    responses={
        200: {
            "description": "✅ 백테스트 삭제 성공 (구현 예정)",
            "content": {
                "application/json": {
                    "examples": {
                        "delete_success": {
                            "summary": "삭제 성공",
                            "value": {
                                "status": "success",
                                "message": "Backtest deleted successfully",
                                "backtest_id": "550e8400-e29b-41d4-a716-446655440000",
                                "deleted_at": "2025-11-01T10:35:00Z"
                            }
                        }
                    }
                }
            }
        },
        404: {
            "description": "❌ 백테스트를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found": {
                            "summary": "결과 없음",
                            "value": {
                                "detail": "Backtest not found"
                            }
                        },
                        "already_deleted": {
                            "summary": "이미 삭제됨",
                            "value": {
                                "detail": "Backtest has already been deleted"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "🚨 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "데이터베이스 오류",
                            "value": {
                                "detail": "Failed to delete backtest: Database connection lost"
                            }
                        },
                        "constraint_violation": {
                            "summary": "제약 조건 위반",
                            "value": {
                                "detail": "Failed to delete backtest: Foreign key constraint violation"
                            }
                        }
                    }
                }
            }
        },
        501: {
            "description": "🚧 구현되지 않음 (Coming Soon)",
            "content": {
                "application/json": {
                    "examples": {
                        "not_implemented": {
                            "summary": "기능 구현 중",
                            "value": {
                                "detail": "Deletion not yet implemented. Database integration pending."
                            }
                        }
                    }
                }
            }
        }
    }
)
async def delete_backtest(backtest_id: UUID):
    """
    백테스트 결과를 삭제합니다.

    백테스트 및 관련된 모든 거래, 스냅샷을 영구적으로 제거합니다.

    **구현 예정**: 데이터베이스 통합 작업 진행 중입니다.
    """
    try:
        # TODO: Implement database deletion
        raise HTTPException(
            status_code=501,
            detail="Deletion not yet implemented. Database integration pending."
        )

    except Exception as e:
        logger.error(f"Failed to delete backtest: {e}")
        raise HTTPException(status_code=404, detail="Backtest not found")


@router.get(
    "/validate/data",
    summary="데이터 가용성 검증",
    description="""
# 백테스트 데이터 가용성 검증

백테스트 실행 전 TimescaleDB에 충분한 과거 데이터가 존재하는지 확인합니다.

## 쿼리 파라미터

- **symbol** (string, required): 거래 심볼
  - 형식: "BTC-USDT-SWAP", "ETH-USDT-SWAP"
  - OKX 영구선물 형식

- **timeframe** (string, required): 시간 프레임
  - 지원: 1m, 3m, 5m, 15m, 30m, 1h, 4h, 1d
  - 데이터 수집 여부에 따라 가용성 상이

- **start_date** (string, required): 시작 날짜
  - ISO 8601 형식: "2025-01-01T00:00:00Z"
  - 데이터 수집 시작 시점 이후여야 함

- **end_date** (string, required): 종료 날짜
  - ISO 8601 형식: "2025-01-31T23:59:59Z"
  - start_date보다 이후여야 함

## 동작 방식

1. **날짜 파싱**: ISO 8601 형식 날짜를 datetime 객체로 변환
2. **데이터 조회**: TimescaleDB에서 지정 기간의 캔들 데이터 확인
3. **커버리지 계산**: 요청 기간 대비 실제 데이터 존재 비율 계산
4. **검증 결과 반환**: 데이터 가용성, 커버리지, 데이터 소스 정보 제공

## 반환 정보

- **available** (bool): 백테스트 실행 가능 여부
  - true: 충분한 데이터 존재 (커버리지 ≥80%)
  - false: 데이터 부족 또는 없음

- **coverage** (float): 데이터 커버리지 비율
  - 0.0 ~ 1.0 범위 (0% ~ 100%)
  - 요청 기간 대비 실제 데이터 존재 비율

- **data_source** (string): 데이터 소스
  - "timescale": TimescaleDB에서 데이터 조회
  - "cache": Redis 캐시에서 데이터 조회
  - "hybrid": TimescaleDB + Redis 혼합

- **message** (string): 상세 메시지
  - 커버리지 퍼센트 또는 데이터 없음 메시지

## 사용 시나리오

✅ **백테스트 전 검증**: 실행 전 데이터 존재 여부 확인
📊 **데이터 품질 확인**: 커버리지 비율로 데이터 완전성 평가
🔍 **기간 선택 최적화**: 데이터가 충분한 기간 선택
⚡ **실행 시간 예측**: 데이터량 기반 실행 시간 추정

## 주의사항

⚠️ 커버리지 80% 미만 시 백테스트 결과 신뢰도 낮음
⚠️ 데이터 누락 구간이 있을 수 있음 (거래소 점검, 네트워크 오류)
⚠️ 최신 데이터는 수집 지연으로 없을 수 있음
⚠️ 시간 프레임별 데이터 수집 상태가 다를 수 있음

## 예시 요청

```bash
GET /validate/data?symbol=BTC-USDT-SWAP&timeframe=5m&start_date=2025-01-01T00:00:00Z&end_date=2025-01-31T23:59:59Z
```
""",
    responses={
        200: {
            "description": "✅ 검증 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "data_available": {
                            "summary": "데이터 충분",
                            "value": {
                                "available": True,
                                "coverage": 0.98,
                                "data_source": "timescale",
                                "message": "Data coverage: 98.0%"
                            }
                        },
                        "partial_data": {
                            "summary": "데이터 부분적",
                            "value": {
                                "available": True,
                                "coverage": 0.85,
                                "data_source": "timescale",
                                "message": "Data coverage: 85.0%"
                            }
                        },
                        "low_coverage": {
                            "summary": "커버리지 낮음",
                            "value": {
                                "available": False,
                                "coverage": 0.45,
                                "data_source": "timescale",
                                "message": "Data coverage: 45.0%"
                            }
                        },
                        "no_data": {
                            "summary": "데이터 없음",
                            "value": {
                                "available": False,
                                "coverage": 0.0,
                                "data_source": "timescale",
                                "message": "No data available for specified period"
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
                    "examples": {
                        "invalid_date_format": {
                            "summary": "잘못된 날짜 형식",
                            "value": {
                                "detail": "Invalid date format. Use ISO 8601: YYYY-MM-DDTHH:MM:SSZ"
                            }
                        },
                        "invalid_date_range": {
                            "summary": "잘못된 날짜 범위",
                            "value": {
                                "detail": "end_date must be after start_date"
                            }
                        },
                        "invalid_timeframe": {
                            "summary": "지원하지 않는 시간 프레임",
                            "value": {
                                "detail": "Unsupported timeframe: 2m. Supported: 1m, 3m, 5m, 15m, 30m, 1h, 4h, 1d"
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "🚨 서버 오류",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "데이터베이스 연결 오류",
                            "value": {
                                "detail": "Failed to validate data: Database connection failed"
                            }
                        },
                        "query_error": {
                            "summary": "쿼리 실행 오류",
                            "value": {
                                "detail": "Failed to validate data: Query execution timeout"
                            }
                        }
                    }
                }
            }
        }
    }
)
async def validate_data_availability(
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str
):
    """
    백테스트용 데이터 가용성을 검증합니다.

    TimescaleDB에서 지정된 심볼, 시간 프레임, 날짜 범위에 대한
    충분한 과거 데이터가 존재하는지 확인합니다.
    """
    try:
        from datetime import datetime

        start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))

        data_provider = TimescaleProvider()
        validation = await data_provider.validate_data_availability(
            symbol, timeframe, start, end
        )

        return {
            "available": validation["available"],
            "coverage": validation["coverage"],
            "data_source": validation["data_source"],
            "message": (
                f"Data coverage: {validation['coverage']*100:.1f}%"
                if validation["available"]
                else "No data available for specified period"
            )
        }

    except Exception as e:
        logger.error(f"Data validation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to validate data: {str(e)}"
        )
