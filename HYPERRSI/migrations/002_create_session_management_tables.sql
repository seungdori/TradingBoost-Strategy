-- =====================================================
-- Migration: HYPERRSI Session Management Tables
-- Version: 002
-- Description: Trading session lifecycle, current bot state, and state change audit log
-- Author: TradingBoost Team
-- Date: 2025-11-26
-- =====================================================

-- =====================================================
-- 1. hyperrsi_sessions - Trading Session Lifecycle
-- =====================================================
-- Records trading sessions from start to end with settings snapshot

CREATE TABLE IF NOT EXISTS hyperrsi_sessions (
    id SERIAL PRIMARY KEY,

    -- User identification
    okx_uid VARCHAR(50) NOT NULL,
    telegram_id INTEGER,

    -- Trading target
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,

    -- Session state
    status VARCHAR(20) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'stopped', 'error')),

    -- Time information (UTC)
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,

    -- Settings snapshot at session start
    params_settings JSONB NOT NULL DEFAULT '{}',
    dual_side_settings JSONB NOT NULL DEFAULT '{}',

    -- Final settings at session end
    final_settings JSONB,

    -- End reason
    end_reason VARCHAR(50),  -- 'manual', 'error', 'system'
    error_message TEXT,

    -- Session statistics (calculated at end)
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    total_pnl DECIMAL(20, 8) DEFAULT 0,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for hyperrsi_sessions
CREATE INDEX IF NOT EXISTS idx_sessions_okx_uid ON hyperrsi_sessions(okx_uid);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON hyperrsi_sessions(status) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON hyperrsi_sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_okx_uid_symbol ON hyperrsi_sessions(okx_uid, symbol);
CREATE INDEX IF NOT EXISTS idx_sessions_okx_uid_status ON hyperrsi_sessions(okx_uid, status);

-- Comment
COMMENT ON TABLE hyperrsi_sessions IS 'Trading session lifecycle - one record per bot start/stop cycle';


-- =====================================================
-- 2. hyperrsi_current - Current Active Bot State (PostgreSQL is SSOT)
-- =====================================================
-- Real-time bot state with position, TP/SL, hedge information

CREATE TABLE IF NOT EXISTS hyperrsi_current (
    id SERIAL PRIMARY KEY,

    -- User identification
    okx_uid VARCHAR(50) NOT NULL,
    telegram_id INTEGER,

    -- Trading target
    symbol VARCHAR(50) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,

    -- Bot state
    is_running BOOLEAN NOT NULL DEFAULT FALSE,
    session_id INTEGER REFERENCES hyperrsi_sessions(id) ON DELETE SET NULL,

    -- Current settings
    params_settings JSONB NOT NULL DEFAULT '{}',
    dual_side_settings JSONB NOT NULL DEFAULT '{}',

    -- Position state (flexible JSON structure)
    position_long JSONB,
    /*
    position_long/short structure:
    {
        "entry_price": 45000.00,
        "avg_price": 44800.00,
        "size": 0.1,
        "contracts": 1,
        "leverage": 10,
        "dca_count": 2,
        "tp_state": 0,  -- 0: not triggered, 1: TP1, 2: TP2, 3: TP3
        "tp_prices": [45500, 46000, 47000],
        "sl_price": 43000,
        "break_even_active": false,
        "trailing_active": false,
        "trailing_stop_price": null,
        "unrealized_pnl": 50.25,
        "last_update": "2025-11-26T10:00:00Z"
    }
    */
    position_short JSONB,

    -- Hedge position (dual-side trading)
    hedge_position JSONB,
    /*
    hedge_position structure:
    {
        "side": "short",  -- opposite of main position
        "entry_price": 45100.00,
        "size": 0.05,
        "dca_index": 3,  -- which DCA triggered hedge
        "dual_side_count": 1,  -- hedge entry count
        "tp_price": 44500,
        "sl_price": 45500
    }
    */

    -- Last execution info
    last_execution_at TIMESTAMPTZ,
    last_signal VARCHAR(30),  -- 'long_entry', 'short_exit', 'dca_long', etc.

    -- Daily statistics
    trades_today INTEGER DEFAULT 0,
    pnl_today DECIMAL(20, 8) DEFAULT 0,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint (one record per user+symbol)
    CONSTRAINT uq_current_okx_uid_symbol UNIQUE (okx_uid, symbol)
);

-- Indexes for hyperrsi_current
CREATE INDEX IF NOT EXISTS idx_current_okx_uid ON hyperrsi_current(okx_uid);
CREATE INDEX IF NOT EXISTS idx_current_is_running ON hyperrsi_current(is_running) WHERE is_running = TRUE;
CREATE INDEX IF NOT EXISTS idx_current_session_id ON hyperrsi_current(session_id);

