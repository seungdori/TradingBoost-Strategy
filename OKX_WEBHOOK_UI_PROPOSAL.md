# OKX 웹훅 설정 페이지 UI 제안서

## 📋 개요

현재 "하이퍼 RSI DCA 봇" UI 디자인 패턴을 따라, OKX Signal Bot 설정을 위한 새로운 페이지를 제안합니다.

### 페이지 위치
- **네비게이션 추가**: 기존 메뉴에 "OKX 웹훅 설정" 또는 "실행 모드 설정" 탭 추가
- **접근성**: 메인 대시보드에서 쉽게 접근 가능한 위치

---

## 🎨 UI 레이아웃

### 전체 구조
```
┌─────────────────────────────────────────────────────────────┐
│  OKX 웹훅 설정                                              │
│  Signal Bot을 통해 OKX에 직접 신호를 전송할 수 있습니다    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  1️⃣ 기본 실행 모드                                     │  │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │  │
│  │  모든 종목에 적용될 기본 실행 모드를 선택하세요         │  │
│  │                                                          │  │
│  │  ◉ API Direct (개인 API 키 사용)                       │  │
│  │  ○ Signal Bot (OKX 웹훅 사용)                          │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  2️⃣ Signal Bot 인증 정보                               │  │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │  │
│  │  Signal Bot 모드를 사용하려면 아래 정보를 입력하세요   │  │
│  │                                                          │  │
│  │  Signal Token                                            │  │
│  │  ┌────────────────────────────────────────────────┐    │  │
│  │  │ your_okx_signal_bot_token_here               │🔑 │    │  │
│  │  └────────────────────────────────────────────────┘    │  │
│  │                                                          │  │
│  │  Webhook URL                                             │  │
│  │  ┌────────────────────────────────────────────────┐    │  │
│  │  │ https://www.okx.com/priapi/v5/trading/bot/... │    │  │
│  │  └────────────────────────────────────────────────┘    │  │
│  │                                                          │  │
│  │  💡 토큰과 URL은 OKX 웹사이트의 Signal Bot 설정에서   │  │
│  │     확인할 수 있습니다                                 │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  3️⃣ 종목별 개별 설정 (선택사항)                        │  │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │  │
│  │  특정 종목에만 다른 실행 모드를 적용할 수 있습니다     │  │
│  │                                                          │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │  🟠 BTC   USDT     Signal Bot        [×]         │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │  🔵 ETH   USDT     API Direct        [×]         │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  │                                                          │  │
│  │  [+ 종목 추가]                                          │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│                                 [취소]  [저장]              │
└─────────────────────────────────────────────────────────────┘
```

---

## 📐 상세 컴포넌트 설계

### 1️⃣ 기본 실행 모드 선택
```jsx
<Card title="1️⃣ 기본 실행 모드">
  <Description>
    모든 종목에 적용될 기본 실행 모드를 선택하세요
  </Description>

  <RadioGroup value={executionMode} onChange={setExecutionMode}>
    <Radio value="api_direct">
      <Icon>🔑</Icon>
      <Label>API Direct</Label>
      <SubLabel>개인 API 키를 사용하여 직접 거래</SubLabel>
    </Radio>

    <Radio value="signal_bot">
      <Icon>📡</Icon>
      <Label>Signal Bot</Label>
      <SubLabel>OKX Signal Bot 웹훅을 통해 거래</SubLabel>
    </Radio>
  </RadioGroup>
</Card>
```

**디자인 스펙:**
- 라디오 버튼: 큰 클릭 영역 (전체 카드)
- 선택된 항목: 파란색 테두리 + 배경색 변경
- 아이콘 + 메인 라벨 + 설명 텍스트 구조

---

### 2️⃣ Signal Bot 인증 정보
```jsx
<Card
  title="2️⃣ Signal Bot 인증 정보"
  disabled={executionMode === 'api_direct'}
>
  <Description>
    Signal Bot 모드를 사용하려면 아래 정보를 입력하세요
  </Description>

  <FormGroup>
    <Label required>Signal Token</Label>
    <Input
      type="password"
      placeholder="your_okx_signal_bot_token_here"
      value={signalToken}
      onChange={setSignalToken}
      icon={<KeyIcon />}
    />
  </FormGroup>

  <FormGroup>
    <Label required>Webhook URL</Label>
    <Input
      type="url"
      value={webhookUrl}
      onChange={setWebhookUrl}
      defaultValue="https://www.okx.com/priapi/v5/trading/bot/signal"
    />
  </FormGroup>

  <InfoBox type="info">
    💡 토큰과 URL은 OKX 웹사이트의 Signal Bot 설정에서 확인할 수 있습니다
    <Link href="https://www.okx.com/trade-bot/signal" target="_blank">
      자세히 보기 →
    </Link>
  </InfoBox>
</Card>
```

