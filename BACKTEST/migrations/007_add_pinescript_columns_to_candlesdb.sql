-- ============================================================
-- CandlesDB 스키마 확장: PineScript 컬럼 추가 및 새 심볼 테이블 생성
-- 적용 대상: CandlesDB (CANDLES_* 설정 사용)
-- ============================================================

-- ============================================================
-- Phase 1: 기존 테이블에 PineScript 컬럼 추가
-- ============================================================

-- BTC-USDT-SWAP (btc_usdt)
ALTER TABLE btc_usdt ADD COLUMN IF NOT EXISTS cycle_bull BOOLEAN;
ALTER TABLE btc_usdt ADD COLUMN IF NOT EXISTS cycle_bear BOOLEAN;
ALTER TABLE btc_usdt ADD COLUMN IF NOT EXISTS bb_state INTEGER;

-- ETH-USDT-SWAP (eth_usdt)
ALTER TABLE eth_usdt ADD COLUMN IF NOT EXISTS cycle_bull BOOLEAN;
ALTER TABLE eth_usdt ADD COLUMN IF NOT EXISTS cycle_bear BOOLEAN;
ALTER TABLE eth_usdt ADD COLUMN IF NOT EXISTS bb_state INTEGER;

-- SOL-USDT-SWAP (sol_usdt)
ALTER TABLE sol_usdt ADD COLUMN IF NOT EXISTS cycle_bull BOOLEAN;
ALTER TABLE sol_usdt ADD COLUMN IF NOT EXISTS cycle_bear BOOLEAN;
ALTER TABLE sol_usdt ADD COLUMN IF NOT EXISTS bb_state INTEGER;

-- ============================================================
-- Phase 2: 새 심볼 테이블 생성 (Top 10 중 추가분)
-- 기존 btc_usdt 테이블 구조를 기반으로 생성
-- ============================================================

-- XRP-USDT-SWAP (xrp_usdt)
CREATE TABLE IF NOT EXISTS xrp_usdt (
    time TIMESTAMPTZ NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    open DECIMAL(20, 8),
    high DECIMAL(20, 8),
    low DECIMAL(20, 8),
    close DECIMAL(20, 8),
    volume DECIMAL(30, 8),
    rsi14 DECIMAL(10, 4),
    atr DECIMAL(20, 8),
    ema7 DECIMAL(20, 8),
    ma20 DECIMAL(20, 8),
    trend_state INTEGER,
    auto_trend_state INTEGER,
    cycle_bull BOOLEAN,
    cycle_bear BOOLEAN,
    bb_state INTEGER,
    PRIMARY KEY (time, timeframe)
);

-- DOGE-USDT-SWAP (doge_usdt)
CREATE TABLE IF NOT EXISTS doge_usdt (
    time TIMESTAMPTZ NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    open DECIMAL(20, 8),
    high DECIMAL(20, 8),
    low DECIMAL(20, 8),
    close DECIMAL(20, 8),
    volume DECIMAL(30, 8),
    rsi14 DECIMAL(10, 4),
    atr DECIMAL(20, 8),
    ema7 DECIMAL(20, 8),
    ma20 DECIMAL(20, 8),
    trend_state INTEGER,
    auto_trend_state INTEGER,
    cycle_bull BOOLEAN,
    cycle_bear BOOLEAN,
    bb_state INTEGER,
    PRIMARY KEY (time, timeframe)
);

-- ADA-USDT-SWAP (ada_usdt)
CREATE TABLE IF NOT EXISTS ada_usdt (
    time TIMESTAMPTZ NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    open DECIMAL(20, 8),
    high DECIMAL(20, 8),
    low DECIMAL(20, 8),
    close DECIMAL(20, 8),
    volume DECIMAL(30, 8),
    rsi14 DECIMAL(10, 4),
    atr DECIMAL(20, 8),
    ema7 DECIMAL(20, 8),
    ma20 DECIMAL(20, 8),
    trend_state INTEGER,
    auto_trend_state INTEGER,
    cycle_bull BOOLEAN,
    cycle_bear BOOLEAN,
    bb_state INTEGER,
    PRIMARY KEY (time, timeframe)
);

