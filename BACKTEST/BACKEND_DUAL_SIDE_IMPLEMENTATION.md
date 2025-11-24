# 백테스트 양방향 매매 로직 구현 가이드

## 📋 개요

프론트엔드에서 백테스트 요청 시 양방향 매매(Dual-Side Trading) 파라미터를 전송합니다.
이 문서는 백엔드에서 이 파라미터들을 어떻게 처리해야 하는지 설명합니다.

**중요**: 이 양방향 매매 로직은 이미 실제 봇 전략에 구현되어 있습니다.
백테스트는 실제 전략을 시뮬레이션하는 것이므로, 동일한 로직을 적용하면 됩니다.

---

## 🔧 프론트엔드에서 전송하는 파라미터

### 1. 양방향 매매 기본 설정

```typescript
use_dual_side_entry: boolean
```
- **의미**: 양방향 매매 사용 여부
- **조건**: `true`일 때만 아래 모든 파라미터가 전송됨
- **기본값**: `false`

---

### 2. 진입 설정

#### 2-1. 양방향 트리거 (진입 회차)
```typescript
dual_side_entry_trigger: number
```
- **의미**: 몇 번째 DCA 진입에서 반대 방향 포지션을 생성할지
- **예시**: `2` → 2번째 DCA 진입 시 반대 방향 포지션 생성
- **범위**: `1` ~ `pyramiding_limit` (최대 진입 횟수)
- **조건**: `use_dual_side_entry === true`일 때만 전송

#### 2-2. 진입 비율 방식
```typescript
dual_side_entry_ratio_type: 'percent_of_position' | 'fixed_amount'
```
- **의미**: 반대 포지션 진입 시 수량 계산 방식
- **옵션**:
  - `'percent_of_position'`: 기존 포지션 대비 퍼센트
  - `'fixed_amount'`: 고정 수량
- **조건**: `use_dual_side_entry === true`일 때만 전송

#### 2-3. 진입 비율 값
```typescript
dual_side_entry_ratio_value: number
```
- **의미**: 진입 수량 값
- **예시**:
  - `dual_side_entry_ratio_type === 'percent_of_position'` + `dual_side_entry_ratio_value === 100`
    → 기존 포지션의 100% (동일한 수량)
  - `dual_side_entry_ratio_type === 'fixed_amount'` + `dual_side_entry_ratio_value === 0.1`
    → 0.1 BTC 고정 수량
- **조건**: `use_dual_side_entry === true`일 때만 전송

---

### 3. 익절(TP) 설정

#### 3-1. TP 트리거 타입
```typescript
dual_side_entry_tp_trigger_type: 'do_not_close' | 'last_dca_on_position' | 'existing_position' | 'percent'
```
- **의미**: 반대 포지션 익절 방식
- **옵션**:
  - `'do_not_close'`: 익절 사용 안 함 (기본값)
  - `'last_dca_on_position'`: 마지막 DCA 진입가에 익절
  - `'existing_position'`: 기존 포지션의 손절가에 익절
  - `'percent'`: 퍼센트 기준 익절
- **조건**: `use_dual_side_entry === true`일 때만 전송

#### 3-2. TP 퍼센트 값
```typescript
dual_side_entry_tp_value: number
```
- **의미**: 익절 퍼센트 (반대 포지션 평단가 기준)
- **예시**: `1.0` → 평단가 대비 +1% 도달 시 익절
- **조건**: `use_dual_side_entry === true` AND `dual_side_entry_tp_trigger_type === 'percent'`일 때만 전송

#### 3-3. 메인 포지션 종료 옵션
```typescript
close_main_on_hedge_tp: boolean
```
- **의미**: 반대 포지션이 익절될 때 메인 포지션도 함께 종료할지 여부
- **예시**: `true` → 헤지 포지션 익절 시 메인 포지션도 함께 청산
- **조건**: `use_dual_side_entry === true`일 때만 전송

---

### 4. 손절(SL) 설정

#### 4-1. SL 사용 여부
```typescript
use_dual_sl: boolean
```
- **의미**: 반대 포지션에 손절 사용 여부
- **조건**: `use_dual_side_entry === true`일 때만 전송

#### 4-2. SL 트리거 타입
```typescript
dual_side_entry_sl_trigger_type: 'existing_position' | 'percent'
```
- **의미**: 반대 포지션 손절 방식
- **옵션**:
  - `'existing_position'`: 기존 포지션의 TP 가격을 손절선으로 사용
  - `'percent'`: 퍼센트 기준 손절
