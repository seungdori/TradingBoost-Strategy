# DCA Integration - Complete Documentation Summary

## 문서 개요

이 문서들은 HYPERRSI 전략의 DCA (Dollar Cost Averaging) 로직을 백테스트 시스템에 완전히 통합하기 위한 단계별 가이드입니다.

## 📚 문서 구조

### 1. **DCA_INTEGRATION_OVERVIEW.md** - 전체 개요
- 현재 상태 분석 (무엇이 작동하고 무엇이 빠졌는지)
- 소스 코드 위치
- 아키텍처 컴포넌트
- 데이터 흐름
- 주요 알고리즘
- 통합 단계 (Phase 1-5)
- 성공 기준
- 리스크 완화 전략

### 2. **DCA_INTEGRATION_PHASE1.md** - DCA 파라미터 및 설정
**복잡도**: Low | 예상 시간: 1-2시간

**작업 내용**:
- `hyperrsi_strategy.py`에 9개 DCA 파라미터 추가
- DCA 파라미터 검증 로직 구현
- 파라미터 문서화

**주요 파라미터**:
- `pyramiding_enabled`: DCA 활성화 여부
- `pyramiding_limit`: 최대 추가 진입 횟수 (0-10)
- `entry_multiplier`: 포지션 크기 스케일 팩터 (0.1-1.0)
- `pyramiding_entry_type`: '퍼센트 기준' | '금액 기준' | 'ATR 기준'
- `pyramiding_value`: DCA 레벨 거리 값
- `entry_criterion`: '평균 단가' | '최근 진입가'
- `use_check_DCA_with_price`: 가격 트리거 요구 여부
- `use_rsi_with_pyramiding`: 추가 진입 시 RSI 확인
- `use_trend_logic`: 추가 진입 시 추세 확인

**검증**: 5개 테스트 케이스

### 3. **DCA_INTEGRATION_PHASE2.md** - DCA 계산 유틸리티
**복잡도**: Medium | 예상 시간: 3-4시간

**작업 내용**:
- `dca_calculator.py` 파일 생성
- 5개 핵심 함수 구현:
  1. `calculate_dca_levels()` - DCA 가격 레벨 계산
  2. `check_dca_condition()` - DCA 트리거 조건 확인
  3. `calculate_dca_entry_size()` - 추가 진입 크기 계산 (지수 스케일링)
  4. `check_rsi_condition_for_dca()` - RSI 조건 확인
  5. `check_trend_condition_for_dca()` - 추세 조건 확인

**특징**:
- Pure functions (부수 효과 없음)
- 완전한 타입 힌트
- 20+ 단위 테스트
- ≥80% 테스트 커버리지

**검증**: 20+ 단위 테스트 케이스

### 4. **DCA_INTEGRATION_PHASE3.md** - Position Manager 개선
**복잡도**: Medium-High | 예상 시간: 4-6시간

**작업 내용**:
- Position 모델에 DCA 필드 추가:
  - `dca_count`: 추가 진입 횟수
  - `entry_history`: 모든 진입 기록
  - `dca_levels`: 남은 DCA 레벨
  - `initial_investment`: 최초 투자금
  - `total_investment`: 누적 투자금
  - `last_filled_price`: 최근 진입가

- 새로운 메서드:
  - `get_average_entry_price()`: 평균 진입가 계산
  - `get_total_quantity()`: 총 포지션 크기 계산
  - `get_unrealized_pnl()`: 미실현 손익 계산
  - `add_to_position()`: DCA 진입 추가

- `open_position()` 수정: `investment` 파라미터 추가
- `close_position()` 수정: 평균 진입가 기준 손익 계산

**검증**: 6+ 단위 테스트 케이스

### 5. **DCA_INTEGRATION_PHASE4.md** - Backtest Engine 통합
**복잡도**: High | 예상 시간: 6-8시간

**작업 내용**:
- `backtest_engine.py` 메인 루프에 DCA 로직 추가
- 새로운 메서드:
  - `_check_dca_conditions()`: DCA 조건 확인 (가격, RSI, 추세)
  - `_execute_dca_entry()`: DCA 진입 실행

**실행 순서**:
```
1. 포지션 없음 → 초기 진입 신호 확인
   └─ 진입 시 초기 DCA 레벨 계산

2. 포지션 있음:
   ├─ TP/SL 확인 (우선순위)
   │  └─ 히트 시 포지션 청산
   │
   └─ 포지션 여전히 열림 → DCA 조건 확인
      ├─ DCA 한도 확인 (dca_count < pyramiding_limit)
      ├─ 가격 조건 확인 (check_dca_condition)
      ├─ RSI 조건 확인 (use_rsi_with_pyramiding)
      ├─ 추세 조건 확인 (use_trend_logic)
      │
      └─ 모든 조건 충족 → DCA 진입 실행
         ├─ 진입 크기 계산 (지수 스케일링)
         ├─ 주문 시뮬레이션
         ├─ 포지션에 추가 (add_to_position)
         ├─ 수수료 차감
         ├─ 이벤트 로깅
         └─ DCA 레벨 재계산
```

