# HYPERRSI 사용자 가이드

## 시작하기

### 1. 서버 실행 (개발자)

```bash
cd HYPERRSI
python main.py
```

서버 주소: `http://localhost:8000`

---

## 기본 사용 흐름

### Step 1: 초기 설정 확인

**API 접속**: `http://localhost:8000/docs`

#### 1.1 잔고 확인
- `GET /api/account/balance`
- `user_id` 입력 (OKX UID 또는 텔레그램 ID)
- 충분한 잔고 확인 (최소 100 USDT 권장)

#### 1.2 현재 설정 확인
- `GET /api/settings/{user_id}`
- 레버리지, 익절/손절 비율 확인

#### 1.3 설정 변경 (필요시)
- `PUT /api/settings/{user_id}`

```json
{
  "settings": {
    "leverage": 10,
    "direction": "롱숏",
    "tp1_value": 2.0,
    "sl_value": 1.5
  }
}
```

---

### Step 2: 매매 시작

**API**: `POST /api/trading/start`

```json
{
  "user_id": "본인_ID",
  "symbol": "SOL-USDT-SWAP",
  "timeframe": "1m"
}
```

**성공 응답**:
```json
{
  "status": "success",
  "message": "트레이딩 태스크가 시작되었습니다.",
  "task_id": "uuid..."
}
```

---

### Step 3: 매매 모니터링

#### 3.1 실시간 확인 (매 2-5분)

**매매 상태**
- `GET /api/trading/status?user_id=본인_ID`
- `status: "running"` 확인

**포지션 확인**
- `GET /api/account/positions?user_id=본인_ID`
- 진입 여부, 방향(롱/숏), 크기, 손익 확인

**주문 내역**
- `GET /api/order/history?user_id=본인_ID`
- 진입/청산 주문 확인

#### 3.2 통계 확인
- `GET /api/stats/summary?user_id=본인_ID`
- 승률, 총 손익, 거래 횟수 확인

---

### Step 4: 매매 중지

**API**: `POST /api/trading/stop`

```json
{
  "user_id": "본인_ID"
}
```

**중지 후 확인**:
- 포지션 조회로 모든 포지션 청산 확인
- 열린 포지션 있으면 TP/SL로 자동 청산 대기 또는 수동 청산

---

## 매매 로직 이해

### 진입 조건
1. **RSI 기반 신호 발생**
   - 과매도(RSI < 30): 롱 진입 조건
   - 과매수(RSI > 70): 숏 진입 조건

2. **설정 확인**
   - `direction` 설정에 맞는 방향만 진입
   - 쿨다운 시간 경과 확인

3. **포지션 생성**
   - 설정된 레버리지로 진입
   - `entry_multiplier`에 따라 포지션 크기 조절

### 청산 조건

**익절 (Take Profit)**
- TP1: 설정 비율(예: 2%) 도달 시 자동 청산
- TP2: 추가 목표(예: 4%) 도달 시 잔량 청산

**손절 (Stop Loss)**
- SL: 손실 비율(예: -1.5%) 도달 시 즉시 청산

---

## 점검 사항

### 매매 시작 전
- [ ] 잔고 충분한지 확인 (최소 100 USDT)
- [ ] 설정값 확인 (레버리지, TP/SL)
- [ ] 텔레그램 알림 설정 (선택)

### 매매 진행 중 (매 5-10분)
- [ ] 매매 상태가 "running"인지
- [ ] 포지션 진입/청산 정상 동작
- [ ] 예상치 못한 손실 발생 여부
- [ ] 텔레그램 알림 수신 (진입/청산)

### 매매 종료 후
- [ ] 모든 포지션 청산 확인
- [ ] 최종 수익/손실 확인
- [ ] 통계 기록 확인

---

## 주요 설정 값 설명

| 설정 | 설명 | 범위 | 권장값 |
|------|------|------|--------|
| leverage | 레버리지 배수 | 1-125 | 5-10 |
| direction | 거래 방향 | 롱/숏/롱숏 | 롱숏 |
| entry_multiplier | 진입 금액 배수 | 0.1-10.0 | 0.5-1.0 |
| tp1_value | 1차 익절 비율 (%) | 0.5-10.0 | 1.5-2.0 |
| tp2_value | 2차 익절 비율 (%) | 1.0-20.0 | 3.0-4.0 |
| sl_value | 손절 비율 (%) | 0.5-5.0 | 1.0-1.5 |
| use_cooldown | 쿨다운 사용 | true/false | true |

---

## 문제 해결

### "매매가 시작되지 않아요"
1. `GET /api/trading/status`로 상태 확인
2. 이미 실행 중이면 먼저 중지 후 재시작
3. 잔고 충분한지 확인

### "포지션이 생성되지 않아요"
- **정상 상황**: RSI 조건 만족 대기 중 (5-30분 소요 가능)
- **쿨다운**: 이전 거래 후 쿨다운 시간 대기 중
- **확인**: 거래 방향 설정 확인

### "익절/손절이 작동하지 않아요"
1. 설정값 확인: `GET /api/settings/{user_id}`
2. 포지션 상세: `GET /api/account/positions`
3. 가격이 목표에 도달했는지 확인

### "텔레그램 알림이 오지 않아요"
1. 텔레그램 봇과 대화 시작했는지 확인
2. 알림 설정 활성화 확인: `GET /api/telegram/settings`

---

## 실전 시나리오

### 시나리오 1: 보수적 설정 (초보자)

```json
{
  "settings": {
    "leverage": 5,
    "direction": "롱",
    "entry_multiplier": 0.5,
    "tp1_value": 1.5,
    "sl_value": 1.0,
    "use_cooldown": true
  }
}
```

- **특징**: 낮은 위험, 안정적 운영
- **목표**: 매매 로직 이해 및 시스템 안정성 확인

### 시나리오 2: 표준 설정 (일반)

```json
{
  "settings": {
    "leverage": 10,
    "direction": "롱숏",
    "entry_multiplier": 1.0,
    "tp1_value": 2.0,
    "sl_value": 1.5,
    "use_cooldown": true
  }
}
```

- **특징**: 균형잡힌 리스크-수익
- **목표**: 정상적인 매매 운영

---

## 용어 설명

- **User ID**: OKX UID (18자리) 또는 텔레그램 ID
- **레버리지**: 자금의 몇 배로 거래 (10배 = 10 USDT로 100 USDT 거래)
- **롱**: 가격 상승 시 수익
- **숏**: 가격 하락 시 수익
- **TP (Take Profit)**: 익절, 목표 수익률 도달 시 자동 청산
- **SL (Stop Loss)**: 손절, 손실 한도 도달 시 자동 청산
- **쿨다운**: 연속 거래 방지를 위한 대기 시간

---

**버전**: 1.0.0
**최종 업데이트**: 2025-01-15