- **조건**: `use_dual_side_entry === true` AND `use_dual_sl === true`일 때만 전송

#### 4-3. SL 값
```typescript
dual_side_entry_sl_value: number | string
```
- **의미**: 손절 값
- **타입**:
  - `dual_side_entry_sl_trigger_type === 'existing_position'` → `string` ('1', '2', '3')
    - '1': 메인 포지션의 1차 TP 가격을 손절선으로 사용
    - '2': 메인 포지션의 2차 TP 가격을 손절선으로 사용
    - '3': 메인 포지션의 3차 TP 가격을 손절선으로 사용
  - `dual_side_entry_sl_trigger_type === 'percent'` → `number`
    - 예시: `2.0` → 평단가 대비 -2% 도달 시 손절
- **조건**: `use_dual_side_entry === true` AND `use_dual_sl === true`일 때만 전송

---

### 5. 추가 설정

#### 5-1. 양방향 피라미딩 제한
```typescript
dual_side_pyramiding_limit: number
```
- **의미**: 반대 방향으로 최대 몇 회까지 추가 진입을 허용할지
- **예시**: `5` → 반대 포지션도 최대 5회까지 DCA 가능
- **범위**: `1` ~ `10`
- **조건**: `use_dual_side_entry === true`일 때만 전송

#### 5-2. 트렌드 종료 시 함께 청산
```typescript
dual_side_trend_close: boolean
```
- **의미**: 메인 포지션이 트렌드 로직으로 종료될 때 반대 포지션도 함께 청산할지 여부
- **예시**: `true` → 트렌드 반전 감지 시 메인 + 헤지 포지션 모두 청산
- **조건**: `use_dual_side_entry === true`일 때만 전송

---

## 🎯 실제 전송 예시

### 예시 1: 기본적인 양방향 매매 (익절 없음)
```json
{
  "use_dual_side_entry": true,
  "dual_side_entry_trigger": 2,
  "dual_side_entry_ratio_type": "percent_of_position",
  "dual_side_entry_ratio_value": 100,
  "dual_side_entry_tp_trigger_type": "do_not_close",
  "dual_side_entry_tp_value": undefined,
  "close_main_on_hedge_tp": false,
  "use_dual_sl": false,
  "dual_side_entry_sl_trigger_type": undefined,
  "dual_side_entry_sl_value": undefined,
  "dual_side_pyramiding_limit": 5,
  "dual_side_trend_close": false
}
```

### 예시 2: 퍼센트 익절 + 퍼센트 손절
```json
{
  "use_dual_side_entry": true,
  "dual_side_entry_trigger": 3,
  "dual_side_entry_ratio_type": "percent_of_position",
  "dual_side_entry_ratio_value": 50,
  "dual_side_entry_tp_trigger_type": "percent",
  "dual_side_entry_tp_value": 1.5,
  "close_main_on_hedge_tp": true,
  "use_dual_sl": true,
  "dual_side_entry_sl_trigger_type": "percent",
  "dual_side_entry_sl_value": 2.0,
  "dual_side_pyramiding_limit": 3,
  "dual_side_trend_close": true
}
```

### 예시 3: 기존 포지션 TP를 SL로 사용
```json
{
  "use_dual_side_entry": true,
  "dual_side_entry_trigger": 2,
  "dual_side_entry_ratio_type": "fixed_amount",
  "dual_side_entry_ratio_value": 0.1,
  "dual_side_entry_tp_trigger_type": "existing_position",
  "dual_side_entry_tp_value": undefined,
  "close_main_on_hedge_tp": false,
  "use_dual_sl": true,
  "dual_side_entry_sl_trigger_type": "existing_position",
  "dual_side_entry_sl_value": "1",  // 1차 TP 가격을 손절선으로 사용
  "dual_side_pyramiding_limit": 5,
  "dual_side_trend_close": false
}
```

---

## 🔍 백엔드 구현 가이드

### 1. 파라미터 검증

