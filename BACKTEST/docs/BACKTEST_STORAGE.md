# 백테스팅 결과 저장 시스템

백테스팅 설정값 자동 저장 및 결과를 TimescaleDB에 저장하는 시스템 문서입니다.

## 📋 목차

- [개요](#개요)
- [주요 기능](#주요-기능)
- [데이터베이스 구조](#데이터베이스-구조)
- [API 엔드포인트](#api-엔드포인트)
- [사용 방법](#사용-방법)
- [코드 예시](#코드-예시)
- [마이그레이션](#마이그레이션)

## 개요

사용자가 백테스팅을 실행할 때 설정값을 자동으로 저장하고, 백테스팅 결과를 TimescaleDB에 저장하여 나중에 조회하고 분석할 수 있는 시스템입니다.

### 핵심 특징

- ✅ **설정값 자동 저장**: localStorage를 활용한 마지막 설정값 복원
- ✅ **완전한 결과 저장**: 모든 거래 내역, DCA 히스토리, 자산 곡선 포함
- ✅ **TimescaleDB 최적화**: 시계열 데이터를 위한 Hypertable 활용
- ✅ **트랜잭션 안전성**: 원자적 저장으로 데이터 무결성 보장
- ✅ **통계 및 분석**: 사용자별 백테스팅 통계 자동 계산

## 주요 기능

### 1. 설정값 자동 저장/불러오기

**위치**: `app/trade/(dashboard)/bot_list/backtest/components/HyperRsiBacktestForm.tsx`

사용자가 백테스팅 설정을 변경할 때마다 localStorage에 자동 저장됩니다.

**저장되는 설정값**:
- **기본 설정**: 심볼, 타임프레임, 시작일/종료일, 초기 잔고
- **전략 파라미터**: RSI 진입 옵션, 과매수/과매도 기준, 레버리지, 투자금, 손절
- **DCA 설정**: 물타기 활성화 여부, 최대 횟수, 진입 타입, 진입 값, 추세 로직
- **수익 관리**: TP1/TP2/TP3 설정, 트레일링 스탑 설정

```typescript
// localStorage 키
const STORAGE_KEY = 'backtest_settings';

// 자동 저장
useEffect(() => {
  const settings = { symbol, timeframe, rsiOversold, ... };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}, [symbol, timeframe, ...]);

// 자동 불러오기
useEffect(() => {
  const savedSettings = localStorage.getItem(STORAGE_KEY);
  if (savedSettings) {
    const settings = JSON.parse(savedSettings);
    setSymbol(settings.symbol);
    // ... 모든 설정값 복원
  }
}, []);
```

### 2. 백테스팅 결과 자동 저장

**위치**: `app/trade/(dashboard)/bot_list/backtest/page.tsx`

백테스팅 실행 완료 후 자동으로 DB에 저장됩니다.

```typescript
const handleSubmit = async (request: BacktestRequest) => {
  // 1. 백테스팅 실행
  const response = await fetch(`${BACKTEST_BACKEND_URL}/backtest/run`, {
    method: 'POST',
    body: JSON.stringify(request),
  });
  const data: BacktestResponse = await response.json();

  // 2. 자동으로 DB에 저장
  await saveBacktestToDB(data);

  // 3. 사용자에게 결과 표시
  setResult(data);
};
```

## 데이터베이스 구조

### ERD (Entity Relationship Diagram)

```
┌─────────────────────────┐
│   backtest_results      │
│─────────────────────────│
│ • id (UUID, PK)         │
│ • user_id (UUID)        │
│ • symbol                │
│ • timeframe             │
│ • start_date            │
│ • end_date              │
│ • strategy_name         │
│ • strategy_params (JSON)│
│ • initial_balance       │
│ • final_balance         │
│ • total_return_percent  │
│ • win_rate              │
│ • profit_factor         │
│ • sharpe_ratio          │
│ • ... (30+ columns)     │
└─────────────────────────┘
           │
           │ 1:N
           ▼
┌─────────────────────────┐
│   backtest_trades       │
│─────────────────────────│
│ • id (UUID, PK)         │
│ • backtest_id (FK)      │
│ • trade_number          │
│ • side (long/short)     │
│ • entry_timestamp       │
│ • entry_price           │
│ • exit_timestamp        │
│ • exit_price            │
│ • pnl                   │
│ • pnl_percent           │
│ • dca_count             │
│ • entry_history (JSON)  │
│ • is_partial_exit       │
│ • tp_level              │
└─────────────────────────┘
           │
           │ 1:N
           ▼
┌─────────────────────────┐
│ backtest_equity_curve   │
│     (Hypertable)        │
│─────────────────────────│
│ • backtest_id (FK)      │
│ • timestamp (PK)        │
│ • balance               │
│ • pnl                   │
│ • trade_number          │
└─────────────────────────┘
```

### 1. backtest_results (메인 결과 테이블)

백테스팅 실행 정보와 전체 결과를 저장합니다.

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| `id` | UUID | 기본키 |
| `user_id` | UUID | 사용자 ID |
| `symbol` | VARCHAR(20) | 거래 심볼 (예: BTCUSDT) |
| `timeframe` | VARCHAR(10) | 타임프레임 (예: 15m, 1h) |
| `start_date` | TIMESTAMPTZ | 백테스팅 시작일 |
| `end_date` | TIMESTAMPTZ | 백테스팅 종료일 |
| `strategy_name` | VARCHAR(50) | 전략 이름 (예: hyperrsi) |
| `strategy_params` | JSONB | 전략 파라미터 (JSON) |
| `status` | VARCHAR(20) | 상태 (completed, running, failed) |
| `initial_balance` | NUMERIC(20,8) | 초기 잔고 |
| `final_balance` | NUMERIC(20,8) | 최종 잔고 |
| `total_return` | NUMERIC(20,8) | 총 수익 (절대값) |
| `total_return_percent` | NUMERIC(10,4) | 총 수익률 (%) |
| `max_drawdown` | NUMERIC(20,8) | 최대 낙폭 (절대값) |
| `max_drawdown_percent` | NUMERIC(10,4) | 최대 낙폭률 (%) |
| `total_trades` | INTEGER | 총 거래 횟수 |
| `winning_trades` | INTEGER | 수익 거래 횟수 |
| `losing_trades` | INTEGER | 손실 거래 횟수 |
| `win_rate` | NUMERIC(5,2) | 승률 (%) |
| `profit_factor` | NUMERIC(10,4) | Profit Factor |
| `sharpe_ratio` | NUMERIC(10,4) | 샤프 지수 |
| `sortino_ratio` | NUMERIC(10,4) | 소르티노 지수 |
| `avg_win` | NUMERIC(20,8) | 평균 수익 |
| `avg_loss` | NUMERIC(20,8) | 평균 손실 |
| `largest_win` | NUMERIC(20,8) | 최대 수익 |
| `largest_loss` | NUMERIC(20,8) | 최대 손실 |
| `avg_trade_duration_minutes` | NUMERIC(10,2) | 평균 거래 기간 (분) |
| `total_fees_paid` | NUMERIC(20,8) | 총 수수료 |
| `detailed_metrics` | JSONB | 추가 메트릭 (JSON) |
| `created_at` | TIMESTAMPTZ | 생성 시간 |
| `updated_at` | TIMESTAMPTZ | 수정 시간 |

**인덱스**:
- `idx_backtest_results_user_id` - 사용자별 조회 최적화
- `idx_backtest_results_created_at` - 최신순 정렬 최적화
- `idx_backtest_results_user_symbol_date` - 복합 인덱스 (사용자 + 심볼 + 날짜)

### 2. backtest_trades (개별 거래 기록)

각 거래의 상세 정보를 저장합니다.

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| `id` | UUID | 기본키 |
| `backtest_id` | UUID | 백테스트 결과 ID (FK) |
| `trade_number` | INTEGER | 거래 번호 |
| `side` | VARCHAR(10) | 포지션 방향 (long, short) |
| `entry_timestamp` | TIMESTAMPTZ | 진입 시간 |
| `entry_price` | NUMERIC(20,8) | 진입 가격 |
| `exit_timestamp` | TIMESTAMPTZ | 청산 시간 |
| `exit_price` | NUMERIC(20,8) | 청산 가격 |
| `exit_reason` | VARCHAR(100) | 청산 이유 |
| `quantity` | NUMERIC(20,8) | 거래 수량 |
| `leverage` | INTEGER | 레버리지 |
| `pnl` | NUMERIC(20,8) | 손익 (절대값) |
| `pnl_percent` | NUMERIC(10,4) | 손익률 (%) |
| `entry_fee` | NUMERIC(20,8) | 진입 수수료 |
| `exit_fee` | NUMERIC(20,8) | 청산 수수료 |
| `dca_count` | INTEGER | DCA 횟수 |
| `entry_history` | JSONB | DCA 진입 이력 (JSON 배열) |
| `total_investment` | NUMERIC(20,8) | 총 투자금 |
| `is_partial_exit` | BOOLEAN | 부분 익절 여부 |
| `tp_level` | INTEGER | TP 레벨 (1, 2, 3) |
| `exit_ratio` | NUMERIC(5,2) | 청산 비율 (%) |
| `remaining_quantity` | NUMERIC(20,8) | 잔여 수량 |

**entry_history JSON 구조**:
```json
[
  {
    "price": 50000.0,
    "quantity": 0.1,
    "investment": 5000.0,
    "timestamp": "2024-01-01T10:00:00Z",
    "reason": "Initial entry",
    "dca_count": 0
  },
  {
    "price": 49500.0,
    "quantity": 0.1,
    "investment": 4950.0,
    "timestamp": "2024-01-01T11:00:00Z",
    "reason": "DCA entry 1",
    "dca_count": 1
  }
]
```

### 3. backtest_equity_curve (자산 곡선 - TimescaleDB Hypertable)

시간별 자산 변화를 저장하는 시계열 테이블입니다.

| 컬럼명 | 타입 | 설명 |
|--------|------|------|
| `backtest_id` | UUID | 백테스트 결과 ID (FK) |
| `timestamp` | TIMESTAMPTZ | 시간 (PK) |
| `balance` | NUMERIC(20,8) | 잔고 |
| `pnl` | NUMERIC(20,8) | 손익 |
| `trade_number` | INTEGER | 관련 거래 번호 |

**TimescaleDB 설정**:
- Hypertable로 변환됨 (시계열 최적화)
- Chunk 간격: 7일
- 시간 기반 파티셔닝으로 대용량 데이터 처리 최적화

## API 엔드포인트

### 1. POST `/api/backtest/save`

백테스팅 결과를 데이터베이스에 저장합니다.

**요청 본문**:
```json
{
  "userId": "user-uuid",
  "backtestResult": {
    "symbol": "BTCUSDT",
    "timeframe": "15m",
    "start_date": "2023-01-01T00:00:00Z",
    "end_date": "2024-01-01T00:00:00Z",
    "strategy_name": "hyperrsi",
    "strategy_params": { ... },
    "initial_balance": 10000,
    "final_balance": 12000,
    "total_return_percent": 20.0,
    "win_rate": 65.5,
    "trades": [ ... ],
    "equity_curve": [ ... ]
  }
}
```

**응답**:
```json
{
  "success": true,
  "backtestId": "backtest-uuid",
  "message": "백테스팅 결과가 성공적으로 저장되었습니다."
}
```

**특징**:
- 트랜잭션으로 안전하게 저장
- 메인 결과, 거래 내역, 자산 곡선을 한 번에 저장
- 저장 실패 시 자동 롤백

### 2. GET `/api/backtest/[id]`

특정 백테스팅 결과를 조회합니다 (모든 데이터 포함).

**URL 파라미터**:
- `id`: 백테스트 결과 ID (UUID)

**응답**:
```json
{
  "id": "backtest-uuid",
  "user_id": "user-uuid",
  "symbol": "BTCUSDT",
  "timeframe": "15m",
  "total_return_percent": 20.0,
  "win_rate": 65.5,
  "trades": [
    {
      "trade_number": 1,
      "side": "long",
      "entry_price": 50000,
      "exit_price": 51000,
      "pnl": 100,
      "pnl_percent": 2.0,
      "dca_count": 2,
      "entry_history": [ ... ]
    }
  ],
  "equity_curve": [
    {
      "timestamp": "2023-01-01T00:00:00Z",
      "balance": 10000,
      "pnl": 0
    }
  ]
}
```

### 3. GET `/api/backtest/list`

사용자별 백테스팅 결과 목록을 조회합니다.

**쿼리 파라미터**:
- `userId` (required): 사용자 ID
- `limit` (optional): 페이지당 개수 (기본값: 20)
- `offset` (optional): 오프셋 (기본값: 0)
- `includeStats` (optional): 통계 포함 여부 (true/false)

**요청 예시**:
```
GET /api/backtest/list?userId=user-uuid&limit=10&offset=0&includeStats=true
```

**응답**:
```json
{
  "backtests": [
    {
      "id": "backtest-uuid-1",
      "symbol": "BTCUSDT",
      "timeframe": "15m",
      "strategy_name": "hyperrsi",
      "total_return_percent": 20.0,
      "win_rate": 65.5,
      "total_trades": 100,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "stats": {
    "total_backtests": 50,
    "avg_return": 15.5,
    "best_return": 45.2,
    "worst_return": -8.5,
    "avg_win_rate": 62.3
  },
  "pagination": {
    "limit": 10,
    "offset": 0,
    "count": 10
  }
}
```

### 4. DELETE `/api/backtest/[id]`

백테스팅 결과를 삭제합니다.

**URL 파라미터**:
- `id`: 백테스트 결과 ID (UUID)

**쿼리 파라미터**:
- `userId` (required): 사용자 ID (권한 확인용)

**요청 예시**:
```
DELETE /api/backtest/backtest-uuid?userId=user-uuid
```

**응답**:
```json
{
  "success": true,
  "message": "백테스팅 결과가 성공적으로 삭제되었습니다."
}
```

**특징**:
- CASCADE 삭제: 관련된 거래 내역과 자산 곡선도 함께 삭제
- 권한 확인: userId가 일치하는 경우만 삭제 가능

## 사용 방법

### 1. 백테스팅 실행 및 자동 저장

```typescript
// 1. 백테스팅 페이지 접속
// URL: http://localhost:3009/trade/bot_list/backtest

// 2. 백테스팅 설정
// - 설정을 변경하면 자동으로 localStorage에 저장됨
// - 다음 방문 시 자동으로 마지막 설정값 복원

// 3. 백테스팅 실행
// - "백테스트 시작" 버튼 클릭
// - 백테스팅 서버(8013번 포트)에서 실행
// - 완료 시 자동으로 DB에 저장
// - 사용자에게 토스트 메시지 표시
```

### 2. 저장된 백테스팅 결과 조회

```typescript
// 사용자의 백테스팅 목록 조회
const fetchBacktestList = async (userId: string) => {
  const response = await fetch(
    `/api/backtest/list?userId=${userId}&limit=20&includeStats=true`
  );
  const data = await response.json();

  console.log('백테스팅 목록:', data.backtests);
  console.log('통계:', data.stats);
};

// 특정 백테스팅 결과 상세 조회
const fetchBacktestDetail = async (backtestId: string) => {
  const response = await fetch(`/api/backtest/${backtestId}`);
  const result = await response.json();

  console.log('총 거래 수:', result.total_trades);
  console.log('승률:', result.win_rate);
  console.log('거래 내역:', result.trades);
  console.log('자산 곡선:', result.equity_curve);
};
```

### 3. 백테스팅 결과 삭제

```typescript
const deleteBacktest = async (backtestId: string, userId: string) => {
  const response = await fetch(
    `/api/backtest/${backtestId}?userId=${userId}`,
    { method: 'DELETE' }
  );

  if (response.ok) {
    console.log('백테스팅 결과가 삭제되었습니다.');
  }
};
```

## 코드 예시

### 백테스팅 서비스 사용

**파일**: `lib/services/backtestService.ts`

```typescript
import { saveBacktestResult, getBacktestList } from '@/lib/services/backtestService';
import type { BacktestResponse } from '@/types/backtest';

// 1. 백테스팅 결과 저장
const result: BacktestResponse = {
  symbol: 'BTCUSDT',
  timeframe: '15m',
  // ... 모든 필드
};

const backtestId = await saveBacktestResult({
  userId: 'user-uuid',
  backtestResult: result,
});

// 2. 백테스팅 목록 조회
const backtests = await getBacktestList('user-uuid', 20, 0);

// 3. 통계 조회
const stats = await getBacktestStats('user-uuid');
console.log('평균 수익률:', stats?.avg_return);
```

### 프론트엔드 통합

```typescript
// 백테스팅 페이지에서 자동 저장
const handleSubmit = async (request: BacktestRequest) => {
  try {
    // 1. 백테스팅 실행
    const response = await fetch(`${BACKTEST_BACKEND_URL}/backtest/run`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
    const data: BacktestResponse = await response.json();

    // 2. DB에 자동 저장
    await fetch('/api/backtest/save', {
      method: 'POST',
      body: JSON.stringify({
        userId: currentUserId,
        backtestResult: data,
      }),
    });

    // 3. 결과 표시
    setResult(data);
    toast({ title: '백테스트 완료 및 저장 완료' });
  } catch (error) {
    toast({ title: '오류 발생', variant: 'destructive' });
  }
};
```

## 마이그레이션

### 데이터베이스 테이블 생성

```bash
# TimescaleDB에 마이그레이션 실행
psql "postgresql://tradeuser:SecurePassword123@158.247.218.188:5432/tradedb" \
  -f migrations/create_backtest_tables.sql
```

### 생성되는 객체

- ✅ 3개의 테이블 (backtest_results, backtest_trades, backtest_equity_curve)
- ✅ 10개의 인덱스 (조회 성능 최적화)
- ✅ 1개의 Hypertable (자산 곡선 시계열 최적화)
- ✅ 4개의 함수 (통계 계산, 자동 정리)
- ✅ 1개의 트리거 (updated_at 자동 업데이트)

### 테이블 확인

```bash
# 백테스팅 테이블 목록 확인
psql "postgresql://tradeuser:SecurePassword123@158.247.218.188:5432/tradedb" \
  -c "\dt backtest*"

# backtest_results 테이블 구조 확인
psql "postgresql://tradeuser:SecurePassword123@158.247.218.188:5432/tradedb" \
  -c "\d backtest_results"
```

## 성능 최적화

### 인덱스 전략

1. **사용자별 조회**: `idx_backtest_results_user_id`
2. **최신순 정렬**: `idx_backtest_results_created_at DESC`
3. **복합 조회**: `idx_backtest_results_user_symbol_date`
4. **거래 조회**: `idx_backtest_trades_backtest_id`
5. **자산 곡선**: `idx_equity_curve_backtest_id`

### TimescaleDB 최적화

- **Hypertable**: 자산 곡선 데이터를 시간 기반으로 파티셔닝
- **Chunk Size**: 7일 단위로 데이터 분할
- **압축**: 오래된 데이터 자동 압축 (선택적)
- **보존 정책**: 오래된 데이터 자동 삭제 (선택적)

### 데이터 정리

```sql
-- 사용자당 최근 100개만 유지
SELECT cleanup_old_backtest_results('user-uuid', 100);

-- 6개월 이상 된 데이터 삭제
DELETE FROM backtest_results
WHERE created_at < NOW() - INTERVAL '6 months';
```

## 보안 고려사항

1. **사용자 권한 확인**: 모든 API에서 userId 검증
2. **SQL Injection 방지**: 파라미터화된 쿼리 사용
3. **트랜잭션 안전성**: BEGIN/COMMIT/ROLLBACK 활용
4. **데이터 무결성**: Foreign Key와 Check Constraint
5. **CASCADE 삭제**: 부모 데이터 삭제 시 자식 데이터 자동 삭제

## 향후 개선 사항

- [ ] 백테스팅 결과 비교 기능
- [ ] 백테스팅 결과 공유 기능
- [ ] 최적 파라미터 자동 탐색 (Parameter Optimization)
- [ ] 백테스팅 결과 시각화 대시보드
- [ ] 백테스팅 결과 PDF 리포트 생성
- [ ] 실시간 백테스팅 진행률 표시
- [ ] 백테스팅 결과 태그/라벨링 기능

## 문제 해결

### 빠른 디버깅 체크리스트 ✅

백테스팅 결과가 저장되지 않을 때 순서대로 확인하세요:

1. ☑️ **로그인 상태**: 로그인되어 있나요?
2. ☑️ **브라우저 콘솔**: F12 → Console에서 `✅ User ID loaded` 메시지가 보이나요?
3. ☑️ **저장 로그**: `💾 Attempting to save backtest result...` 메시지가 보이나요?
4. ☑️ **User ID**: `👤 User ID: xxx-xxx-xxx` 형태로 출력되나요? (null이 아닌가요?)
5. ☑️ **API 응답**: `📥 Response status: 201` 이 보이나요?
6. ☑️ **저장 성공**: `✅ Backtest result saved to DB` 메시지가 보이나요?
7. ☑️ **토스트 메시지**: "백테스트 결과가 데이터베이스에 저장되었습니다" 메시지가 보이나요?

**하나라도 ❌ 라면 아래 상세 가이드를 참고하세요.**

### 백테스팅 결과가 저장되지 않는 경우

#### 1. 브라우저 콘솔 로그 확인

백테스팅 실행 후 브라우저 개발자 도구(F12) → Console 탭에서 다음 로그를 확인하세요:

```
✅ User ID loaded: xxx-xxx-xxx  // 사용자 인증 성공
💾 Attempting to save backtest result...  // 저장 시도
👤 User ID: xxx-xxx-xxx  // 사용자 ID 확인
📤 Sending save request to /api/backtest/save  // API 호출
📊 Backtest data: { symbol, timeframe, ... }  // 백테스트 데이터
📥 Response status: 201  // 응답 상태 (201이면 성공)
✅ Backtest result saved to DB: backtest-id  // 저장 성공
```

**문제별 해결 방법**:

**A. 사용자 인증 실패** (`⚠️ User not authenticated`)
```bash
# 해결 방법: 다시 로그인
# 페이지 새로고침 후 로그인 상태 확인
```

**B. User ID가 null** (`⚠️ User ID not available`)
```bash
# 원인: 로그인하지 않았거나 세션 만료
# 해결: /login 페이지에서 다시 로그인
```

**C. API 호출 실패** (`❌ Save failed`)
```bash
# 원인: API 서버 오류 또는 네트워크 문제
# 해결:
# 1. 브라우저 Network 탭에서 /api/backtest/save 요청 확인
# 2. Response 탭에서 에러 메시지 확인
# 3. 서버 로그 확인
```

#### 2. 사용자 인증 확인

백테스팅 페이지에서 사용자 인증을 확인합니다:

```bash
# 브라우저 콘솔에서 직접 테스트
fetch('/api/auth/verify')
  .then(r => r.json())
  .then(d => console.log('Auth:', d));

# 예상 결과:
# {
#   "success": true,
#   "user": {
#     "id": "user-uuid",
#     "email": "user@example.com",
#     "name": "User Name"
#   }
# }
```

#### 3. 네트워크 확인

브라우저 개발자 도구 → Network 탭에서:

1. `/api/backtest/save` 요청 찾기
2. Status가 `201 Created`인지 확인
3. Response 탭에서 `backtestId` 확인
4. Request Payload에서 `userId`와 `backtestResult` 확인

#### 4. DB 연결 및 데이터 확인

```bash
# TimescaleDB 연결 테스트
psql "postgresql://tradeuser:SecurePassword123@158.247.218.188:5432/tradedb" -c "SELECT 1;"

# 저장된 백테스팅 결과 확인
psql "postgresql://tradeuser:SecurePassword123@158.247.218.188:5432/tradedb" -c "SELECT id, symbol, total_return_percent, win_rate, created_at FROM backtest_results ORDER BY created_at DESC LIMIT 5;"

# 특정 사용자의 백테스팅 결과 확인
psql "postgresql://tradeuser:SecurePassword123@158.247.218.188:5432/tradedb" -c "SELECT COUNT(*) FROM backtest_results WHERE user_id = 'your-user-id';"
```

#### 5. 서버 로그 확인

```bash
# Next.js 개발 서버 로그
# 터미널에서 실행 중인 pnpm dev 로그 확인

# API 에러 확인
# "Error saving backtest result:" 메시지 찾기
```

### 설정값이 복원되지 않는 경우

1. **localStorage 확인**: 브라우저 개발자 도구 Application 탭
2. **브라우저 시크릿 모드**: 시크릿 모드에서는 localStorage 사용 불가
3. **쿠키/캐시 삭제**: localStorage가 삭제되었을 가능성

```javascript
// 브라우저 콘솔에서 확인
localStorage.getItem('backtest_settings');
```

## 참고 자료

- [TimescaleDB 공식 문서](https://docs.timescale.com/)
- [PostgreSQL JSONB 타입](https://www.postgresql.org/docs/current/datatype-json.html)
- [Next.js API Routes](https://nextjs.org/docs/app/building-your-application/routing/route-handlers)
- [localStorage API](https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage)

---

**작성일**: 2024-01-04
**버전**: 1.0.0
**담당자**: AI Assistant
