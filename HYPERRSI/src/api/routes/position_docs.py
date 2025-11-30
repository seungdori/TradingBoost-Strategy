"""
Position API OpenAPI Documentation
===================================

이 모듈은 position.py의 OpenAPI 문서화(description, responses)를 분리하여 관리합니다.
코드 가독성과 유지보수성을 높이기 위해 라우터 로직과 문서를 분리했습니다.
"""

# ==========================================
# GET /{user_id} - fetch_okx_position
# ==========================================

FETCH_OKX_POSITION_DESCRIPTION = """
# OKX 포지션 조회

특정 사용자의 OKX 포지션 정보를 조회하고 Redis에 자동으로 동기화합니다.

## URL 파라미터

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환

## 쿼리 파라미터

- **symbol** (string, optional): 거래 심볼
  - 형식: "BTC-USDT-SWAP", "ETH-USDT-SWAP" 등
  - 미지정 시: 모든 활성 포지션 조회
  - 지정 시: 해당 심볼만 조회

## 동작 방식

1. **사용자 인증**: Redis에서 API 키 조회
2. **OKX API 호출**: CCXT를 통한 포지션 정보 조회
3. **데이터 검증**: 유효한 포지션 필터링 및 기본값 설정
4. **Redis 동기화**: 포지션 정보를 Redis에 저장
   - 롱/숏 포지션 정보 개별 저장
   - 포지션 상태(position_state) 업데이트
   - 청산된 포지션 자동 삭제
5. **응답 반환**: 포지션 목록 및 메타데이터

## 반환 정보 (ApiResponse)

- **timestamp** (string): 조회 시간 (UTC)
- **logger** (string): 로거 이름
- **message** (string): 결과 메시지
- **data** (array): 포지션 정보 배열
  - **symbol** (string): 거래 심볼
  - **side** (string): 포지션 방향 (long/short)
  - **entryPrice** (float): 평균 진입가
  - **markPrice** (float): 현재 마크 가격
  - **liquidationPrice** (float): 청산 가격
  - **leverage** (float): 레버리지
  - **contracts** (float): 계약 수량
  - **notional** (float): 명목가치 (USDT)
  - **unrealizedPnl** (float): 미실현 손익
  - **percentage** (float): 손익률 (%)
- **position_qty** (float): 총 포지션 수

## Redis 키 구조

포지션 정보는 다음 Redis 키에 저장됩니다:
- `user:{okx_uid}:position:{symbol}:long` - 롱 포지션 정보
- `user:{okx_uid}:position:{symbol}:short` - 숏 포지션 정보
- `user:{okx_uid}:position:{symbol}:position_state` - 포지션 상태

## 사용 시나리오

- 📊 **실시간 모니터링**: 대시보드에 포지션 현황 표시
- 💰 **손익 계산**: 미실현 손익 및 손익률 확인
- ⚠️ **리스크 관리**: 청산가 대비 현재가 모니터링
- 🔄 **자동 동기화**: Redis 상태와 실제 포지션 동기화
- 📈 **통계 분석**: 포지션 히스토리 및 성과 분석

## 예시 URL

```
GET /position/518796558012178692
GET /position/518796558012178692?symbol=BTC-USDT-SWAP
GET /position/1709556958?symbol=ETH-USDT-SWAP
```
"""

FETCH_OKX_POSITION_RESPONSES = {
    200: {
        "description": "✅ 포지션 조회 성공",
        "content": {
            "application/json": {
                "examples": {
                    "with_positions": {
                        "summary": "포지션 보유 중",
                        "value": {
                            "timestamp": "2025-01-12T16:30:00",
                            "logger": "root",
                            "message": "OKX 포지션 조회 결과",
                            "data": [
                                {
                                    "symbol": "BTC-USDT-SWAP",
                                    "side": "long",
                                    "entryPrice": 45000.0,
                                    "markPrice": 45500.0,
                                    "liquidationPrice": 43000.0,
                                    "leverage": 10.0,
                                    "contracts": 0.1,
                                    "notional": 4550.0,
                                    "unrealizedPnl": 50.0,
                                    "percentage": 1.11
                                }
                            ],
                            "position_qty": 1.0
                        }
                    },
                    "no_positions": {
                        "summary": "포지션 없음",
                        "value": {
                            "timestamp": "2025-01-12T16:30:00",
                            "logger": "root",
                            "message": "포지션이 없습니다",
                            "data": [],
                            "position_qty": 0.0
                        }
                    },
                    "multiple_positions": {
                        "summary": "여러 포지션",
                        "value": {
                            "timestamp": "2025-01-12T16:30:00",
                            "logger": "root",
                            "message": "OKX 포지션 조회 결과",
                            "data": [
                                {
                                    "symbol": "BTC-USDT-SWAP",
                                    "side": "long",
                                    "entryPrice": 45000.0,
                                    "unrealizedPnl": 50.0
                                },
                                {
                                    "symbol": "ETH-USDT-SWAP",
                                    "side": "short",
                                    "entryPrice": 2500.0,
                                    "unrealizedPnl": -10.0
                                }
                            ],
                            "position_qty": 2.0
                        }
                    }
                }
            }
        }
    },
    404: {
        "description": "❌ API 키를 찾을 수 없음",
        "content": {
            "application/json": {
                "examples": {
                    "api_keys_not_found": {
                        "summary": "API 키 없음",
                        "value": {
                            "detail": "API keys not found in Redis"
                        }
                    }
                }
            }
        }
    },
    500: {
        "description": "❌ 서버 오류",
        "content": {
            "application/json": {
                "examples": {
                    "fetch_error": {
                        "summary": "포지션 조회 실패",
                        "value": {
                            "detail": "Error fetching position: Connection timeout"
                        }
                    },
                    "api_key_error": {
                        "summary": "API 키 조회 오류",
                        "value": {
                            "detail": "Error fetching API keys: Redis connection failed"
                        }
                    }
                }
            }
        }
    }
}