```python
def validate_dual_side_params(params: dict) -> bool:
    """양방향 매매 파라미터 검증"""

    # 양방향 매매 비활성화 시 검증 스킵
    if not params.get('use_dual_side_entry', False):
        return True

    # 필수 파라미터 체크
    required = [
        'dual_side_entry_trigger',
        'dual_side_entry_ratio_type',
        'dual_side_entry_ratio_value',
        'dual_side_entry_tp_trigger_type',
        'dual_side_pyramiding_limit'
    ]

    for key in required:
        if key not in params:
            raise ValueError(f"Missing required dual-side parameter: {key}")

    # 트리거 값 검증
    trigger = params['dual_side_entry_trigger']
    pyramiding_limit = params.get('pyramiding_limit', params.get('dca_max_orders', 5))

    if trigger < 1 or trigger > pyramiding_limit:
        raise ValueError(f"dual_side_entry_trigger must be between 1 and {pyramiding_limit}")

    # TP 퍼센트 값 검증
    if params['dual_side_entry_tp_trigger_type'] == 'percent':
        if 'dual_side_entry_tp_value' not in params:
            raise ValueError("dual_side_entry_tp_value required when tp_trigger_type is 'percent'")

    # SL 값 검증
    if params.get('use_dual_sl', False):
        if 'dual_side_entry_sl_trigger_type' not in params:
            raise ValueError("dual_side_entry_sl_trigger_type required when use_dual_sl is True")

        if params['dual_side_entry_sl_trigger_type'] == 'percent':
            if 'dual_side_entry_sl_value' not in params:
                raise ValueError("dual_side_entry_sl_value required when sl_trigger_type is 'percent'")

    return True
```

### 2. 양방향 포지션 생성 로직

```python
def should_create_dual_side_position(current_entry_count: int, params: dict) -> bool:
    """반대 포지션 생성 여부 확인"""

    if not params.get('use_dual_side_entry', False):
        return False

    trigger = params.get('dual_side_entry_trigger', 2)

    # 트리거 회차에 도달했는지 확인
    return current_entry_count == trigger


def calculate_dual_side_quantity(main_position_qty: float, params: dict) -> float:
    """반대 포지션 수량 계산"""

    ratio_type = params.get('dual_side_entry_ratio_type', 'percent_of_position')
    ratio_value = params.get('dual_side_entry_ratio_value', 100)

    if ratio_type == 'percent_of_position':
        # 메인 포지션 대비 퍼센트
        return main_position_qty * (ratio_value / 100.0)
    else:  # 'fixed_amount'
        # 고정 수량
        return ratio_value
```

### 3. 익절(TP) 로직

```python
def calculate_dual_side_tp_price(
    entry_price: float,
    side: str,  # 'long' or 'short'
    params: dict,
    main_position_sl_price: float = None
) -> float | None:
    """반대 포지션 익절가 계산"""

    tp_type = params.get('dual_side_entry_tp_trigger_type', 'do_not_close')

    if tp_type == 'do_not_close':
        return None

    elif tp_type == 'last_dca_on_position':
        # 마지막 DCA 진입가를 익절가로 사용
        # (실제 구현에서는 마지막 DCA 가격을 추적해야 함)
        return entry_price  # 간소화된 예시

    elif tp_type == 'existing_position':
        # 메인 포지션의 손절가를 익절가로 사용
        return main_position_sl_price

    elif tp_type == 'percent':
        # 퍼센트 기준 익절
        tp_percent = params.get('dual_side_entry_tp_value', 1.0)

        if side == 'long':
            return entry_price * (1 + tp_percent / 100)
        else:  # short
            return entry_price * (1 - tp_percent / 100)

    return None


def should_close_main_on_hedge_tp(params: dict) -> bool:
    """헤지 포지션 익절 시 메인 포지션도 종료할지 여부"""
    return params.get('close_main_on_hedge_tp', False)
```

### 4. 손절(SL) 로직

```python
def calculate_dual_side_sl_price(
    entry_price: float,
    side: str,  # 'long' or 'short'
    params: dict,
    main_position_tp_prices: dict = None  # {'tp1': price, 'tp2': price, 'tp3': price}
) -> float | None:
    """반대 포지션 손절가 계산"""

    if not params.get('use_dual_sl', False):
        return None

    sl_type = params.get('dual_side_entry_sl_trigger_type', 'percent')

    if sl_type == 'existing_position':
        # 메인 포지션의 TP 가격을 손절선으로 사용
        tp_level = params.get('dual_side_entry_sl_value', '1')

        tp_key = f'tp{tp_level}'
        if main_position_tp_prices and tp_key in main_position_tp_prices:
            return main_position_tp_prices[tp_key]

        return None

    elif sl_type == 'percent':
        # 퍼센트 기준 손절
        sl_percent = params.get('dual_side_entry_sl_value', 2.0)

        if side == 'long':
            return entry_price * (1 - sl_percent / 100)
        else:  # short
            return entry_price * (1 + sl_percent / 100)

    return None
```

### 5. 피라미딩 제한

