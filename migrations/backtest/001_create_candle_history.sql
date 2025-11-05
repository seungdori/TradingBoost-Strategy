-- ============================================
-- 캔들 히스토리 테이블 (시계열 데이터)
-- ============================================
-- 백테스팅을 위한 과거 캔들 데이터 저장
-- TimescaleDB의 Hypertable 기능 활용

CREATE TABLE IF NOT EXISTS candle_history (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,

    -- OHLCV 데이터
    open NUMERIC(20, 8) NOT NULL,
    high NUMERIC(20, 8) NOT NULL,
    low NUMERIC(20, 8) NOT NULL,
    close NUMERIC(20, 8) NOT NULL,
    volume NUMERIC(20, 8) NOT NULL,

    -- 인디케이터
    rsi NUMERIC(10, 2),
    atr NUMERIC(20, 8),
    ema NUMERIC(20, 8),
    sma NUMERIC(20, 8),
    bollinger_upper NUMERIC(20, 8),
    bollinger_middle NUMERIC(20, 8),
    bollinger_lower NUMERIC(20, 8),

    -- 트렌드 지표
    macd NUMERIC(20, 8),
    macd_signal NUMERIC(20, 8),
    macd_histogram NUMERIC(20, 8),

    -- 메타데이터
    data_source VARCHAR(20) DEFAULT 'okx',
    is_complete BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- 기본키: 심볼 + 타임프레임 + 타임스탬프
    PRIMARY KEY (symbol, timeframe, timestamp)
);

-- TimescaleDB Hypertable 변환 (시계열 최적화)
SELECT create_hypertable(
    'candle_history',
    'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_candle_symbol_timeframe
ON candle_history (symbol, timeframe, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_candle_timestamp
ON candle_history (timestamp DESC);

-- 데이터 보관 정책 (1년 이상 데이터 자동 삭제)
SELECT add_retention_policy(
    'candle_history',
    INTERVAL '1 year',
    if_not_exists => TRUE
);

-- 압축 정책 (7일 이상된 데이터 압축)
ALTER TABLE candle_history SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,timeframe'
);

SELECT add_compression_policy(
    'candle_history',
    INTERVAL '7 days',
    if_not_exists => TRUE
);

-- 코멘트 추가
COMMENT ON TABLE candle_history IS '백테스팅용 캔들 히스토리 데이터 (TimescaleDB Hypertable)';
COMMENT ON COLUMN candle_history.timestamp IS '캔들 타임스탬프 (UTC)';
COMMENT ON COLUMN candle_history.symbol IS '거래 심볼 (예: BTC-USDT-SWAP)';
COMMENT ON COLUMN candle_history.timeframe IS '타임프레임 (예: 1m, 5m, 1h)';
COMMENT ON COLUMN candle_history.is_complete IS '완성된 캔들 여부 (false = 진행중인 캔들)';
