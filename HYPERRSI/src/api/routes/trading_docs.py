"""
Trading API OpenAPI Documentation
=================================

이 모듈은 trading.py의 OpenAPI 문서화(description, responses)를 분리하여 관리합니다.
코드 가독성과 유지보수성을 높이기 위해 라우터 로직과 문서를 분리했습니다.
"""

# =============================================================================
# /start - 트레이딩 태스크 시작
# =============================================================================

START_TRADING_DESCRIPTION = """
# 트레이딩 태스크 시작

특정 사용자의 자동 트레이딩을 시작합니다. OKX UID 또는 텔레그램 ID를 사용하여 사용자를 식별합니다.

## 요청 본문 (TradingTaskRequest)

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리 숫자) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환 시도
- **symbol** (string, optional): 거래 심볼
  - 형식: "SOL-USDT-SWAP", "BTC-USDT-SWAP" 등
  - 기본값: "SOL-USDT-SWAP"
- **timeframe** (string, optional): 차트 시간 프레임
  - 지원: "1m", "5m", "15m", "1h", "4h"
  - 기본값: "1m"

## 쿼리 파라미터

- **restart** (boolean, optional): 재시작 모드
  - `true`: 실행 중인 태스크가 있어도 강제로 재시작
  - `false`: 이미 실행 중이면 오류 반환 (기본값)

## 동작 방식

1. **사용자 식별**: OKX UID 또는 텔레그램 ID 확인 및 변환
2. **Redis 연결 확인**: Redis 연결 상태 검증 (2초 타임아웃)
3. **API 키 확인**: Redis에서 API 키 조회, 없으면 TimescaleDB에서 가져오기
4. **상태 확인**: 현재 실행 중인 트레이딩 태스크 확인
5. **기존 태스크 처리**: restart=true인 경우 기존 태스크 종료
6. **락/쿨다운 정리**: 트레이딩 관련 Redis 키 초기화
7. **Celery 태스크 시작**: 새로운 트레이딩 사이클 실행
8. **상태 저장**: Redis에 실행 상태 및 태스크 ID 저장

## 반환 정보

- **status** (string): 요청 처리 상태 ("success")
- **message** (string): 결과 메시지
- **task_id** (string): Celery 태스크 ID
  - 형식: UUID 형식의 고유 식별자
  - 태스크 추적 및 취소에 사용

## 사용 시나리오

-  **최초 트레이딩 시작**: 사용자의 첫 트레이딩 봇 가동
-  **재시작**: 서버 재시작 후 트레이딩 봇 복구
- ⚙️ **설정 변경**: 심볼 또는 타임프레임 변경 시 재시작
-  **문제 해결**: 오류 상태에서 정상 상태로 복구

## 보안 및 검증

- **Redis 연결 확인**: 2초 타임아웃으로 연결 상태 검증
- **API 키 암호화**: AES-256으로 암호화된 API 키 사용
- **중복 실행 방지**: 이미 실행 중이면 오류 반환 (restart=false)
- **에러 핸들링**: 모든 단계에서 에러 로깅 및 텔레그램 알림

## 예시 요청

```bash
curl -X POST "http://localhost:8000/trading/start?restart=false" \\
     -H "Content-Type: application/json" \\
     -d '{
           "user_id": "518796558012178692",
           "symbol": "SOL-USDT-SWAP",
           "timeframe": "1m"
         }'
```
"""