# ==========================================
# POST /{user_id}/{symbol}/leverage - set_position_leverage
# ==========================================

SET_POSITION_LEVERAGE_DESCRIPTION = """
# 포지션 레버리지 설정

특정 심볼의 레버리지를 변경하고 마진 모드(cross/isolated)를 설정합니다.

## URL 파라미터

- **user_id** (string, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환
- **symbol** (string, required): 거래 심볼
  - 형식: "BTC-USDT-SWAP", "ETH-USDT-SWAP" 등
  - 반드시 SWAP(무기한 선물) 거래쌍이어야 함

## 요청 본문 (LeverageRequest)

- **leverage** (float, required): 설정할 레버리지 값
  - 범위: 1 ~ 125
  - OKX 거래소 기준, 심볼별로 최대 레버리지가 다를 수 있음
  - 기본값: 10
- **marginMode** (string, required): 마진 모드
  - "cross": 교차 마진 (전체 계좌 잔고 사용)
  - "isolated": 격리 마진 (포지션별 독립된 마진)
  - 기본값: "cross"
- **posSide** (string, optional): 포지션 방향
  - "long": 롱 포지션
  - "short": 숏 포지션
  - "net": 단방향 포지션 (cross 모드에서만 사용)
  - isolated 모드에서는 필수 입력
  - 기본값: "long"

## 마진 모드 설명

### Cross Margin (교차 마진)
- 전체 계좌 잔고를 마진으로 사용
- 포지션 간 마진 공유로 청산 리스크 감소
- 한 포지션 청산 시 전체 계좌에 영향

### Isolated Margin (격리 마진)
- 포지션별로 독립된 마진 할당
- 포지션별 리스크 격리
- 한 포지션 청산이 다른 포지션에 영향 없음

## 동작 방식

1. **사용자 인증**: Redis에서 API 키 조회
2. **CCXT 클라이언트 생성**: OKX API 접근 준비
3. **마켓 정보 로드**: 심볼 유효성 검증
4. **레버리지 변경**: OKX API를 통한 레버리지 설정
5. **응답 반환**: 설정 결과 및 메타데이터

## 반환 정보 (LeverageResponse)

- **timestamp** (string): 설정 완료 시간 (UTC)
- **message** (string): 결과 메시지
- **symbol** (string): 거래 심볼
- **leverage** (float): 설정된 레버리지
- **marginMode** (string): 설정된 마진 모드
- **posSide** (string): 설정된 포지션 방향
- **status** (string): 처리 상태 ("success" 또는 "failed")

## 사용 시나리오

- 🎯 **레버리지 조정**: 시장 변동성에 따라 레버리지 조절
- ⚠️ **리스크 관리**: 높은 변동성 구간에서 레버리지 낮춤
- 📊 **전략 최적화**: 전략별 최적 레버리지 설정
- 🔄 **마진 모드 전환**: cross ↔ isolated 전환
- 💼 **포트폴리오 관리**: 심볼별 레버리지 차별화

## 주의사항

- 레버리지 변경은 기존 포지션에도 즉시 적용됩니다
- 마진 모드 변경 시 기존 오픈 오더가 취소될 수 있습니다
- 최대 레버리지는 심볼과 계정 등급에 따라 다릅니다
- 레버리지가 높을수록 청산 리스크가 증가합니다

## 예시 URL

```bash
# Cross Margin 10배 레버리지 설정
POST /position/518796558012178692/BTC-USDT-SWAP/leverage
{
  "leverage": 10,
  "marginMode": "cross"
}

# Isolated Margin 롱 포지션 20배 레버리지 설정
POST /position/1709556958/ETH-USDT-SWAP/leverage
{
  "leverage": 20,
  "marginMode": "isolated",
  "posSide": "long"
}

# 보수적 레버리지 5배 설정
POST /position/518796558012178692/SOL-USDT-SWAP/leverage
{
  "leverage": 5,
  "marginMode": "cross"
}
```
"""