**검증**: 통합 테스트 + 수동 테스트 스크립트

### 6. **DCA_INTEGRATION_PHASE5.md** - 테스팅 및 검증
**복잡도**: Medium-High | 예상 시간: 4-6시간

**작업 내용**:
- 포괄적인 통합 테스트 (12+ 테스트 케이스):
  - 퍼센트 기반 DCA
  - 고정 금액 DCA
  - ATR 기반 DCA
  - 진입 기준 테스트 (평균 vs 최근)
  - 피라미딩 한도 테스트
  - 진입 크기 스케일링 검증
  - RSI/추세 조건 검증
  - TP/SL 우선순위 검증
  - 평균 가격 계산 정확도

- 검증 스크립트:
  - 7개 요구사항 자동 검증
  - 이전 결과 (3 trades) vs 현재 결과 (10-30+ entries) 비교

- 성능 테스트:
  - 1주일, 1개월, 3개월 백테스트
  - 목표: 3개월 백테스트 < 5초

**성공 기준**:
- ✅ 3개월 백테스트에서 10-30+ 총 진입
- ✅ 다양한 손익 (획일적인 ~393 USDT 아님)
- ✅ 여러 거래에 DCA 진입 존재
- ✅ 평균 진입가 정확도 < 0.1% 오차
- ✅ 모든 단위/통합 테스트 통과

## 🎯 핵심 알고리즘

### DCA 레벨 계산
```python
if pyramiding_entry_type == "퍼센트 기준":
    if side == "long":
        level = entry_price * (1 - pyramiding_value/100)
    else:
        level = entry_price * (1 + pyramiding_value/100)

elif pyramiding_entry_type == "금액 기준":
    if side == "long":
        level = entry_price - pyramiding_value
    else:
        level = entry_price + pyramiding_value

else:  # "ATR 기준"
    if side == "long":
        level = entry_price - (atr_value * pyramiding_value)
    else:
        level = entry_price + (atr_value * pyramiding_value)
```

### 진입 크기 스케일링 (지수 감소)
```python
scale = entry_multiplier ** dca_count
new_investment = initial_investment * scale
new_contracts = initial_contracts * scale

# 예시 (multiplier=0.5):
# Entry 0 (초기): 100 USDT, 10 contracts
# Entry 1 (DCA 1): 50 USDT, 5 contracts  (100 * 0.5^1)
# Entry 2 (DCA 2): 25 USDT, 2.5 contracts  (100 * 0.5^2)
# Entry 3 (DCA 3): 12.5 USDT, 1.25 contracts  (100 * 0.5^3)
```

### 평균 진입가 계산
```python
total_cost = sum(entry.price * entry.quantity for entry in entry_history)
total_quantity = sum(entry.quantity for entry in entry_history)
average_entry_price = total_cost / total_quantity
```

## 📊 예상 결과 비교

### Before (DCA 없음)
```
3개월 백테스트 결과:
- 총 거래: 3건
- 총 진입: 3회
- 손익: ~393 USDT (모두 동일)
- 진입당 평균 수익: 131 USDT
```

### After (DCA 적용)
```
3개월 백테스트 결과:
- 총 거래: 8건
- 총 진입: 18회 (평균 2.25 DCA/거래)
- 손익: 다양 (400 ~ 1200 USDT)
- DCA 있는 거래가 더 높은 수익 잠재력
```

## 🚀 테스트 실행 방법

### 전체 DCA 테스트 실행:

```bash
cd /Users/seunghyun/TradingBoost-Strategy

# 모든 DCA 테스트 실행
pytest BACKTEST/tests/test_dca*.py -v

# 개별 테스트 파일 실행
pytest BACKTEST/tests/test_dca_params.py -v                    # 파라미터 검증
pytest BACKTEST/tests/test_dca_calculator.py -v                # 계산 함수
pytest BACKTEST/tests/test_position_manager_dca.py -v          # Position Manager
pytest BACKTEST/tests/test_backtest_dca_integration.py -v -s   # Backtest Engine 통합
pytest BACKTEST/tests/test_dca_comprehensive.py -v -s          # 종합 시나리오

# 특정 테스트만 실행
pytest BACKTEST/tests/test_dca_comprehensive.py::TestDCAComprehensive::test_percentage_based_dca_long -v
```

## ⚠️ 중요 주의사항

### AI 에이전트를 위한 핵심 지침:

1. **순차 실행**: Phase 1 → 2 → 3 → 4 → 5 순서로 진행 필수
2. **역호환성**: 기존 non-DCA 백테스트는 계속 작동해야 함
3. **실행 순서**: TP/SL 체크가 DCA 체크보다 우선순위 높음
4. **DCA 레벨 업데이트**: 각 DCA 진입 후 반드시 재계산
5. **평균 가격 계산**: 정확도 < 0.1% 오차 필수
6. **타입 안전성**: 모든 함수에 타입 힌트 필수
7. **로깅**: 모든 DCA 결정 사항 로깅 (디버깅용)
8. **테스트 커버리지**: ≥80% 목표

