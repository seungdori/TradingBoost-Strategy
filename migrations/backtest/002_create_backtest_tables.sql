-- ============================================
-- 백테스트 실행 기록 테이블
-- ============================================

CREATE TABLE IF NOT EXISTS backtest_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,  -- NULLABLE: 백테스트는 실제 사용자 없이도 실행 가능

    -- 백테스트 설정
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    start_date TIMESTAMPTZ NOT NULL,
    end_date TIMESTAMPTZ NOT NULL,

    -- 전략 설정 (JSONB로 유연하게 저장)
    strategy_name VARCHAR(50) DEFAULT 'hyperrsi',
    strategy_params JSONB NOT NULL,

    -- 실행 상태
    status VARCHAR(20) DEFAULT 'pending',  -- pending, running, completed, failed
    progress NUMERIC(5, 2) DEFAULT 0.0,

    -- 실행 시간
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    execution_time_seconds NUMERIC(10, 2),

    -- 결과 요약 (빠른 조회용)
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    total_return_percent NUMERIC(10, 2),
    max_drawdown_percent NUMERIC(10, 2),
    sharpe_ratio NUMERIC(10, 4),
    win_rate NUMERIC(5, 2),

    -- 상세 결과 (JSONB)
    detailed_metrics JSONB,

    -- 에러 정보
    error_message TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_user ON backtest_runs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_status ON backtest_runs(status);
CREATE INDEX IF NOT EXISTS idx_backtest_symbol ON backtest_runs(symbol, timeframe);

COMMENT ON TABLE backtest_runs IS '백테스트 실행 기록';
COMMENT ON COLUMN backtest_runs.strategy_params IS '전략 파라미터 (JSON)';
COMMENT ON COLUMN backtest_runs.detailed_metrics IS '상세 성능 지표 (JSON)';

-- ============================================
-- 백테스트 거래 내역 테이블
-- ============================================

CREATE TABLE IF NOT EXISTS backtest_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backtest_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,

    -- 거래 정보
    trade_number INTEGER NOT NULL,
    side VARCHAR(10) NOT NULL,  -- long, short

    -- 진입
    entry_timestamp TIMESTAMPTZ NOT NULL,
    entry_price NUMERIC(20, 8) NOT NULL,
    entry_reason VARCHAR(100),

    -- 청산
    exit_timestamp TIMESTAMPTZ,
    exit_price NUMERIC(20, 8),
    exit_reason VARCHAR(100),  -- take_profit, stop_loss, trailing_stop, signal

    -- 수량 및 손익
    quantity NUMERIC(20, 8) NOT NULL,
    leverage NUMERIC(5, 2) NOT NULL,

    pnl NUMERIC(20, 8),
    pnl_percent NUMERIC(10, 4),

    -- 수수료
    entry_fee NUMERIC(20, 8) DEFAULT 0,
    exit_fee NUMERIC(20, 8) DEFAULT 0,

    -- TP/SL 레벨
    take_profit_price NUMERIC(20, 8),
    stop_loss_price NUMERIC(20, 8),
    trailing_stop_price NUMERIC(20, 8),

    -- 진입 시점의 지표값
    entry_rsi NUMERIC(10, 2),
    entry_atr NUMERIC(20, 8),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_btrade_run ON backtest_trades(backtest_id, trade_number);
CREATE INDEX IF NOT EXISTS idx_btrade_timestamp ON backtest_trades(entry_timestamp);

COMMENT ON TABLE backtest_trades IS '백테스트 거래 내역';
COMMENT ON COLUMN backtest_trades.exit_reason IS '청산 사유 (TP/SL/신호 등)';

-- ============================================
-- 백테스트 잔고 스냅샷 (Equity Curve 데이터)
-- ============================================

CREATE TABLE IF NOT EXISTS backtest_balance_snapshots (
    id BIGSERIAL PRIMARY KEY,
    backtest_id UUID NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,

    timestamp TIMESTAMPTZ NOT NULL,
    balance NUMERIC(20, 8) NOT NULL,
    equity NUMERIC(20, 8) NOT NULL,  -- balance + unrealized PNL

    -- 포지션 정보
    position_side VARCHAR(10),  -- NULL if no position
    position_size NUMERIC(20, 8),
    unrealized_pnl NUMERIC(20, 8) DEFAULT 0,

    -- 누적 통계
    cumulative_pnl NUMERIC(20, 8),
    cumulative_trades INTEGER DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_balance_run ON backtest_balance_snapshots(backtest_id, timestamp);

COMMENT ON TABLE backtest_balance_snapshots IS '백테스트 잔고 변화 기록 (Equity Curve)';

-- TimescaleDB Hypertable 변환 제거 (일반 테이블로 사용)
-- 필요시 추가: PRIMARY KEY를 (id, timestamp)로 변경 후 hypertable 적용 가능