SET_POSITION_LEVERAGE_RESPONSES = {
    200: {
        "description": "✅ 레버리지 설정 성공",
        "content": {
            "application/json": {
                "examples": {
                    "cross_margin_success": {
                        "summary": "교차 마진 레버리지 설정 성공",
                        "value": {
                            "timestamp": "2025-01-12T16:45:00",
                            "message": "레버리지 설정이 완료되었습니다",
                            "symbol": "BTC-USDT-SWAP",
                            "leverage": 10.0,
                            "marginMode": "cross",
                            "posSide": "net",
                            "status": "success"
                        }
                    },
                    "isolated_long_success": {
                        "summary": "격리 마진 롱 포지션 레버리지 설정",
                        "value": {
                            "timestamp": "2025-01-12T16:50:00",
                            "message": "레버리지 설정이 완료되었습니다",
                            "symbol": "ETH-USDT-SWAP",
                            "leverage": 20.0,
                            "marginMode": "isolated",
                            "posSide": "long",
                            "status": "success"
                        }
                    },
                    "isolated_short_success": {
                        "summary": "격리 마진 숏 포지션 레버리지 설정",
                        "value": {
                            "timestamp": "2025-01-12T16:55:00",
                            "message": "레버리지 설정이 완료되었습니다",
                            "symbol": "SOL-USDT-SWAP",
                            "leverage": 15.0,
                            "marginMode": "isolated",
                            "posSide": "short",
                            "status": "success"
                        }
                    },
                    "conservative_leverage": {
                        "summary": "보수적 레버리지 설정 (5배)",
                        "value": {
                            "timestamp": "2025-01-12T17:00:00",
                            "message": "레버리지 설정이 완료되었습니다",
                            "symbol": "BTC-USDT-SWAP",
                            "leverage": 5.0,
                            "marginMode": "cross",
                            "posSide": "net",
                            "status": "success"
                        }
                    }
                }
            }
        }
    },
    400: {
        "description": "❌ 잘못된 요청 - 유효성 검증 실패",
        "content": {
            "application/json": {
                "examples": {
                    "invalid_leverage_range": {
                        "summary": "레버리지 범위 초과",
                        "value": {
                            "detail": {
                                "message": "레버리지 설정 실패",
                                "error": "Leverage must be between 1 and 125",
                                "symbol": "BTC-USDT-SWAP"
                            }
                        }
                    },
                    "invalid_margin_mode": {
                        "summary": "잘못된 마진 모드",
                        "value": {
                            "detail": {
                                "message": "레버리지 설정 실패",
                                "error": "marginMode must be either 'cross' or 'isolated'",
                                "symbol": "ETH-USDT-SWAP"
                            }
                        }
                    },
                    "missing_pos_side": {
                        "summary": "격리 마진에서 posSide 누락",
                        "value": {
                            "detail": {
                                "message": "레버리지 설정 실패",
                                "error": "posSide is required for isolated margin mode",
                                "symbol": "SOL-USDT-SWAP"
                            }
                        }
                    },
                    "invalid_symbol": {
                        "summary": "지원하지 않는 심볼",
                        "value": {
                            "detail": {
                                "message": "레버리지 설정 실패",
                                "error": "Symbol not found or not supported",
                                "symbol": "INVALID-USDT-SWAP"
                            }
                        }
                    }
                }
            }
        }
    },
    401: {
        "description": "❌ 인증 실패",
        "content": {
            "application/json": {
                "examples": {
                    "invalid_api_keys": {
                        "summary": "잘못된 API 키",
                        "value": {
                            "detail": {
                                "message": "레버리지 설정 실패",
                                "error": "Invalid API credentials",
                                "symbol": "BTC-USDT-SWAP"
                            }
                        }
                    },
                    "expired_api_keys": {
                        "summary": "만료된 API 키",
                        "value": {
                            "detail": {
                                "message": "레버리지 설정 실패",
                                "error": "API key has expired",
                                "symbol": "ETH-USDT-SWAP"
                            }
                        }
                    }
                }
            }
        }
    },
    404: {
        "description": "❌ 리소스를 찾을 수 없음",
        "content": {
            "application/json": {
                "examples": {
                    "api_keys_not_found": {
                        "summary": "API 키 없음",
                        "value": {
                            "detail": "API keys not found in Redis"
                        }
                    },
                    "user_not_found": {
                        "summary": "사용자 없음",
                        "value": {
                            "detail": {
                                "message": "레버리지 설정 실패",
                                "error": "User not found",
                                "symbol": "BTC-USDT-SWAP"
                            }
                        }
                    }
                }
            }
        }
    },
    429: {
        "description": "⏱️ 요청 속도 제한 초과",
        "content": {
            "application/json": {
                "examples": {
                    "rate_limit_exceeded": {
                        "summary": "API 요청 한도 초과",
                        "value": {
                            "detail": {
                                "message": "레버리지 설정 실패",
                                "error": "Rate limit exceeded. Please try again later.",
                                "symbol": "BTC-USDT-SWAP",
                                "retry_after": 60
                            }
                        }
                    }
                }
            }
        }
    },
    500: {
        "description": "❌ 서버 오류",
        "content": {
            "application/json": {
                "examples": {
                    "exchange_api_error": {
                        "summary": "거래소 API 오류",
                        "value": {
                            "detail": {
                                "message": "레버리지 설정 실패",
                                "error": "OKX API connection failed",
                                "symbol": "BTC-USDT-SWAP"
                            }
                        }
                    },
                    "network_timeout": {
                        "summary": "네트워크 타임아웃",
                        "value": {
                            "detail": {
                                "message": "레버리지 설정 실패",
                                "error": "Request timeout",
                                "symbol": "ETH-USDT-SWAP"
                            }
                        }
                    },
                    "redis_error": {
                        "summary": "Redis 연결 실패",
                        "value": {
                            "detail": "Error fetching API keys: Redis connection failed"
                        }
                    },
                    "ccxt_close_error": {
                        "summary": "CCXT 클라이언트 종료 오류",
                        "value": {
                            "detail": {
                                "message": "레버리지 설정 실패",
                                "error": "Failed to close CCXT client",
                                "symbol": "SOL-USDT-SWAP"
                            }
                        }
                    }
                }
            }
        }
    }
}