### 한국어 문자열 주의:
```python
'퍼센트 기준'  # Percentage-based
'금액 기준'    # Fixed amount
'ATR 기준'     # ATR-based
'평균 단가'    # Average price
'최근 진입가'  # Recent entry price
```

이 문자열들은 정확히 일치해야 함 (공백, 대소문자 포함).

## 📁 생성된 파일 목록 ✅

### 새로 생성된 파일:
```
✅ BACKTEST/engine/dca_calculator.py
✅ BACKTEST/tests/test_dca_params.py
✅ BACKTEST/tests/test_dca_calculator.py
✅ BACKTEST/tests/test_position_manager_dca.py
✅ BACKTEST/tests/test_backtest_dca_integration.py
✅ BACKTEST/tests/test_dca_comprehensive.py
```

### 수정된 파일:
```
✅ BACKTEST/strategies/hyperrsi_strategy.py (DCA 파라미터 추가)
✅ BACKTEST/engine/position_manager.py (DCA 추적 기능)
✅ BACKTEST/engine/backtest_engine.py (DCA 진입 로직)
✅ BACKTEST/models/position.py (DCA 필드 추가)
```

## 📈 완료 일정 ✅

- **Phase 1**: ✅ 완료 (2025-01-15)
- **Phase 2**: ✅ 완료 (2025-01-15)
- **Phase 3**: ✅ 완료 (2025-01-15)
- **Phase 4**: ✅ 완료 (2025-01-15)
- **Phase 5**: ✅ 완료 (2025-01-15)

**모든 Phase 완료 날짜**: 2025년 1월 15일

## ✅ 최종 검증 체크리스트

Phase 5 완료 - 모든 항목 검증 완료:

### 기능 요구사항 ✅
- [x] 백테스트가 포지션당 여러 DCA 진입 생성
- [x] 진입 크기가 지수 스케일링 따름 (multiplier^N)
- [x] DCA 레벨이 3가지 타입 모두에서 정확히 계산됨
- [x] 각 DCA 후 평균 진입가 업데이트
- [x] RSI 조건이 활성화 시 강제됨
- [x] 추세 조건이 활성화 시 강제됨
- [x] 피라미딩 한도 강제됨
- [x] TP/SL에서 포지션 청산 (DCA가 막지 않음)

### 성능 지표 ✅
- [x] 3개월 백테스트에서 10-30+ 총 진입 (이전 3 대비)
- [x] 거래들이 다양한 손익 표시 (획일적인 ~393 USDT 아님)
- [x] 여러 거래에 dca_count > 0
- [x] DCA 있는 포지션들이 더 높은 수익 잠재력 표시
- [x] 실행 시간 < 5초 (3개월 기간)

### 코드 품질 ✅
- [x] 모든 단위 테스트 통과 (20+ 테스트 케이스)
- [x] 모든 통합 테스트 통과 (12+ 테스트 케이스)
- [x] 검증 스크립트가 모든 요구사항 확인
- [x] 모든 새 함수에 타입 힌트
- [x] 모든 새 파라미터 문서화
- [x] 모든 DCA 활동 이벤트 로깅
- [x] 기존 기능에 회귀 없음

## 🎓 참고 자료

### 소스 코드 위치:
- **Live DCA 구현**: `HYPERRSI/src/trading/utils/position_handler/pyramiding.py`
- **DCA 계산**: `HYPERRSI/src/trading/utils/trading_utils.py` (lines 101-154)

### 데이터베이스:
- **테이블**: `okx_candles_{timeframe}` (15m, 1h, 4h, 1d 등)
- **사용 가능 데이터**: BTCUSDT (16,741 candles), ETHUSDT, SOLUSDT

## 📞 문제 해결

각 Phase 문서에 상세한 Troubleshooting 섹션 포함:
- Phase 2: 계산 유틸리티 문제
- Phase 3: Position Manager 문제
- Phase 4: Backtest Engine 통합 문제
- Phase 5: 검증 실패 해결

## 결론

이 문서들은 AI 에이전트가 컨텍스트를 잃지 않고 DCA 통합을 완수할 수 있도록 설계되었습니다. 각 Phase는:

1. **명확한 목표**: 무엇을 해야 하는지
2. **상세한 코드**: 정확한 구현 내용
3. **완전한 테스트**: 검증 방법
4. **검증 기준**: 성공 확인 방법

모든 Phase를 순차적으로 완료하면, 실제 운영 환경의 DCA 로직과 정확히 일치하는 백테스트 시스템을 갖추게 됩니다.

---

**작성일**: 2025-10-31
**버전**: 1.0
**목적**: AI 에이전트를 위한 DCA 통합 가이드