**디자인 스펙:**
- API Direct 모드 선택 시: 카드 전체 비활성화 (opacity: 0.5)
- Input 필드: 현재 UI와 동일한 스타일 (둥근 모서리, 그림자)
- 비밀번호 타입: Token 입력 시 마스킹 처리
- 기본값 제공: Webhook URL은 OKX 공식 URL 미리 채움

---

### 3️⃣ 종목별 개별 설정
```jsx
<Card title="3️⃣ 종목별 개별 설정 (선택사항)">
  <Description>
    특정 종목에만 다른 실행 모드를 적용할 수 있습니다
  </Description>

  <SymbolOverrideList>
    {symbolOverrides.map((override) => (
      <SymbolOverrideItem key={override.symbol}>
        <SymbolBadge color={getSymbolColor(override.symbol)}>
          {override.symbol.split('-')[0]}
        </SymbolBadge>

        <QuoteLabel>USDT</QuoteLabel>

        <ModeSelect
          value={override.mode}
          onChange={(mode) => updateOverride(override.symbol, mode)}
        >
          <Option value="api_direct">API Direct</Option>
          <Option value="signal_bot">Signal Bot</Option>
        </ModeSelect>

        <RemoveButton onClick={() => removeOverride(override.symbol)}>
          ×
        </RemoveButton>
      </SymbolOverrideItem>
    ))}
  </SymbolOverrideList>

  <AddSymbolButton onClick={openSymbolSelector}>
    + 종목 추가
  </AddSymbolButton>
</Card>
```

**디자인 스펙:**
- 심볼 뱃지: 현재 UI와 동일한 색상 코딩
  - BTC: 오렌지 (#F97316)
  - ETH: 다크블루 (#1E3A8A)
  - SOL: 퍼플 (#7C3AED)
- 모드 선택: 드롭다운 (select 스타일)
- 제거 버튼: 호버 시 빨간색, 오른쪽 정렬
- 추가 버튼: 점선 테두리, + 아이콘

---

### 종목 추가 모달
```jsx
<Modal title="종목 추가" visible={showSymbolSelector}>
  <SymbolGrid>
    <SymbolCard onClick={() => addSymbol('BTC-USDT-SWAP')}>
      <SymbolIcon color="orange">🟠</SymbolIcon>
      <SymbolName>BTC</SymbolName>
      <SymbolQuote>USDT</SymbolQuote>
    </SymbolCard>

    <SymbolCard onClick={() => addSymbol('ETH-USDT-SWAP')}>
      <SymbolIcon color="blue">🔵</SymbolIcon>
      <SymbolName>ETH</SymbolName>
      <SymbolQuote>USDT</SymbolQuote>
    </SymbolCard>

    <SymbolCard onClick={() => addSymbol('SOL-USDT-SWAP')}>
      <SymbolIcon color="purple">🟣</SymbolIcon>
      <SymbolName>SOL</SymbolName>
      <SymbolQuote>USDT</SymbolQuote>
    </SymbolCard>

    {/* 더 많은 종목들... */}
  </SymbolGrid>

  <ModalActions>
    <Button variant="secondary" onClick={closeModal}>취소</Button>
  </ModalActions>
</Modal>
```

**디자인 스펙:**
- 모달: 중앙 정렬, 반투명 배경 (backdrop)
- 그리드 레이아웃: 3-4개 열
- 카드 호버 효과: 그림자 강화, 약간 위로 이동

---

## 🎯 사용자 시나리오

### 시나리오 1: 모든 종목 Signal Bot 사용
1. "기본 실행 모드"에서 **Signal Bot** 선택
2. Token과 Webhook URL 입력
3. **저장** 클릭
4. ✅ 모든 종목이 Signal Bot으로 거래됨

### 시나리오 2: BTC만 Signal Bot, 나머지는 API Direct
1. "기본 실행 모드"에서 **API Direct** 선택 (기본값)
2. Signal Bot Token과 URL 입력 (Signal Bot 사용 종목을 위해)
3. "종목별 개별 설정"에서 **+ 종목 추가** 클릭
4. BTC 선택
5. BTC의 모드를 **Signal Bot**으로 변경
6. **저장** 클릭
7. ✅ BTC는 Signal Bot, ETH/SOL은 API Direct로 거래됨

### 시나리오 3: API Direct만 사용 (기존 방식)
1. "기본 실행 모드"에서 **API Direct** 선택 (기본값)
2. **저장** 클릭
3. ✅ 모든 종목이 기존 방식대로 API Direct로 거래됨

---

## ⚠️ 검증 및 에러 처리

### 폼 검증 규칙
```javascript
const validateSettings = () => {
  // 1. Signal Bot 모드 검증
  if (executionMode === 'signal_bot' || hasSignalBotSymbols()) {
    if (!signalToken.trim()) {
      return {
        valid: false,
        error: 'Signal Bot을 사용하려면 Token이 필요합니다'
      };
    }

    if (!webhookUrl.trim()) {
      return {
        valid: false,
        error: 'Signal Bot을 사용하려면 Webhook URL이 필요합니다'
      };
    }
  }

  // 2. 중복 종목 검증
  const symbols = symbolOverrides.map(o => o.symbol);
  if (new Set(symbols).size !== symbols.length) {
    return {
      valid: false,
      error: '중복된 종목이 있습니다'
    };
  }

  return { valid: true };
};
```

### 에러 메시지 표시
```jsx
{error && (
  <Alert type="error" dismissible>
    ❌ {error}
  </Alert>
)}
```

### 성공 메시지
```jsx
{saved && (
  <Alert type="success" dismissible>
    ✅ 설정이 저장되었습니다
  </Alert>
)}
```

---

## 💾 API 요청 예시

### 설정 저장 요청
```javascript
const saveSettings = async () => {
  try {
    const response = await fetch(`/api/settings/${userId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        settings: {
          execution_mode: executionMode,
          signal_bot_token: signalToken,
          signal_bot_webhook_url: webhookUrl,
          symbol_execution_modes: symbolOverrides.reduce((acc, override) => {
            acc[override.symbol] = override.mode;
            return acc;
          }, {})
        }
      })
    });

    if (!response.ok) {
      throw new Error(await response.text());
    }

    showSuccess('설정이 저장되었습니다');
  } catch (error) {
    showError(error.message);
  }
};
```

---

## 🎨 디자인 토큰

### 색상 (현재 UI 기반)
```css
--color-btc: #F97316;      /* 오렌지 */
--color-eth: #1E3A8A;      /* 다크블루 */
--color-sol: #7C3AED;      /* 퍼플 */