# ==========================================
# POST /open - open_position_endpoint
# ==========================================

OPEN_POSITION_DESCRIPTION = """
# 포지션 오픈 (롱/숏)

지정된 심볼에 대해 롱(매수) 또는 숏(매도) 포지션을 오픈하고, 옵션으로 TP(Take Profit)/SL(Stop Loss) 주문을 설정합니다.

## 요청 본문 (OpenPositionRequest)

### 필수 파라미터

- **user_id** (int, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환
- **symbol** (string, required): 거래 심볼
  - 형식: "BTC-USDT-SWAP", "ETH-USDT-SWAP" 등
  - 반드시 SWAP(무기한 선물) 거래쌍
- **direction** (string, required): 포지션 방향
  - "long": 매수 포지션 (가격 상승 예상)
  - "short": 매도 포지션 (가격 하락 예상)
- **size** (float, required): 포지션 크기
  - 기준 화폐 단위 (예: BTC 수량)
  - 최소 주문 수량은 심볼별로 상이

### 선택 파라미터

- **leverage** (float, optional): 레버리지
  - 범위: 1 ~ 125
  - 기본값: 10.0
  - 심볼별 최대 레버리지 제한 적용
- **stop_loss** (float, optional): 손절가
  - 롱: 진입가보다 낮은 가격
  - 숏: 진입가보다 높은 가격
  - 미설정 시 손절 주문 생성 안 함
- **take_profit** (array of float, optional): 이익실현가 목록
  - 여러 TP 레벨 설정 가능
  - 첫 번째 값이 주요 TP로 사용됨
  - 미설정 시 TP 주문 생성 안 함
- **is_DCA** (bool, optional): DCA(Dollar Cost Averaging) 모드
  - True: 기존 포지션에 추가 진입 (평균 단가 조정)
  - False: 신규 포지션 진입
  - 기본값: False
- **is_hedge** (bool, optional): 헤지 포지션 여부
  - True: 반대 방향 포지션으로 헤지
  - False: 일반 포지션
  - 기본값: False
- **hedge_tp_price** (float, optional): 헤지 포지션 TP
- **hedge_sl_price** (float, optional): 헤지 포지션 SL

## 동작 방식

1. **사용자 인증**: Redis/TimescaleDB에서 API 키 조회
2. **TradingService 생성**: CCXT 클라이언트 초기화
3. **파라미터 검증**: direction, size, leverage 유효성 확인
4. **포지션 오픈**: OKX API를 통한 시장가 주문 실행
5. **TP/SL 설정**: take_profit, stop_loss가 있으면 조건부 주문 생성
6. **DCA 처리**: is_DCA=True인 경우 기존 TP/SL 취소 후 재생성
7. **Redis 동기화**: 포지션 정보를 Redis에 저장
8. **응답 반환**: 포지션 생성 결과 및 메타데이터

## 반환 정보 (PositionResponse)

- **symbol** (string): 거래 심볼
- **side** (string): 포지션 방향 (long/short)
- **size** (float): 포지션 크기
- **entry_price** (float): 평균 진입가
- **leverage** (float): 레버리지
- **sl_price** (float): 손절가
- **tp_prices** (array): 이익실현가 목록
- **order_id** (string): 주문 ID
- **last_filled_price** (float): 최종 체결가

## 사용 시나리오

- 📈 **롱 포지션**: 상승 추세 포착, 지지선 반등 매수
- 📉 **숏 포지션**: 하락 추세 포착, 저항선 돌파 실패
- 🎯 **TP/SL 설정**: 리스크 관리 및 자동 청산
- 💰 **DCA 전략**: 가격 하락 시 추가 매수로 평균 단가 낮춤
- 🛡️ **헤지**: 기존 포지션 리스크 헤지

## 주의사항

- 충분한 잔고가 있어야 포지션 오픈 가능
- 레버리지가 높을수록 청산 리스크 증가
- DCA 모드는 기존 포지션이 있을 때만 유효
- TP/SL 가격은 진입가 대비 논리적으로 유효해야 함
- 시장가 주문은 슬리피지가 발생할 수 있음

## 예시 요청

```bash
# 기본 롱 포지션 (TP/SL 포함)
curl -X POST "http://localhost:8000/position/open" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": 1709556958,
    "symbol": "BTC-USDT-SWAP",
    "direction": "long",
    "size": 0.1,
    "leverage": 10,
    "stop_loss": 89520.0,
    "take_profit": [96450.6, 96835.6, 97124.4]
  }'

# DCA 모드 추가 진입
curl -X POST "http://localhost:8000/position/open" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": 1709556958,
    "symbol": "BTC-USDT-SWAP",
    "direction": "long",
    "size": 0.05,
    "is_DCA": true
  }'

# 숏 포지션 (헤지)
curl -X POST "http://localhost:8000/position/open" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": 1709556958,
    "symbol": "ETH-USDT-SWAP",
    "direction": "short",
    "size": 1.0,
    "leverage": 5,
    "is_hedge": true
  }'
```
"""