```python
def can_add_dual_side_position(current_dual_entry_count: int, params: dict) -> bool:
    """반대 포지션 추가 진입 가능 여부"""

    max_entries = params.get('dual_side_pyramiding_limit', 5)
    return current_dual_entry_count < max_entries
```

### 6. 트렌드 종료 처리

```python
def should_close_dual_on_trend(params: dict) -> bool:
    """트렌드 종료 시 반대 포지션도 함께 청산할지 여부"""
    return params.get('dual_side_trend_close', False)
```

---

## 📊 통합 예시 (전체 플로우)

```python
class DualSidePositionManager:
    """양방향 매매 포지션 관리자"""

    def __init__(self, params: dict):
        self.params = params
        self.main_position = None
        self.dual_position = None
        self.main_entry_count = 0
        self.dual_entry_count = 0

    def on_main_entry(self, price: float, quantity: float, side: str):
        """메인 포지션 진입 시"""
        self.main_entry_count += 1

        # 양방향 트리거 확인
        if should_create_dual_side_position(self.main_entry_count, self.params):
            self.create_dual_position(price, quantity, side)

    def create_dual_position(self, main_price: float, main_qty: float, main_side: str):
        """반대 포지션 생성"""

        # 반대 방향 결정
        dual_side = 'short' if main_side == 'long' else 'long'

        # 수량 계산
        dual_qty = calculate_dual_side_quantity(main_qty, self.params)

        # TP 계산
        main_sl_price = self.main_position.stop_loss if self.main_position else None
        tp_price = calculate_dual_side_tp_price(
            main_price, dual_side, self.params, main_sl_price
        )

        # SL 계산
        main_tp_prices = {
            'tp1': self.main_position.tp1_price,
            'tp2': self.main_position.tp2_price,
            'tp3': self.main_position.tp3_price
        } if self.main_position else None

        sl_price = calculate_dual_side_sl_price(
            main_price, dual_side, self.params, main_tp_prices
        )

        # 포지션 생성
        self.dual_position = Position(
            side=dual_side,
            entry_price=main_price,
            quantity=dual_qty,
            tp_price=tp_price,
            sl_price=sl_price
        )

        self.dual_entry_count = 1

    def on_dual_tp_hit(self):
        """헤지 포지션 익절 시"""

        # 헤지 포지션 청산
        self.dual_position.close()

        # 메인 포지션도 함께 종료할지 확인
        if should_close_main_on_hedge_tp(self.params):
            self.main_position.close()

    def on_trend_reversal(self):
        """트렌드 반전 감지 시"""

        # 메인 포지션 종료
        self.main_position.close()

        # 헤지 포지션도 함께 종료할지 확인
        if should_close_dual_on_trend(self.params):
            if self.dual_position and not self.dual_position.is_closed:
                self.dual_position.close()
```

---

## ✅ 체크리스트

백엔드에서 구현 시 확인해야 할 사항:

- [ ] `use_dual_side_entry === false`일 때 모든 양방향 로직 스킵
- [ ] `dual_side_entry_trigger` 회차에 정확히 반대 포지션 생성
- [ ] `dual_side_entry_ratio_type`에 따라 수량 정확히 계산
- [ ] `dual_side_entry_tp_trigger_type`에 따라 익절가 정확히 계산
- [ ] `dual_side_entry_sl_trigger_type`에 따라 손절가 정확히 계산
- [ ] `close_main_on_hedge_tp === true`일 때 메인 포지션 함께 종료
- [ ] `dual_side_pyramiding_limit`를 초과하지 않도록 제한
- [ ] `dual_side_trend_close === true`일 때 트렌드 종료 시 헤지 포지션도 함께 청산
- [ ] `undefined` 값 처리 (조건부 파라미터)
- [ ] 트레이드 히스토리에 양방향 매매 정보 기록

---

## 🚨 주의사항

1. **조건부 파라미터**: `use_dual_side_entry === true`일 때만 대부분의 파라미터가 전송됩니다.
2. **undefined 처리**: 백엔드에서 `undefined` 값을 적절히 처리해야 합니다 (Python에서는 `None`).
3. **타입 혼합**: `dual_side_entry_sl_value`는 `string` 또는 `number`가 될 수 있습니다.
4. **실제 전략 참고**: 이 로직은 이미 실제 봇 전략에 구현되어 있으므로, 해당 코드를 참고하세요.

---

## 📞 추가 질문이 있다면

이 문서로 백엔드 구현이 가능할 것입니다. 추가 질문이나 명확하지 않은 부분이 있으면 알려주세요!
