# DCA 미작동 근본 원인 분석

## 🚨 핵심 문제

**ATR 기반 DCA 설정으로 변경했지만 여전히 DCA가 발동하지 않음**

### 백테스트 결과 요약

**퍼센트 기반 (3%)**:
- 총 거래: 3회
- DCA 발동: 0회
- 총 수익률: +11.78%
- 승률: 100%

**ATR 기반 (3 ATR)**:
- 총 거래: 3회
- DCA 발동: 0회 ⚠️
- 총 수익률: +11.78%
- 승률: 100%

→ **결과가 완전히 동일함!**

---

## 🔍 근본 원인 조사

### 1단계: 설정 파일 확인 ✅

```json
{
  "pyramiding_entry_type": "ATR 기준",  // ✅ 올바름
  "pyramiding_value": 3.0               // ✅ 올바름
}
```

### 2단계: 백테스트 엔진 코드 확인 ✅

`BACKTEST/engine/dca_calculator.py` lines 83-98:

```python
else:  # "ATR 기준"
    # ATR-based calculation
    if atr_value is None or atr_value == 0:
        logger.warning(
            f"ATR value is {atr_value}, cannot calculate ATR-based DCA level. "
            f"Falling back to percentage-based with 3%"
        )
        # ⚠️ FALLBACK: 퍼센트 기준으로 전환!
        if side == "long":
            level = reference_price * 0.97  # 3% below
        else:
            level = reference_price * 1.03  # 3% above
    else:
        # ✅ 정상적인 ATR 기반 계산
        if side == "long":
            level = reference_price - (atr_value * pyramiding_value)
        else:  # short
            level = reference_price + (atr_value * pyramiding_value)
```

**로직은 올바름** - ATR 값이 없으면 fallback 발동

### 3단계: ATR 값 전달 확인 ✅

`BACKTEST/engine/backtest_engine.py` line 332:

```python
dca_levels = calculate_dca_levels(
    entry_price=filled_price,
    last_filled_price=filled_price,
    settings=self.strategy_params,
    side=position.side.value,
    atr_value=candle.atr if hasattr(candle, 'atr') else None,  // ✅ ATR 전달 시도
    current_price=candle.close
)
```

### 4단계: TimescaleDB 데이터 확인 ❌

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'okx_candles_15m'
AND column_name LIKE '%atr%'
```

**결과**:
- `atr` 컬럼 존재: ✅
- 데이터 타입: `numeric` ✅
- **실제 데이터 값: NULL** ❌❌❌

```python
time: 2025-05-03 11:00:00+09:00
close: <valid_price>
rsi: <valid_value>
ema: <valid_value>
sma: <valid_value>
atr: None  # ❌ ATR 값이 없음!
```

---

## 🎯 결론

### ATR 기반 DCA가 작동하지 않은 이유

1. **TimescaleDB에 ATR 값이 없음**
2. `candle.atr = None` 상태로 `calculate_dca_levels()` 호출
3. Fallback 로직 발동: 퍼센트 기준 3%로 자동 전환
4. 결과적으로 퍼센트 기반과 동일하게 작동

### 퍼센트 기반 DCA가 작동하지 않은 이유

**DCA_ANALYSIS_REPORT.txt** 분석 결과:

- **가격 조건**: 3% 역방향 움직임이 TP 전에 발생하지 않음
  - 거래 #1: DCA Level 1까지 최소 2.86% 부족
  - 거래 #2: DCA Level 1까지 최소 1.44% 부족
  - 거래 #3: DCA Level 1까지 최소 2.34% 부족

- **RSI + Trend 조건**: 개별적으로는 충족되지만 **동시 충족 0회**
  - 거래 #2: RSI 충족 14회(1.9%), Trend 충족 391회(53.3%)
  - 하지만 가격 조건이 0회이므로 전체 조건 충족 0회

- **빠른 TP 달성**: 평균 보유 시간 74.92시간 (3.1일)
  - 가격이 역방향 3% 움직이기 전에 TP 4% 먼저 달성

---

## 💡 해결 방안

### 즉시 적용 가능한 방안

#### 1. DCA 진입 조건 완화 ⭐ 추천

```json
{
  "pyramiding_entry_type": "퍼센트 기준",
  "pyramiding_value": 1.5,  // 3.0 → 1.5% (더 빨리 DCA 도달)
  "use_rsi_with_pyramiding": false,  // RSI 체크 제거
  "use_trend_logic": false,  // Trend 체크 제거
  "use_check_DCA_with_price": true  // 가격 조건만 유지
}
```

**예상 효과**:
- 거래 #2에서 1.44% 움직임으로 DCA Level 1 도달 가능
- RSI/Trend 조건 제거로 가격 조건만 충족하면 DCA 발동

#### 2. Entry Criterion 변경 테스트

```json
{
  "entry_criterion": "최근 진입가"  // "평균 단가" → "최근 진입가"
}
```

**효과**: 추가 진입 시 평균가 대신 마지막 진입가 기준으로 계산하여 더 유연한 DCA 가능

### 장기 해결 방안

#### 3. TimescaleDB ATR 데이터 계산/저장

**필요 작업**:
1. OKX API에서 받은 캔들 데이터로 ATR 계산 (period=14)
2. TimescaleDB `okx_candles_15m` 테이블에 ATR 값 저장
3. 백테스트 시 ATR 기반 DCA 정상 작동

**구현 후 효과**:
- 3 ATR 기준으로 시장 변동성에 적응적인 DCA 레벨 설정
- 변동성 높을 때: 넓은 DCA 간격 (손실 방지)
- 변동성 낮을 때: 좁은 DCA 간격 (기회 활용)

---

## 📋 권장 테스트 순서

### 1차 테스트: 조건 완화 (즉시 가능)
```json
{
  "pyramiding_entry_type": "퍼센트 기준",
  "pyramiding_value": 1.5,
  "use_rsi_with_pyramiding": false,
  "use_trend_logic": false
}
```

### 2차 테스트: 더 공격적인 DCA
```json
{
  "pyramiding_value": 1.0  // 1% 간격으로 더 자주 DCA
}
```

### 3차 테스트: ATR 구현 후 (장기)
```json
{
  "pyramiding_entry_type": "ATR 기준",
  "pyramiding_value": 2.0  // 2 ATR (3 ATR보다 더 빈번)
}
```

---

## 📊 예상 결과

### 1.5% + 조건 완화 시나리오

**거래 #2 (LONG)**:
- 진입가: $112,579.78
- DCA Level 1: $110,850.83 (-1.5%)
- 최저가: $110,780.30

→ ✅ **DCA Level 1 도달!** (최저가가 DCA 레벨보다 낮음)
→ 추가 진입 발생 예상

**예상 개선**:
- DCA 발동: 0회 → 1-2회
- 평균 진입가 개선으로 수익률 향상 가능
- 손실 시 리스크 분산 효과