OPEN_POSITION_RESPONSES = {
    200: {
        "description": "✅ 포지션 생성 성공",
        "content": {
            "application/json": {
                "examples": {
                    "long_position_with_tp_sl": {
                        "summary": "롱 포지션 (TP/SL 포함)",
                        "value": {
                            "symbol": "BTC-USDT-SWAP",
                            "side": "long",
                            "size": 0.1,
                            "entry_price": 92450.5,
                            "leverage": 10.0,
                            "sl_price": 89520.0,
                            "tp_prices": [96450.6, 96835.6, 97124.4],
                            "order_id": "123456789012345678",
                            "last_filled_price": 92450.5
                        }
                    },
                    "short_position_simple": {
                        "summary": "숏 포지션 (기본)",
                        "value": {
                            "symbol": "ETH-USDT-SWAP",
                            "side": "short",
                            "size": 1.0,
                            "entry_price": 2650.3,
                            "leverage": 10.0,
                            "sl_price": 0.0,
                            "tp_prices": [],
                            "order_id": "987654321098765432",
                            "last_filled_price": 2650.3
                        }
                    },
                    "dca_entry": {
                        "summary": "DCA 추가 진입",
                        "value": {
                            "symbol": "BTC-USDT-SWAP",
                            "side": "long",
                            "size": 0.05,
                            "entry_price": 91200.0,
                            "leverage": 10.0,
                            "sl_price": 89000.0,
                            "tp_prices": [95000.0],
                            "order_id": "555666777888999000",
                            "last_filled_price": 91200.0
                        }
                    },
                    "hedge_position": {
                        "summary": "헤지 포지션",
                        "value": {
                            "symbol": "SOL-USDT-SWAP",
                            "side": "short",
                            "size": 10.0,
                            "entry_price": 125.5,
                            "leverage": 5.0,
                            "sl_price": 130.0,
                            "tp_prices": [120.0],
                            "order_id": "111222333444555666",
                            "last_filled_price": 125.5
                        }
                    }
                }
            }
        }
    },
    400: {
        "description": "❌ 잘못된 요청 - 유효성 검증 실패",
        "content": {
            "application/json": {
                "examples": {
                    "insufficient_balance": {
                        "summary": "잔고 부족",
                        "value": {
                            "detail": "주문에 필요한 잔고가 부족합니다. 현재 잔고: 100 USDT, 필요 마진: 150 USDT"
                        }
                    },
                    "invalid_direction": {
                        "summary": "잘못된 포지션 방향",
                        "value": {
                            "detail": "direction must be 'long' or 'short'"
                        }
                    },
                    "invalid_size": {
                        "summary": "잘못된 포지션 크기",
                        "value": {
                            "detail": "주문 수량이 최소 주문 수량(0.01)보다 작습니다"
                        }
                    },
                    "invalid_tp_price": {
                        "summary": "잘못된 TP 가격",
                        "value": {
                            "detail": "롱 포지션의 TP 가격은 진입가보다 높아야 합니다"
                        }
                    },
                    "invalid_sl_price": {
                        "summary": "잘못된 SL 가격",
                        "value": {
                            "detail": "숏 포지션의 SL 가격은 진입가보다 낮아야 합니다"
                        }
                    }
                }
            }
        }
    },
    401: {
        "description": "❌ 인증 실패",
        "content": {
            "application/json": {
                "examples": {
                    "invalid_api_keys": {
                        "summary": "잘못된 API 키",
                        "value": {
                            "detail": "유효하지 않은 API 키입니다"
                        }
                    },
                    "api_permission_denied": {
                        "summary": "API 권한 부족",
                        "value": {
                            "detail": "API 키에 트레이딩 권한이 없습니다"
                        }
                    }
                }
            }
        }
    },
    404: {
        "description": "❌ 리소스를 찾을 수 없음",
        "content": {
            "application/json": {
                "examples": {
                    "user_not_found": {
                        "summary": "사용자 없음",
                        "value": {
                            "detail": "User not found"
                        }
                    },
                    "api_keys_not_found": {
                        "summary": "API 키 없음",
                        "value": {
                            "detail": "API keys not found in Redis"
                        }
                    }
                }
            }
        }
    },
    429: {
        "description": "⏱️ 요청 속도 제한 초과",
        "content": {
            "application/json": {
                "examples": {
                    "rate_limit_exceeded": {
                        "summary": "API 요청 한도 초과",
                        "value": {
                            "detail": "Rate limit exceeded. Please try again later.",
                            "retry_after": 60
                        }
                    }
                }
            }
        }
    },
    500: {
        "description": "❌ 서버 오류",
        "content": {
            "application/json": {
                "examples": {
                    "exchange_api_error": {
                        "summary": "거래소 API 오류",
                        "value": {
                            "detail": "거래소 연결 오류: Connection timeout"
                        }
                    },
                    "order_execution_failed": {
                        "summary": "주문 실행 실패",
                        "value": {
                            "detail": "Order execution failed: Market is closed"
                        }
                    },
                    "trading_service_error": {
                        "summary": "TradingService 오류",
                        "value": {
                            "detail": "Failed to create TradingService for user"
                        }
                    }
                }
            }
        }
    },
    503: {
        "description": "❌ 서비스 이용 불가",
        "content": {
            "application/json": {
                "examples": {
                    "insufficient_funds": {
                        "summary": "자금 부족 (일시적)",
                        "value": {
                            "detail": "자금 부족으로 주문을 실행할 수 없습니다. 잠시 후 다시 시도해주세요.",
                            "retry_after": 300
                        }
                    },
                    "exchange_maintenance": {
                        "summary": "거래소 점검",
                        "value": {
                            "detail": "거래소가 점검 중입니다",
                            "retry_after": 1800
                        }
                    }
                }
            }
        }
    }
}