-- AVAX-USDT-SWAP (avax_usdt)
CREATE TABLE IF NOT EXISTS avax_usdt (
    time TIMESTAMPTZ NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    open DECIMAL(20, 8),
    high DECIMAL(20, 8),
    low DECIMAL(20, 8),
    close DECIMAL(20, 8),
    volume DECIMAL(30, 8),
    rsi14 DECIMAL(10, 4),
    atr DECIMAL(20, 8),
    ema7 DECIMAL(20, 8),
    ma20 DECIMAL(20, 8),
    trend_state INTEGER,
    auto_trend_state INTEGER,
    cycle_bull BOOLEAN,
    cycle_bear BOOLEAN,
    bb_state INTEGER,
    PRIMARY KEY (time, timeframe)
);

-- LINK-USDT-SWAP (link_usdt)
CREATE TABLE IF NOT EXISTS link_usdt (
    time TIMESTAMPTZ NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    open DECIMAL(20, 8),
    high DECIMAL(20, 8),
    low DECIMAL(20, 8),
    close DECIMAL(20, 8),
    volume DECIMAL(30, 8),
    rsi14 DECIMAL(10, 4),
    atr DECIMAL(20, 8),
    ema7 DECIMAL(20, 8),
    ma20 DECIMAL(20, 8),
    trend_state INTEGER,
    auto_trend_state INTEGER,
    cycle_bull BOOLEAN,
    cycle_bear BOOLEAN,
    bb_state INTEGER,
    PRIMARY KEY (time, timeframe)
);

-- DOT-USDT-SWAP (dot_usdt)
CREATE TABLE IF NOT EXISTS dot_usdt (
    time TIMESTAMPTZ NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    open DECIMAL(20, 8),
    high DECIMAL(20, 8),
    low DECIMAL(20, 8),
    close DECIMAL(20, 8),
    volume DECIMAL(30, 8),
    rsi14 DECIMAL(10, 4),
    atr DECIMAL(20, 8),
    ema7 DECIMAL(20, 8),
    ma20 DECIMAL(20, 8),
    trend_state INTEGER,
    auto_trend_state INTEGER,
    cycle_bull BOOLEAN,
    cycle_bear BOOLEAN,
    bb_state INTEGER,
    PRIMARY KEY (time, timeframe)
);

-- MATIC-USDT-SWAP (matic_usdt) - 참고: Polygon은 POL로 리브랜딩됨
CREATE TABLE IF NOT EXISTS matic_usdt (
    time TIMESTAMPTZ NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    open DECIMAL(20, 8),
    high DECIMAL(20, 8),
    low DECIMAL(20, 8),
    close DECIMAL(20, 8),
    volume DECIMAL(30, 8),
    rsi14 DECIMAL(10, 4),
    atr DECIMAL(20, 8),
    ema7 DECIMAL(20, 8),
    ma20 DECIMAL(20, 8),
    trend_state INTEGER,
    auto_trend_state INTEGER,
    cycle_bull BOOLEAN,
    cycle_bear BOOLEAN,
    bb_state INTEGER,
    PRIMARY KEY (time, timeframe)
);

-- ============================================================
-- Phase 3: 인덱스 생성 (성능 최적화)
-- ============================================================

-- 기존 테이블 인덱스
CREATE INDEX IF NOT EXISTS idx_btc_usdt_cycle_bull ON btc_usdt(cycle_bull) WHERE cycle_bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_btc_usdt_cycle_bear ON btc_usdt(cycle_bear) WHERE cycle_bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_btc_usdt_bb_state ON btc_usdt(bb_state) WHERE bb_state IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_eth_usdt_cycle_bull ON eth_usdt(cycle_bull) WHERE cycle_bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_eth_usdt_cycle_bear ON eth_usdt(cycle_bear) WHERE cycle_bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_eth_usdt_bb_state ON eth_usdt(bb_state) WHERE bb_state IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sol_usdt_cycle_bull ON sol_usdt(cycle_bull) WHERE cycle_bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sol_usdt_cycle_bear ON sol_usdt(cycle_bear) WHERE cycle_bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sol_usdt_bb_state ON sol_usdt(bb_state) WHERE bb_state IS NOT NULL;

