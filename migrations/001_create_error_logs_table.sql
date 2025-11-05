-- Create error_logs table for centralized error logging
-- Run this SQL in your PostgreSQL database

CREATE TABLE IF NOT EXISTS error_logs (
    id SERIAL PRIMARY KEY,

    -- Timestamp (시계열 데이터 - 중요)
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),

    -- User Information
    user_id VARCHAR(255),
    telegram_id INTEGER,

    -- Error Classification
    error_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'ERROR',
    strategy_type VARCHAR(50),

    -- Error Content
    error_message TEXT NOT NULL,
    error_details JSONB,

    -- Code Location
    module VARCHAR(255),
    function VARCHAR(255),
    traceback TEXT,

    -- Additional Metadata
    metadata JSONB,

    -- Resolution Status
    resolved INTEGER NOT NULL DEFAULT 0,  -- 0=미해결, 1=해결
    resolved_at TIMESTAMP
);

-- Create indexes for query optimization
CREATE INDEX IF NOT EXISTS idx_error_logs_timestamp ON error_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_error_logs_user_id ON error_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_error_logs_telegram_id ON error_logs(telegram_id);
CREATE INDEX IF NOT EXISTS idx_error_logs_error_type ON error_logs(error_type);
CREATE INDEX IF NOT EXISTS idx_error_logs_strategy_type ON error_logs(strategy_type);
CREATE INDEX IF NOT EXISTS idx_error_logs_severity ON error_logs(severity);
CREATE INDEX IF NOT EXISTS idx_error_logs_resolved ON error_logs(resolved);

-- Composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_error_logs_timestamp_user ON error_logs(timestamp, user_id);
CREATE INDEX IF NOT EXISTS idx_error_logs_timestamp_strategy ON error_logs(timestamp, strategy_type);

-- Add table comments
COMMENT ON TABLE error_logs IS '중앙 집중식 에러 로깅 테이블';
COMMENT ON COLUMN error_logs.timestamp IS '에러 발생 시각 (UTC)';
COMMENT ON COLUMN error_logs.user_id IS '사용자 ID (okx_uid 또는 user_id)';
COMMENT ON COLUMN error_logs.telegram_id IS '텔레그램 사용자 ID';
COMMENT ON COLUMN error_logs.error_type IS '에러 타입/카테고리';
COMMENT ON COLUMN error_logs.severity IS '심각도 (DEBUG, INFO, WARNING, ERROR, CRITICAL)';
COMMENT ON COLUMN error_logs.strategy_type IS '전략 타입 (HYPERRSI, GRID)';
COMMENT ON COLUMN error_logs.error_message IS '에러 메시지';
COMMENT ON COLUMN error_logs.error_details IS '에러 상세 정보 (JSON)';
COMMENT ON COLUMN error_logs.module IS '에러 발생 모듈';
COMMENT ON COLUMN error_logs.function IS '에러 발생 함수';
COMMENT ON COLUMN error_logs.traceback IS '스택 트레이스';
COMMENT ON COLUMN error_logs.metadata IS '추가 메타데이터 (JSON)';
COMMENT ON COLUMN error_logs.resolved IS '해결 여부 (0=미해결, 1=해결)';
COMMENT ON COLUMN error_logs.resolved_at IS '해결 시각';

-- Optional: Create a hypertable if using TimescaleDB (uncomment if needed)
-- SELECT create_hypertable('error_logs', 'timestamp', if_not_exists => TRUE);