# ==========================================
# POST /close - close_position_endpoint
# ==========================================

CLOSE_POSITION_DESCRIPTION = """
# 포지션 청산 (전체/부분)

기존 포지션을 전체 또는 부분적으로 청산합니다. 청산 비율 또는 수량을 지정하여 포지션을 종료할 수 있습니다.

## 요청 본문 (ClosePositionRequest)

### 필수 파라미터

- **user_id** (int, required): 사용자 식별자
  - OKX UID (18자리) 또는 텔레그램 ID
  - 텔레그램 ID인 경우 자동으로 OKX UID로 변환
- **symbol** (string, required): 거래 심볼
  - 형식: "BTC-USDT-SWAP", "ETH-USDT-SWAP" 등
  - 청산할 포지션의 심볼과 정확히 일치해야 함

### 선택 파라미터

- **side** (string, optional): 포지션 방향
  - "long": 롱 포지션 청산
  - "short": 숏 포지션 청산
  - 기본값: "long"
  - 미지정 시 TradingService가 자동으로 심볼의 포지션 방향 감지
- **size** (float, optional): 청산할 수량
  - 기준 화폐 단위 (예: BTC 수량)
  - 0 또는 미지정 시 percent 사용
  - size 우선순위가 percent보다 높음
- **percent** (float, optional): 청산 비율
  - 범위: 0 ~ 100
  - 100: 전체 청산
  - 50: 절반 청산
  - size가 지정되지 않은 경우에만 사용됨
- **comment** (string, optional): 청산 사유
  - 로깅 및 추적을 위한 메모
  - 예: "TP 도달", "수동 청산", "리스크 관리"

## 동작 방식

1. **사용자 인증**: Redis/TimescaleDB에서 API 키 조회
2. **TradingService 생성**: CCXT 클라이언트 초기화
3. **포지션 확인**: Redis에서 현재 포지션 상태 조회
4. **청산량 계산**:
   - size 지정: 해당 수량만큼 청산
   - percent 지정: 포지션의 지정 비율만큼 청산
   - 미지정: 전체 포지션 청산
5. **주문 실행**: OKX API를 통한 시장가 청산 주문
6. **Redis 업데이트**: 포지션 상태 동기화
7. **TP/SL 취소**: 청산 완료 시 관련 TP/SL 주문 자동 취소
8. **응답 반환**: 청산 성공 여부 및 메타데이터

## 반환 정보

- **success** (boolean): 청산 성공 여부 (true/false)
- **message** (string): 결과 메시지

## 사용 시나리오

- 💰 **이익 실현**: 목표 수익 달성 시 전체 또는 부분 청산
- 🛡️ **손절**: 손실 확대 방지를 위한 조기 청산
- 📊 **리밸런싱**: 포트폴리오 비율 조정을 위한 부분 청산
- ⚖️ **리스크 관리**: 변동성 증가 시 포지션 축소
- 🔄 **전략 전환**: 시장 상황 변화에 따른 포지션 종료

## 청산 방식 비교

### 전체 청산
- **size**: 미지정 또는 0
- **percent**: 100 또는 미지정
- 포지션 전체를 한 번에 청산

### 부분 청산 (비율)
- **size**: 미지정 또는 0
- **percent**: 1 ~ 99
- 포지션의 일부를 비율로 청산

### 부분 청산 (수량)
- **size**: 청산할 구체적 수량
- **percent**: 무시됨
- 정확한 수량만큼 청산

## 주의사항

- 청산 시 TP/SL 주문이 자동으로 취소됩니다
- 시장가 청산은 슬리피지가 발생할 수 있습니다
- 부분 청산 후 남은 포지션은 유지됩니다
- 포지션이 없는 경우 404 오류 반환
- size와 percent를 동시 지정 시 size가 우선됩니다

## 예시 요청

```bash
# 전체 청산
curl -X POST "http://localhost:8000/position/close" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": 1709556958,
    "symbol": "BTC-USDT-SWAP",
    "side": "long",
    "comment": "목표 수익 달성"
  }'

# 50% 부분 청산
curl -X POST "http://localhost:8000/position/close" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": 1709556958,
    "symbol": "ETH-USDT-SWAP",
    "side": "short",
    "percent": 50,
    "comment": "리스크 감소"
  }'

# 수량 지정 청산
curl -X POST "http://localhost:8000/position/close" \\
  -H "Content-Type: application/json" \\
  -d '{
    "user_id": 1709556958,
    "symbol": "SOL-USDT-SWAP",
    "side": "long",
    "size": 5.0,
    "comment": "부분 이익 실현"
  }'
```
"""