--color-primary: #3B82F6;  /* 파란색 (선택/액션) */
--color-success: #10B981;  /* 초록색 (성공) */
--color-danger: #EF4444;   /* 빨간색 (삭제) */
--color-warning: #F59E0B;  /* 노란색 (경고) */

--color-bg-card: #FFFFFF;
--color-border: #E5E7EB;
--color-text: #1F2937;
--color-text-secondary: #6B7280;
```

### 간격
```css
--spacing-xs: 0.5rem;   /* 8px */
--spacing-sm: 1rem;     /* 16px */
--spacing-md: 1.5rem;   /* 24px */
--spacing-lg: 2rem;     /* 32px */
--spacing-xl: 3rem;     /* 48px */
```

### 그림자
```css
--shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
--shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
--shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1);
```

---

## 📱 반응형 디자인

### 데스크톱 (1024px+)
- 3열 레이아웃
- 카드 최대 너비: 1200px
- 사이드 여백: 2rem

### 태블릿 (768px - 1023px)
- 2열 레이아웃
- 카드 최대 너비: 100%
- 사이드 여백: 1rem

### 모바일 (< 768px)
- 1열 레이아웃
- 풀 너비 카드
- 버튼 스택: 가로 → 세로 배치

---

## ✅ 체크리스트

### 개발 단계
- [ ] 기본 레이아웃 구현
- [ ] 라디오 버튼 그룹 구현
- [ ] Input 필드 구현 (Token, URL)
- [ ] 종목별 설정 리스트 구현
- [ ] 종목 추가 모달 구현
- [ ] 폼 검증 로직 구현
- [ ] API 연동 구현
- [ ] 에러/성공 메시지 구현
- [ ] 반응형 스타일 적용

### 테스트 단계
- [ ] 시나리오 1 테스트 (전체 Signal Bot)
- [ ] 시나리오 2 테스트 (일부만 Signal Bot)
- [ ] 시나리오 3 테스트 (전체 API Direct)
- [ ] 검증 로직 테스트
- [ ] 크로스 브라우저 테스트
- [ ] 모바일 반응형 테스트

---

## 📚 참고 자료

### OKX Signal Bot 문서
- [OKX Signal Bot Guide](https://www.okx.com/help/trading-bot-signal-guide)
- [Webhook Payload Format](https://www.okx.com/priapi/v5/trading/bot/signal)

### 현재 코드베이스
- `shared/constants/default_settings.py` - 설정 구조
- `HYPERRSI/src/api/routes/settings.py` - 검증 로직
- `HYPERRSI/src/trading/executors/factory.py` - Executor 선택 로직

---

## 🚀 배포 순서

1. **백엔드 API 테스트**: settings API 검증
2. **프론트엔드 개발**: UI 컴포넌트 구현
3. **통합 테스트**: 프론트-백엔드 연동 확인
4. **사용자 테스트**: 베타 테스터 피드백 수집
5. **문서화**: 사용자 가이드 작성
6. **프로덕션 배포**: 단계적 롤아웃

---

**작성일**: 2025-11-05
**버전**: 1.0
**작성자**: Claude (claude.ai/code)