-- 새 테이블 인덱스
CREATE INDEX IF NOT EXISTS idx_xrp_usdt_timeframe ON xrp_usdt(timeframe);
CREATE INDEX IF NOT EXISTS idx_xrp_usdt_cycle_bull ON xrp_usdt(cycle_bull) WHERE cycle_bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_xrp_usdt_bb_state ON xrp_usdt(bb_state) WHERE bb_state IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_doge_usdt_timeframe ON doge_usdt(timeframe);
CREATE INDEX IF NOT EXISTS idx_doge_usdt_cycle_bull ON doge_usdt(cycle_bull) WHERE cycle_bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_doge_usdt_bb_state ON doge_usdt(bb_state) WHERE bb_state IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ada_usdt_timeframe ON ada_usdt(timeframe);
CREATE INDEX IF NOT EXISTS idx_ada_usdt_cycle_bull ON ada_usdt(cycle_bull) WHERE cycle_bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ada_usdt_bb_state ON ada_usdt(bb_state) WHERE bb_state IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_avax_usdt_timeframe ON avax_usdt(timeframe);
CREATE INDEX IF NOT EXISTS idx_avax_usdt_cycle_bull ON avax_usdt(cycle_bull) WHERE cycle_bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_avax_usdt_bb_state ON avax_usdt(bb_state) WHERE bb_state IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_link_usdt_timeframe ON link_usdt(timeframe);
CREATE INDEX IF NOT EXISTS idx_link_usdt_cycle_bull ON link_usdt(cycle_bull) WHERE cycle_bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_link_usdt_bb_state ON link_usdt(bb_state) WHERE bb_state IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_dot_usdt_timeframe ON dot_usdt(timeframe);
CREATE INDEX IF NOT EXISTS idx_dot_usdt_cycle_bull ON dot_usdt(cycle_bull) WHERE cycle_bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_dot_usdt_bb_state ON dot_usdt(bb_state) WHERE bb_state IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_matic_usdt_timeframe ON matic_usdt(timeframe);
CREATE INDEX IF NOT EXISTS idx_matic_usdt_cycle_bull ON matic_usdt(cycle_bull) WHERE cycle_bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_matic_usdt_bb_state ON matic_usdt(bb_state) WHERE bb_state IS NOT NULL;

-- ============================================================
-- Phase 4: 컬럼 설명 추가
-- ============================================================

COMMENT ON COLUMN btc_usdt.cycle_bull IS 'PineScript CYCLE Bull condition (JMA/T3 + VIDYA analysis)';
COMMENT ON COLUMN btc_usdt.cycle_bear IS 'PineScript CYCLE Bear condition (JMA/T3 + VIDYA analysis)';
COMMENT ON COLUMN btc_usdt.bb_state IS 'PineScript Bollinger Band Width state: -2=squeeze, 0=normal, 2=expansion';

-- 다른 테이블들도 동일한 설명 적용
COMMENT ON COLUMN eth_usdt.cycle_bull IS 'PineScript CYCLE Bull condition';
COMMENT ON COLUMN eth_usdt.cycle_bear IS 'PineScript CYCLE Bear condition';
COMMENT ON COLUMN eth_usdt.bb_state IS 'Bollinger Band Width state: -2=squeeze, 0=normal, 2=expansion';

COMMENT ON COLUMN sol_usdt.cycle_bull IS 'PineScript CYCLE Bull condition';
COMMENT ON COLUMN sol_usdt.cycle_bear IS 'PineScript CYCLE Bear condition';
COMMENT ON COLUMN sol_usdt.bb_state IS 'Bollinger Band Width state: -2=squeeze, 0=normal, 2=expansion';