CLOSE_POSITION_RESPONSES = {
    200: {
        "description": "✅ 포지션 청산 성공",
        "content": {
            "application/json": {
                "examples": {
                    "full_close_success": {
                        "summary": "전체 청산 성공",
                        "value": {
                            "success": True,
                            "message": "Position closed successfully."
                        }
                    },
                    "partial_close_percent": {
                        "summary": "50% 부분 청산 성공",
                        "value": {
                            "success": True,
                            "message": "Position closed successfully. (50% closed)"
                        }
                    },
                    "partial_close_size": {
                        "summary": "수량 지정 청산 성공",
                        "value": {
                            "success": True,
                            "message": "Position closed successfully. (0.05 BTC closed)"
                        }
                    }
                }
            }
        }
    },
    400: {
        "description": "❌ 잘못된 요청 - 유효성 검증 실패",
        "content": {
            "application/json": {
                "examples": {
                    "invalid_percent": {
                        "summary": "잘못된 청산 비율",
                        "value": {
                            "detail": "percent must be between 0 and 100"
                        }
                    },
                    "invalid_size": {
                        "summary": "잘못된 청산 수량",
                        "value": {
                            "detail": "청산 수량이 보유 포지션(0.1 BTC)보다 큽니다"
                        }
                    },
                    "invalid_side": {
                        "summary": "잘못된 포지션 방향",
                        "value": {
                            "detail": "side must be 'long' or 'short'"
                        }
                    },
                    "close_order_failed": {
                        "summary": "청산 주문 실패",
                        "value": {
                            "detail": "Failed to execute close order: Insufficient position"
                        }
                    }
                }
            }
        }
    },
    401: {
        "description": "❌ 인증 실패",
        "content": {
            "application/json": {
                "examples": {
                    "invalid_api_keys": {
                        "summary": "잘못된 API 키",
                        "value": {
                            "detail": "유효하지 않은 API 키입니다"
                        }
                    },
                    "api_permission_denied": {
                        "summary": "API 권한 부족",
                        "value": {
                            "detail": "API 키에 트레이딩 권한이 없습니다"
                        }
                    }
                }
            }
        }
    },
    404: {
        "description": "❌ 포지션을 찾을 수 없음",
        "content": {
            "application/json": {
                "examples": {
                    "no_position": {
                        "summary": "활성 포지션 없음",
                        "value": {
                            "detail": "포지션 청산 실패 혹은 활성화된 포지션이 없습니다."
                        }
                    },
                    "user_not_found": {
                        "summary": "사용자 없음",
                        "value": {
                            "detail": "User not found"
                        }
                    },
                    "symbol_not_found": {
                        "summary": "심볼에 포지션 없음",
                        "value": {
                            "detail": "No active position found for symbol BTC-USDT-SWAP"
                        }
                    }
                }
            }
        }
    },
    429: {
        "description": "⏱️ 요청 속도 제한 초과",
        "content": {
            "application/json": {
                "examples": {
                    "rate_limit_exceeded": {
                        "summary": "API 요청 한도 초과",
                        "value": {
                            "detail": "Rate limit exceeded. Please try again later.",
                            "retry_after": 60
                        }
                    }
                }
            }
        }
    },
    500: {
        "description": "❌ 서버 오류",
        "content": {
            "application/json": {
                "examples": {
                    "exchange_api_error": {
                        "summary": "거래소 API 오류",
                        "value": {
                            "detail": "거래소 연결 오류: Connection timeout"
                        }
                    },
                    "redis_sync_error": {
                        "summary": "Redis 동기화 실패",
                        "value": {
                            "detail": "Failed to update position state in Redis"
                        }
                    },
                    "trading_service_error": {
                        "summary": "TradingService 오류",
                        "value": {
                            "detail": "Failed to create TradingService for user"
                        }
                    },
                    "cancel_orders_failed": {
                        "summary": "TP/SL 취소 실패",
                        "value": {
                            "detail": "Position closed but failed to cancel TP/SL orders"
                        }
                    }
                }
            }
        }
    },
    503: {
        "description": "❌ 서비스 이용 불가",
        "content": {
            "application/json": {
                "examples": {
                    "exchange_maintenance": {
                        "summary": "거래소 점검",
                        "value": {
                            "detail": "거래소가 점검 중입니다",
                            "retry_after": 1800
                        }
                    },
                    "market_closed": {
                        "summary": "시장 종료",
                        "value": {
                            "detail": "Market is currently closed"
                        }
                    }
                }
            }
        }
    }
}