-- Comment
COMMENT ON TABLE hyperrsi_current IS 'Current active bot state - PostgreSQL is SSOT, Redis is cache';


-- =====================================================
-- 3. hyperrsi_state_changes - State Change Audit Log (Monthly Partitioned)
-- =====================================================
-- All state changes for audit trail (1 year retention)

CREATE TABLE IF NOT EXISTS hyperrsi_state_changes (
    id BIGSERIAL,
    change_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Context
    okx_uid VARCHAR(50) NOT NULL,
    session_id INTEGER,
    symbol VARCHAR(50) NOT NULL,

    -- Change type
    change_type VARCHAR(50) NOT NULL,
    /*
    change_type values:
    -- Session related
    'session_started', 'session_stopped', 'session_error'

    -- Position related
    'position_opened', 'position_closed', 'dca_executed', 'position_partial_close'

    -- TP/SL related
    'tp1_hit', 'tp2_hit', 'tp3_hit', 'sl_hit'
    'break_even_activated', 'trailing_activated', 'trailing_updated'

    -- Hedge related
    'hedge_opened', 'hedge_closed', 'hedge_tp_hit', 'hedge_sl_hit'

    -- Settings related
    'settings_updated', 'dual_side_updated', 'leverage_changed'

    -- Order related
    'order_placed', 'order_filled', 'order_cancelled'
    */

    -- Change content (before/after state)
    previous_state JSONB,
    new_state JSONB,

    -- Price/PnL info
    price_at_change DECIMAL(20, 8),
    pnl_at_change DECIMAL(20, 8),
    pnl_percent DECIMAL(10, 4),

    -- Trigger info
    triggered_by VARCHAR(30) NOT NULL DEFAULT 'system',
    /*
    triggered_by values:
    'user' - direct user action (telegram bot)
    'celery' - Celery task
    'websocket' - position_monitor WebSocket
    'exchange' - exchange event
    'system' - internal system
    */
    trigger_source VARCHAR(100),  -- specific source (e.g., 'telegram_bot', 'trading_tasks.py')

    -- Additional data
    metadata JSONB DEFAULT '{}',

    -- Primary key includes partition key
    PRIMARY KEY (id, change_time)
) PARTITION BY RANGE (change_time);

-- Create monthly partitions (12 months)
CREATE TABLE IF NOT EXISTS hyperrsi_state_changes_2025_11 PARTITION OF hyperrsi_state_changes
    FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
CREATE TABLE IF NOT EXISTS hyperrsi_state_changes_2025_12 PARTITION OF hyperrsi_state_changes
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');
CREATE TABLE IF NOT EXISTS hyperrsi_state_changes_2026_01 PARTITION OF hyperrsi_state_changes
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE IF NOT EXISTS hyperrsi_state_changes_2026_02 PARTITION OF hyperrsi_state_changes
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE IF NOT EXISTS hyperrsi_state_changes_2026_03 PARTITION OF hyperrsi_state_changes
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS hyperrsi_state_changes_2026_04 PARTITION OF hyperrsi_state_changes
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE IF NOT EXISTS hyperrsi_state_changes_2026_05 PARTITION OF hyperrsi_state_changes
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS hyperrsi_state_changes_2026_06 PARTITION OF hyperrsi_state_changes
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE IF NOT EXISTS hyperrsi_state_changes_2026_07 PARTITION OF hyperrsi_state_changes
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE IF NOT EXISTS hyperrsi_state_changes_2026_08 PARTITION OF hyperrsi_state_changes
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE IF NOT EXISTS hyperrsi_state_changes_2026_09 PARTITION OF hyperrsi_state_changes
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE IF NOT EXISTS hyperrsi_state_changes_2026_10 PARTITION OF hyperrsi_state_changes
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');

-- Indexes for hyperrsi_state_changes
CREATE INDEX IF NOT EXISTS idx_state_changes_okx_uid_time ON hyperrsi_state_changes(okx_uid, change_time DESC);
CREATE INDEX IF NOT EXISTS idx_state_changes_session ON hyperrsi_state_changes(session_id, change_time DESC);
CREATE INDEX IF NOT EXISTS idx_state_changes_type ON hyperrsi_state_changes(change_type, change_time DESC);
CREATE INDEX IF NOT EXISTS idx_state_changes_symbol ON hyperrsi_state_changes(symbol, change_time DESC);

-- Comment
COMMENT ON TABLE hyperrsi_state_changes IS 'State change audit log - all state changes for 1 year retention';