START_TRADING_RESPONSES = {
    200: {
        "description": " 트레이딩 태스크 시작 성공",
        "content": {
            "application/json": {
                "examples": {
                    "success": {
                        "summary": "트레이딩 시작 성공",
                        "value": {
                            "status": "success",
                            "message": "트레이딩 태스크가 시작되었습니다.",
                            "task_id": "abc123-def456-ghi789-jkl012"
                        }
                    },
                    "restart_success": {
                        "summary": "재시작 성공",
                        "value": {
                            "status": "success",
                            "message": "트레이딩 태스크가 시작되었습니다.",
                            "task_id": "xyz789-uvw456-rst123-opq098"
                        }
                    }
                }
            }
        }
    },
    400: {
        "description": " 잘못된 요청 - 이미 실행 중",
        "content": {
            "application/json": {
                "examples": {
                    "already_running": {
                        "summary": "이미 실행 중",
                        "value": {
                            "detail": "이미 트레이딩 태스크가 실행 중입니다."
                        }
                    },
                    "invalid_symbol": {
                        "summary": "잘못된 심볼",
                        "value": {
                            "detail": "Invalid symbol format"
                        }
                    }
                }
            }
        }
    },
    403: {
        "description": " 권한 없음 - 허용되지 않은 사용자",
        "content": {
            "application/json": {
                "examples": {
                    "unauthorized": {
                        "summary": "권한 없음",
                        "value": {
                            "detail": "권한이 없는 사용자입니다."
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
                    "redis_error": {
                        "summary": "Redis 연결 실패",
                        "value": {
                            "detail": "Redis 연결 오류: Connection refused"
                        }
                    },
                    "redis_timeout": {
                        "summary": "Redis 타임아웃",
                        "value": {
                            "detail": "Redis 연결 시간 초과"
                        }
                    },
                    "task_start_error": {
                        "summary": "태스크 시작 실패",
                        "value": {
                            "detail": "트레이딩 태스크 시작 실패: Celery worker not available"
                        }
                    },
                    "api_key_error": {
                        "summary": "API 키 오류",
                        "value": {
                            "detail": "트레이딩 시작 실패: API key not found"
                        }
                    }
                }
            }
        }
    }
}


# =============================================================================
# /start_all_users - 모든 사용자 재시작
# =============================================================================

START_ALL_USERS_DESCRIPTION = """
서버 재시작 등으로 다운 후, 기존에 실행 중이던 모든 사용자의 트레이딩 태스크를 재시작합니다 (OKX UID 기준).

멀티심볼 모드에서는 각 사용자의 모든 활성 심볼을 재시작합니다.
"""

START_ALL_USERS_RESPONSES = {
    200: {
        "description": "모든 실행 중인 트레이딩 태스크 재시작 성공",
        "content": {
            "application/json": {
                "example": {
                    "status": "success",
                    "message": "모든 실행 중인 트레이딩 태스크에 재시작 명령을 보냈습니다.",
                    "restarted_users": [
                        {"okx_uid": "UID1", "task_id": "new_task_id_1"},
                        {"okx_uid": "UID2", "task_id": "new_task_id_2"}
                    ],
                    "multi_symbol_mode": True
                }
            }
        }
    },
    500: {"description": "트레이딩 태스크 재시작 실패"}
}


# =============================================================================
# /stop - 트레이딩 태스크 중지
# =============================================================================

STOP_TRADING_DESCRIPTION = """
# 트레이딩 태스크 중지

특정 사용자의 자동 트레이딩을 안전하게 중지합니다. 실행 중인 Celery 태스크를 종료하고 관련 Redis 상태를 정리합니다.

## 요청 방식

**쿼리 파라미터** 또는 **JSON 본문** 중 하나를 사용:

### 방법 1: 쿼리 파라미터
- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리 숫자) 또는 텔레그램 ID

### 방법 2: JSON 본문
- **okx_uid** (string, required): OKX UID

## 동작 방식

1. **사용자 식별**: OKX UID 또는 텔레그램 ID 확인 및 변환
2. **상태 확인**: 현재 트레이딩 상태 조회 (running 여부)
3. **종료 신호 설정**: Redis에 stop_signal 설정
4. **Celery 태스크 취소**: 실행 중인 태스크 종료 (SIGTERM)
5. **락/쿨다운 해제**: 트레이딩 관련 Redis 키 삭제
6. **열린 주문 취소** (선택): 활성 주문 취소 시도
7. **상태 정리**: Redis 상태를 'stopped'로 변경
8. **텔레그램 알림**: 사용자에게 중지 메시지 전송

## 정리되는 Redis 키

- `user:{okx_uid}:symbol:{symbol}:status` → "stopped" (심볼별 상태)
- `user:{okx_uid}:symbol:{symbol}:task_id` → 삭제
- `user:{okx_uid}:stop_signal` → 삭제
- `user:{okx_uid}:task_running` → 삭제
- `user:{okx_uid}:cooldown:{symbol}:long` → 삭제
- `user:{okx_uid}:cooldown:{symbol}:short` → 삭제
- `lock:user:{okx_uid}:{symbol}:{timeframe}` → 삭제

## 반환 정보

- **status** (string): 요청 처리 상태 ("success")
- **message** (string): 결과 메시지
  - "트레이딩 중지 신호가 보내졌습니다. 잠시 후 중지됩니다."
  - "트레이딩이 이미 중지되어 있습니다."

## 사용 시나리오

-  **수동 중지**: 사용자가 트레이딩을 직접 중지
-  **비상 중지**: 시장 급변 시 긴급 중지
-  **유지보수**: 설정 변경 또는 업데이트를 위한 중지
-  **전략 변경**: 새로운 전략 적용을 위한 중지
-  **손실 제한**: 일정 손실 도달 시 자동 중지

## 예시 요청

### 쿼리 파라미터 방식
```bash
curl -X POST "http://localhost:8000/trading/stop?user_id=518796558012178692"
```

### JSON 본문 방식
```bash
curl -X POST "http://localhost:8000/trading/stop" \\
     -H "Content-Type: application/json" \\
     -d '{"okx_uid": "518796558012178692"}'
```
"""

STOP_TRADING_RESPONSES = {
    200: {
        "description": " 트레이딩 태스크 중지 성공",
        "content": {
            "application/json": {
                "examples": {
                    "stop_success": {
                        "summary": "중지 성공",
                        "value": {
                            "status": "success",
                            "message": "트레이딩 중지 신호가 보내졌습니다. 잠시 후 중지됩니다."
                        }
                    },
                    "already_stopped": {
                        "summary": "이미 중지됨",
                        "value": {
                            "status": "success",
                            "message": "트레이딩이 이미 중지되어 있습니다."
                        }
                    }
                }
            }
        }
    },
    400: {
        "description": " 잘못된 요청 - 필수 파라미터 누락",
        "content": {
            "application/json": {
                "examples": {
                    "missing_user_id": {
                        "summary": "사용자 ID 누락",
                        "value": {
                            "detail": "user_id 또는 okx_uid가 필요합니다."
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
                        "summary": "존재하지 않는 사용자",
                        "value": {
                            "detail": "User not found"
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
                    "redis_error": {
                        "summary": "Redis 연결 실패",
                        "value": {
                            "detail": "Redis 연결 오류: Connection refused"
                        }
                    },
                    "task_cancel_error": {
                        "summary": "태스크 취소 실패",
                        "value": {
                            "detail": "트레이딩 중지 실패: Failed to cancel task"
                        }
                    },
                    "cleanup_error": {
                        "summary": "상태 정리 실패",
                        "value": {
                            "detail": "트레이딩 중지 실패: Cleanup operation failed"
                        }
                    }
                }
            }
        }
    }
}


# =============================================================================
# /active_symbols/{okx_uid} - 활성 심볼 목록 조회
# =============================================================================

GET_ACTIVE_SYMBOLS_DESCRIPTION = """
# 활성 심볼 목록 조회

멀티심볼 모드에서 특정 사용자가 현재 트레이딩 중인 모든 심볼 목록과 상세 정보를 조회합니다.

## 반환 정보

- **okx_uid**: 사용자 OKX UID
- **multi_symbol_enabled**: 멀티심볼 모드 활성화 여부
- **max_symbols**: 최대 동시 트레이딩 가능 심볼 수
- **active_count**: 현재 활성 심볼 수
- **remaining_slots**: 추가 가능한 심볼 슬롯 수
- **symbols**: 활성 심볼 상세 정보 배열
"""

GET_ACTIVE_SYMBOLS_RESPONSES = {
    200: {
        "description": "활성 심볼 목록 조회 성공",
        "content": {
            "application/json": {
                "example": {
                    "okx_uid": "518796558012178692",
                    "multi_symbol_enabled": True,
                    "max_symbols": 3,
                    "active_count": 2,
                    "remaining_slots": 1,
                    "symbols": [
                        {
                            "symbol": "BTC-USDT-SWAP",
                            "timeframe": "1m",
                            "status": "running",
                            "preset_id": "a1b2c3d4",
                            "started_at": "1700000000.0"
                        },
                        {
                            "symbol": "ETH-USDT-SWAP",
                            "timeframe": "5m",
                            "status": "running",
                            "preset_id": None,
                            "started_at": "1700001000.0"
                        }
                    ]
                }
            }
        }
    }
}


# =============================================================================
# /running_users - 실행 중인 모든 사용자 조회
# =============================================================================

GET_RUNNING_USERS_DESCRIPTION = """
# 실행 중인 모든 사용자 조회

Redis에서 트레이딩 상태가 'running'인 모든 사용자의 OKX UID 목록을 조회합니다.

## 동작 방식

1. **Redis 패턴 매칭**: `user:*:symbol:*:status` 패턴으로 모든 심볼별 상태 키 조회
2. **상태 필터링**: 값이 'running'인 키만 선택
3. **UID 추출**: 키에서 OKX UID 파싱
4. **목록 반환**: 실행 중인 사용자 UID 배열 반환

## 반환 정보

- **status** (string): 요청 처리 상태 ("success")
- **running_users** (array of string): 실행 중인 사용자 OKX UID 목록
  - 빈 배열: 실행 중인 사용자 없음
  - 각 요소: 18자리 OKX UID

## 사용 시나리오

-  **시스템 모니터링**: 전체 활성 사용자 수 파악
-  **일괄 재시작**: 서버 재시작 시 복구할 사용자 목록 확인
-  **일괄 중지**: 긴급 상황 시 중지할 사용자 식별
-  **통계 분석**: 활성 사용자 통계 집계
-  **관리자 도구**: 관리자 대시보드에 활성 사용자 표시

## 예시 URL

```
GET /trading/running_users
```
"""

GET_RUNNING_USERS_RESPONSES = {
    200: {
        "description": " 실행 중인 사용자 조회 성공",
        "content": {
            "application/json": {
                "examples": {
                    "multiple_users": {
                        "summary": "여러 사용자 실행 중",
                        "value": {
                            "status": "success",
                            "running_users": [
                                "518796558012178692",
                                "549641376070615063",
                                "587662504768345929"
                            ]
                        }
                    },
                    "single_user": {
                        "summary": "단일 사용자 실행 중",
                        "value": {
                            "status": "success",
                            "running_users": [
                                "518796558012178692"
                            ]
                        }
                    },
                    "no_users": {
                        "summary": "실행 중인 사용자 없음",
                        "value": {
                            "status": "success",
                            "running_users": []
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
                    "redis_error": {
                        "summary": "Redis 연결 실패",
                        "value": {
                            "detail": "Redis 연결 실패"
                        }
                    },
                    "query_error": {
                        "summary": "데이터 조회 실패",
                        "value": {
                            "detail": "running_users 조회 실패: Query failed"
                        }
                    }
                }
            }
        }
    }
}


# =============================================================================
# /stop_all_running_users - 모든 실행 중인 사용자 중지
# =============================================================================

STOP_ALL_RUNNING_USERS_DESCRIPTION = "Redis에서 'running' 상태인 모든 OKX UID의 트레이딩을 중지합니다."


# =============================================================================
# /restart_all_running_users - 모든 실행 중인 사용자 재시작
# =============================================================================

RESTART_ALL_RUNNING_USERS_DESCRIPTION = "Redis에서 'running' 상태인 모든 OKX UID를 찾아, 기존 태스크 종료 후 restart=true로 다시 시작시킵니다."


# =============================================================================
# /status/{okx_uid} - 특정 사용자의 트레이딩 상태 조회
# =============================================================================

GET_USER_STATUS_DESCRIPTION = """
# 특정 사용자의 트레이딩 상태 조회

특정 사용자의 트레이딩 상태 및 관련 정보를 종합적으로 조회합니다.

## URL 파라미터

- **okx_uid** (string, required): OKX UID
  - 형식: 18자리 숫자 (예: "518796558012178692")

## 반환 정보

### 기본 정보
- **trading_status** (string): 트레이딩 상태
  - `running`: 실행 중
  - `stopped`: 중지됨
  - `error`: 오류 발생
  - `restarting`: 재시작 중
  - `not_found`: 정보 없음

### 태스크 정보
- **task_id** (string, optional): Celery 태스크 ID
  - 형식: UUID 형식
  - 실행 중인 태스크의 고유 식별자

### 사용자 설정 (preferences)
- **symbol** (string): 거래 심볼
- **timeframe** (string): 차트 시간 프레임

### 포지션 정보 (position_info)
- **main_direction** (string): 주 포지션 방향
  - `long`: 롱 포지션
  - `short`: 숏 포지션
- **position_state** (string): 포지션 상태
  - `in_position`: 포지션 보유 중
  - `no_position`: 포지션 없음
  - `closing`: 청산 중

### 기타 정보
- **stop_signal** (string, optional): 중지 신호 여부
  - `true`: 중지 신호 활성

## 사용 시나리오

-  **상태 모니터링**: 실시간 트레이딩 상태 확인
-  **디버깅**: 트레이딩 문제 분석 및 해결
-  **대시보드**: 사용자 대시보드에 상태 표시
- ⚙️ **설정 확인**: 현재 적용된 심볼/타임프레임 확인
- 💼 **포지션 추적**: 현재 보유 포지션 현황 파악

## 예시 URL

```
GET /trading/status/518796558012178692
```
"""

GET_USER_STATUS_RESPONSES = {
    200: {
        "description": " 트레이딩 상태 조회 성공",
        "content": {
            "application/json": {
                "examples": {
                    "running_with_position": {
                        "summary": "실행 중 (포지션 보유)",
                        "value": {
                            "status": "success",
                            "data": {
                                "trading_status": "running",
                                "symbol": "SOL-USDT-SWAP",
                                "timeframe": "1m",
                                "task_id": "abc123-def456-ghi789-jkl012",
                                "preferences": {
                                    "symbol": "SOL-USDT-SWAP",
                                    "timeframe": "1m"
                                },
                                "position_info": {
                                    "main_direction": "long",
                                    "position_state": "in_position"
                                }
                            }
                        }
                    },
                    "stopped": {
                        "summary": "중지됨",
                        "value": {
                            "status": "success",
                            "data": {
                                "trading_status": "stopped",
                                "symbol": "BTC-USDT-SWAP",
                                "timeframe": "5m",
                                "preferences": {
                                    "symbol": "BTC-USDT-SWAP",
                                    "timeframe": "5m"
                                }
                            }
                        }
                    },
                    "not_found": {
                        "summary": "정보 없음",
                        "value": {
                            "status": "success",
                            "data": {
                                "trading_status": "not_found",
                                "message": "사용자의 트레이딩 정보가 없습니다."
                            }
                        }
                    }
                }
            }
        }
    },
    404: {
        "description": " 사용자 정보를 찾을 수 없음",
        "content": {
            "application/json": {
                "examples": {
                    "user_not_found": {
                        "summary": "존재하지 않는 사용자",
                        "value": {
                            "detail": "User not found"
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
                    "redis_error": {
                        "summary": "Redis 연결 실패",
                        "value": {
                            "detail": "Redis 연결 실패"
                        }
                    },
                    "query_error": {
                        "summary": "데이터 조회 실패",
                        "value": {
                            "detail": "트레이딩 상태 조회 실패: Query failed"
                        }
                    }
                }
            }
        }
    }
}


# =============================================================================
# /status/{okx_uid}/{symbol} - 특정 심볼 상태 조회
# =============================================================================

GET_USER_SYMBOL_STATUS_DESCRIPTION = "특정 사용자의 특정 심볼에 대한 트레이딩 상태 및 관련 정보를 상세하게 조회합니다 (OKX UID 기준)."

GET_USER_SYMBOL_STATUS_RESPONSES = {
    200: {
        "description": "심볼별 트레이딩 상태 조회 성공",
        "content": {
            "application/json": {
                "example": {
                    "status": "success",
                    "data": {
                        "symbol": "SOL-USDT-SWAP",
                        "position_info": {
                            "main_direction": "long",
                            "position_state": "in_position",
                            "long": {
                                "entry_price": "124.56",
                                "size": "0.5"
                            },
                            "short": None,
                            "dca_levels": {
                                "long": ["level1", "level2"],
                                "short": []
                            }
                        }
                    }
                }
            }
        }
    },
    404: {"description": "사용자 또는 심볼 정보를 찾을 수 없음"},
    500: {"description": "서버 오류"}
}