# ==========================================
# GET /{user_id}/{symbol}/detail - get_position_detail
# ==========================================

GET_POSITION_DETAIL_DESCRIPTION = """
# 포지션 상세 정보 조회

특정 사용자의 특정 심볼에 대한 포지션 상세 정보를 조회합니다.
TP(Take Profit), SL(Stop Loss), Trailing Stop, DCA 정보를 한 번에 확인할 수 있습니다.

## URL 파라미터

- **user_id** (string, required): 사용자 식별자 (OKX UID 또는 텔레그램 ID)
- **symbol** (string, required): 거래 심볼 (예: BTC-USDT-SWAP)

## 반환 정보

### position (포지션 정보)
- **side**: 포지션 방향 (long/short)
- **entry_price**: 평균 진입가
- **size**: 포지션 수량
- **leverage**: 레버리지
- **entry_count**: 현재 진입 횟수 (1=최초진입, 2=1차 DCA, 3=2차 DCA, ...)

### stop_loss (손절 정보)
- **price**: 손절 가격
- **algo_id**: OKX 알고리즘 주문 ID
- **trigger_price**: 트리거 가격

### take_profit (익절 정보 배열)
- **price**: 익절 가격
- **size**: 익절 수량
- **algo_id**: OKX 알고리즘 주문 ID
- **trigger_price**: 트리거 가격

### trailing_stop (트레일링 스톱 정보)
- **active**: 활성화 여부
- **price**: 현재 트레일링 스톱 가격
- **offset**: 트레일링 오프셋 값
- **highest_price**: 최고가 (롱 포지션)
- **lowest_price**: 최저가 (숏 포지션)
- **activation_price**: 트레일링 활성화 가격

### dca (DCA/물타기 정보)
- **next_entry_price**: 다음 DCA 진입 가격
- **remaining_levels**: 남은 DCA 레벨 수
- **all_levels**: 모든 DCA 레벨 가격 목록

## 예시 URL

```
GET /api/position/1709556958/BTC-USDT-SWAP/detail
GET /api/position/518796558012178692/ETH-USDT-SWAP/detail
```
"""

GET_POSITION_DETAIL_RESPONSES = {
    200: {
        "description": "✅ TP/SL 정보 조회 성공",
        "content": {
            "application/json": {
                "examples": {
                    "with_all_info": {
                        "summary": "모든 정보 포함",
                        "value": {
                            "user_id": "518796558012178692",
                            "symbol": "BTC-USDT-SWAP",
                            "position": {
                                "side": "long",
                                "entry_price": 95000.0,
                                "size": 0.1,
                                "leverage": 10.0,
                                "entry_count": 2
                            },
                            "stop_loss": {
                                "price": 93000.0,
                                "algo_id": "123456789",
                                "trigger_price": 93000.0
                            },
                            "take_profit": [
                                {"price": 97000.0, "size": 0.03, "algo_id": "987654321", "trigger_price": 97000.0},
                                {"price": 98000.0, "size": 0.03, "algo_id": "987654322", "trigger_price": 98000.0},
                                {"price": 99000.0, "size": 0.04, "algo_id": "987654323", "trigger_price": 99000.0}
                            ],
                            "trailing_stop": {
                                "active": True,
                                "price": 96500.0,
                                "offset": 500.0,
                                "highest_price": 97000.0,
                                "lowest_price": None,
                                "activation_price": 96000.0
                            },
                            "dca": {
                                "next_entry_price": 94000.0,
                                "remaining_levels": 2,
                                "all_levels": [94000.0, 93000.0]
                            },
                            "timestamp": "2025-01-12T16:30:00"
                        }
                    },
                    "no_position": {
                        "summary": "포지션 없음",
                        "value": {
                            "user_id": "518796558012178692",
                            "symbol": "BTC-USDT-SWAP",
                            "position": None,
                            "stop_loss": None,
                            "take_profit": [],
                            "trailing_stop": None,
                            "dca": None,
                            "timestamp": "2025-01-12T16:30:00"
                        }
                    }
                }
            }
        }
    },
    404: {
        "description": "❌ API 키를 찾을 수 없음"
    },
    500: {
        "description": "❌ 서버 오류"
    }
}