-- =====================================================
-- 4. updated_at Trigger Function
-- =====================================================

CREATE OR REPLACE FUNCTION update_hyperrsi_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to sessions table
DROP TRIGGER IF EXISTS trigger_sessions_updated_at ON hyperrsi_sessions;
CREATE TRIGGER trigger_sessions_updated_at
    BEFORE UPDATE ON hyperrsi_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_hyperrsi_updated_at();

-- Apply trigger to current state table
DROP TRIGGER IF EXISTS trigger_current_updated_at ON hyperrsi_current;
CREATE TRIGGER trigger_current_updated_at
    BEFORE UPDATE ON hyperrsi_current
    FOR EACH ROW
    EXECUTE FUNCTION update_hyperrsi_updated_at();


-- =====================================================
-- 5. Partition Management Function
-- =====================================================

CREATE OR REPLACE FUNCTION create_hyperrsi_state_changes_partition(
    p_year INTEGER,
    p_month INTEGER
)
RETURNS TEXT AS $$
DECLARE
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
BEGIN
    partition_name := format('hyperrsi_state_changes_%s_%s',
                            p_year,
                            LPAD(p_month::TEXT, 2, '0'));

    start_date := make_date(p_year, p_month, 1);
    end_date := start_date + INTERVAL '1 month';

    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF hyperrsi_state_changes
         FOR VALUES FROM (%L) TO (%L)',
        partition_name,
        start_date,
        end_date
    );

    RETURN partition_name;
END;
$$ LANGUAGE plpgsql;

-- Comment
COMMENT ON FUNCTION create_hyperrsi_state_changes_partition IS 'Creates a monthly partition for state_changes table';


-- =====================================================
-- 6. Data Retention Function (1 year)
-- =====================================================

CREATE OR REPLACE FUNCTION cleanup_old_hyperrsi_state_changes(
    retention_months INTEGER DEFAULT 12
)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER := 0;
    partition_name TEXT;
    cutoff_date DATE;
BEGIN
    cutoff_date := CURRENT_DATE - (retention_months || ' months')::INTERVAL;

    -- Find and drop old partitions
    FOR partition_name IN
        SELECT tablename
        FROM pg_tables
        WHERE tablename LIKE 'hyperrsi_state_changes_%'
          AND schemaname = 'public'
          AND tablename != 'hyperrsi_state_changes'
    LOOP
        DECLARE
            partition_date DATE;
            year_month TEXT;
        BEGIN
            -- Extract year_month from partition name (e.g., hyperrsi_state_changes_2025_11)
            year_month := SUBSTRING(partition_name FROM 'hyperrsi_state_changes_(\d{4}_\d{2})');

            IF year_month IS NOT NULL THEN
                partition_date := TO_DATE(year_month, 'YYYY_MM');

                IF partition_date < cutoff_date THEN
                    EXECUTE format('DROP TABLE IF EXISTS %I', partition_name);
                    deleted_count := deleted_count + 1;
                    RAISE NOTICE 'Dropped partition: %', partition_name;
                END IF;
            END IF;
        EXCEPTION
            WHEN OTHERS THEN
                -- Skip partitions with invalid names
                RAISE NOTICE 'Skipping partition with invalid name: %', partition_name;
        END;
    END LOOP;

    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Comment
COMMENT ON FUNCTION cleanup_old_hyperrsi_state_changes IS 'Drops partitions older than retention_months (default 12)';


-- =====================================================
-- 7. Session Statistics View
-- =====================================================

CREATE OR REPLACE VIEW hyperrsi_session_stats AS
SELECT
    okx_uid,
    COUNT(*) as total_sessions,
    COUNT(*) FILTER (WHERE status = 'stopped' AND total_pnl > 0) as profitable_sessions,
    COUNT(*) FILTER (WHERE status = 'stopped' AND total_pnl < 0) as losing_sessions,
    COUNT(*) FILTER (WHERE status = 'running') as active_sessions,
    SUM(total_pnl) as total_pnl,
    AVG(total_pnl) FILTER (WHERE total_pnl > 0) as avg_win,
    AVG(total_pnl) FILTER (WHERE total_pnl < 0) as avg_loss,
    MAX(total_pnl) as best_session,
    MIN(total_pnl) as worst_session,
    SUM(total_trades) as total_trades,
    SUM(winning_trades) as total_winning_trades,
    AVG(EXTRACT(EPOCH FROM (COALESCE(ended_at, NOW()) - started_at))/3600) as avg_session_hours
FROM hyperrsi_sessions
GROUP BY okx_uid;

-- Comment
COMMENT ON VIEW hyperrsi_session_stats IS 'Aggregated session statistics per user';
