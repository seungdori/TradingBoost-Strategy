-- =====================================================
-- Migration: HYPERRSI Trading Statistics Tables
-- Version: 003
-- Description: Trade records and daily statistics for comprehensive trading analytics
-- Author: TradingBoost Team
-- Date: 2025-11-26
-- =====================================================

-- =====================================================
-- 1. hyperrsi_trades - Complete Trade Records
-- =====================================================
-- Records every closed trade with full details for statistics calculation

CREATE TABLE IF NOT EXISTS hyperrsi_trades (
    id BIGSERIAL PRIMARY KEY,

    -- User identification
    okx_uid VARCHAR(50) NOT NULL,
    telegram_id INTEGER,

    -- Trading target
    symbol VARCHAR(50) NOT NULL,

    -- Trade direction
    side VARCHAR(10) NOT NULL CHECK (side IN ('long', 'short')),
    is_hedge BOOLEAN NOT NULL DEFAULT FALSE,

    -- Entry information
    entry_time TIMESTAMPTZ NOT NULL,
    entry_price NUMERIC(20, 8) NOT NULL,
    entry_size NUMERIC(20, 8) NOT NULL,  -- in contracts or base currency
    entry_value NUMERIC(20, 8) NOT NULL,  -- entry_price * entry_size

    -- Exit information
    exit_time TIMESTAMPTZ NOT NULL,
    exit_price NUMERIC(20, 8) NOT NULL,
    exit_size NUMERIC(20, 8) NOT NULL,
    exit_value NUMERIC(20, 8) NOT NULL,

    -- Close type
    close_type VARCHAR(30) NOT NULL,
    /*
    close_type values:
    - 'manual' - user manual close
    - 'tp1', 'tp2', 'tp3' - take profit levels
    - 'sl' - stop loss
    - 'break_even' - break even stop
    - 'trailing_stop' - trailing stop
    - 'liquidation' - liquidation
    - 'hedge_tp', 'hedge_sl' - hedge position TP/SL
    - 'signal' - signal-based exit
    - 'force_close' - force close by system
    */

    -- Position management info
    leverage INTEGER NOT NULL DEFAULT 1,
    dca_count INTEGER NOT NULL DEFAULT 0,
    avg_entry_price NUMERIC(20, 8),  -- weighted average if DCA was used

    -- PnL information
    realized_pnl NUMERIC(20, 8) NOT NULL,  -- actual profit/loss in USDT
    realized_pnl_percent NUMERIC(10, 4) NOT NULL,  -- percentage return

    -- Fee information
    entry_fee NUMERIC(20, 8) NOT NULL DEFAULT 0,
    exit_fee NUMERIC(20, 8) NOT NULL DEFAULT 0,
    total_fee NUMERIC(20, 8) GENERATED ALWAYS AS (entry_fee + exit_fee) STORED,

    -- Net PnL (after fees)
    net_pnl NUMERIC(20, 8) GENERATED ALWAYS AS (realized_pnl - entry_fee - exit_fee) STORED,

    -- Session reference
    session_id INTEGER REFERENCES hyperrsi_sessions(id) ON DELETE SET NULL,

    -- Holding time (calculated)
    holding_seconds INTEGER GENERATED ALWAYS AS (
        EXTRACT(EPOCH FROM (exit_time - entry_time))::INTEGER
    ) STORED,

    -- Trade date for daily aggregation (based on exit time in UTC)
    trade_date DATE GENERATED ALWAYS AS (DATE(exit_time AT TIME ZONE 'UTC')) STORED,

    -- Additional data
    entry_order_id VARCHAR(100),
    exit_order_id VARCHAR(100),
    extra_data JSONB DEFAULT '{}',
    /*
    extra_data structure example:
    {
        "tp_prices": [45500, 46000, 47000],
        "sl_price": 43000,
        "partial_closes": [
            {"time": "...", "price": 45500, "size": 0.03, "pnl": 15.0}
        ],
        "signals": {
            "entry_signal": "long_entry",
            "exit_signal": "tp1_hit"
        },
        "market_conditions": {
            "entry_rsi": 28.5,
            "exit_rsi": 72.3
        }
    }
    */

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for hyperrsi_trades
CREATE INDEX IF NOT EXISTS idx_trades_okx_uid ON hyperrsi_trades(okx_uid);
CREATE INDEX IF NOT EXISTS idx_trades_okx_uid_symbol ON hyperrsi_trades(okx_uid, symbol);
CREATE INDEX IF NOT EXISTS idx_trades_okx_uid_exit_time ON hyperrsi_trades(okx_uid, exit_time DESC);
CREATE INDEX IF NOT EXISTS idx_trades_trade_date ON hyperrsi_trades(trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_trades_okx_uid_trade_date ON hyperrsi_trades(okx_uid, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_trade_date ON hyperrsi_trades(symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_trades_session ON hyperrsi_trades(session_id);
CREATE INDEX IF NOT EXISTS idx_trades_close_type ON hyperrsi_trades(close_type);

-- Comment
COMMENT ON TABLE hyperrsi_trades IS 'Complete trade records for statistics calculation - one record per closed trade';


-- =====================================================
-- 2. hyperrsi_daily_stats - Pre-aggregated Daily Statistics (Optional)
-- =====================================================
-- Pre-calculated daily statistics for faster queries on large datasets

CREATE TABLE IF NOT EXISTS hyperrsi_daily_stats (
    id SERIAL PRIMARY KEY,

    -- Dimensions
    okx_uid VARCHAR(50) NOT NULL,
    symbol VARCHAR(50),  -- NULL means all symbols aggregated
    stat_date DATE NOT NULL,

    -- Trade counts
    total_trades INTEGER NOT NULL DEFAULT 0,
    winning_trades INTEGER NOT NULL DEFAULT 0,
    losing_trades INTEGER NOT NULL DEFAULT 0,

    -- PnL metrics
    gross_pnl NUMERIC(20, 8) NOT NULL DEFAULT 0,
    total_fees NUMERIC(20, 8) NOT NULL DEFAULT 0,
    net_pnl NUMERIC(20, 8) NOT NULL DEFAULT 0,

    -- Win/Loss breakdowns
    total_win_amount NUMERIC(20, 8) NOT NULL DEFAULT 0,
    total_loss_amount NUMERIC(20, 8) NOT NULL DEFAULT 0,
    max_win NUMERIC(20, 8) NOT NULL DEFAULT 0,
    max_loss NUMERIC(20, 8) NOT NULL DEFAULT 0,

    -- Volume
    total_volume NUMERIC(20, 8) NOT NULL DEFAULT 0,  -- sum of entry_value

    -- Holding time stats (in seconds)
    avg_holding_time INTEGER DEFAULT 0,
    min_holding_time INTEGER,
    max_holding_time INTEGER,

    -- Close type breakdown
    close_type_counts JSONB DEFAULT '{}',
    /*
    Example:
    {
        "tp1": 5,
        "tp2": 3,
        "tp3": 1,
        "sl": 2,
        "trailing_stop": 4
    }
    */

    -- Running balance tracking for MDD calculation
    starting_balance NUMERIC(20, 8),
    ending_balance NUMERIC(20, 8),
    peak_balance NUMERIC(20, 8),

    -- Daily drawdown
    daily_drawdown NUMERIC(20, 8) DEFAULT 0,
    daily_drawdown_percent NUMERIC(10, 4) DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint
    CONSTRAINT uq_daily_stats_okx_symbol_date UNIQUE (okx_uid, symbol, stat_date)
);

-- Indexes for hyperrsi_daily_stats
CREATE INDEX IF NOT EXISTS idx_daily_stats_okx_uid ON hyperrsi_daily_stats(okx_uid);
CREATE INDEX IF NOT EXISTS idx_daily_stats_okx_uid_date ON hyperrsi_daily_stats(okx_uid, stat_date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_stats_okx_uid_symbol_date ON hyperrsi_daily_stats(okx_uid, symbol, stat_date DESC);

-- Apply updated_at trigger
DROP TRIGGER IF EXISTS trigger_daily_stats_updated_at ON hyperrsi_daily_stats;
CREATE TRIGGER trigger_daily_stats_updated_at
    BEFORE UPDATE ON hyperrsi_daily_stats
    FOR EACH ROW
    EXECUTE FUNCTION update_hyperrsi_updated_at();

-- Comment
COMMENT ON TABLE hyperrsi_daily_stats IS 'Pre-aggregated daily statistics for faster queries';


-- =====================================================
-- 3. Trading Statistics View (Real-time calculation)
-- =====================================================
-- View for on-the-fly statistics calculation from trades table

CREATE OR REPLACE VIEW hyperrsi_trading_stats AS
SELECT
    okx_uid,
    symbol,

    -- Basic counts
    COUNT(*) as total_trades,
    COUNT(*) FILTER (WHERE net_pnl > 0) as winning_trades,
    COUNT(*) FILTER (WHERE net_pnl < 0) as losing_trades,
    COUNT(*) FILTER (WHERE net_pnl = 0) as breakeven_trades,

    -- Win rate
    ROUND(
        (COUNT(*) FILTER (WHERE net_pnl > 0)::NUMERIC / NULLIF(COUNT(*), 0) * 100),
        2
    ) as win_rate,

    -- PnL metrics
    SUM(realized_pnl) as gross_pnl,
    SUM(total_fee) as total_fees,
    SUM(net_pnl) as net_pnl,

    -- Win/Loss breakdown
    SUM(net_pnl) FILTER (WHERE net_pnl > 0) as total_wins,
    ABS(SUM(net_pnl) FILTER (WHERE net_pnl < 0)) as total_losses,

    -- Averages
    ROUND(AVG(net_pnl), 8) as avg_pnl,
    ROUND(AVG(net_pnl) FILTER (WHERE net_pnl > 0), 8) as avg_win,
    ROUND(AVG(net_pnl) FILTER (WHERE net_pnl < 0), 8) as avg_loss,

    -- Extremes
    MAX(net_pnl) as max_win,
    MIN(net_pnl) as max_loss,

    -- Profit factor
    ROUND(
        NULLIF(SUM(net_pnl) FILTER (WHERE net_pnl > 0), 0) /
        NULLIF(ABS(SUM(net_pnl) FILTER (WHERE net_pnl < 0)), 0),
        4
    ) as profit_factor,

    -- Volume
    SUM(entry_value) as total_volume,

    -- Holding time
    ROUND(AVG(holding_seconds) / 3600.0, 2) as avg_holding_hours,
    MIN(holding_seconds) as min_holding_seconds,
    MAX(holding_seconds) as max_holding_seconds,

    -- Date range
    MIN(exit_time) as first_trade,
    MAX(exit_time) as last_trade,

    -- Close type distribution
    jsonb_object_agg(
        COALESCE(close_type, 'unknown'),
        close_type_count
    ) as close_type_distribution

FROM hyperrsi_trades
LEFT JOIN LATERAL (
    SELECT close_type as ct, COUNT(*) as close_type_count
    FROM hyperrsi_trades t2
    WHERE t2.okx_uid = hyperrsi_trades.okx_uid
    AND t2.symbol = hyperrsi_trades.symbol
    GROUP BY close_type
) close_types ON true
GROUP BY okx_uid, symbol;

-- Comment
COMMENT ON VIEW hyperrsi_trading_stats IS 'Real-time trading statistics calculated from trades';


-- =====================================================
-- 4. Function: Calculate MDD (Maximum Drawdown)
-- =====================================================

CREATE OR REPLACE FUNCTION calculate_hyperrsi_mdd(
    p_okx_uid VARCHAR(50),
    p_symbol VARCHAR(50) DEFAULT NULL,
    p_start_date DATE DEFAULT NULL,
    p_end_date DATE DEFAULT NULL,
    p_initial_balance NUMERIC DEFAULT 10000
)
RETURNS TABLE (
    max_drawdown NUMERIC,
    max_drawdown_percent NUMERIC,
    peak_balance NUMERIC,
    trough_balance NUMERIC,
    drawdown_start_date DATE,
    drawdown_end_date DATE
) AS $$
DECLARE
    v_running_balance NUMERIC := p_initial_balance;
    v_peak_balance NUMERIC := p_initial_balance;
    v_current_drawdown NUMERIC := 0;
    v_max_drawdown NUMERIC := 0;
    v_max_drawdown_percent NUMERIC := 0;
    v_trough_balance NUMERIC := p_initial_balance;
    v_drawdown_start DATE;
    v_drawdown_end DATE;
    v_current_drawdown_start DATE;
    v_trade RECORD;
BEGIN
    FOR v_trade IN
        SELECT
            trade_date,
            SUM(net_pnl) as daily_pnl
        FROM hyperrsi_trades
        WHERE okx_uid = p_okx_uid
        AND (p_symbol IS NULL OR symbol = p_symbol)
        AND (p_start_date IS NULL OR trade_date >= p_start_date)
        AND (p_end_date IS NULL OR trade_date <= p_end_date)
        GROUP BY trade_date
        ORDER BY trade_date
    LOOP
        -- Update running balance
        v_running_balance := v_running_balance + v_trade.daily_pnl;

        -- Check for new peak
        IF v_running_balance > v_peak_balance THEN
            v_peak_balance := v_running_balance;
            v_current_drawdown := 0;
            v_current_drawdown_start := NULL;
        ELSE
            -- Calculate current drawdown
            v_current_drawdown := v_peak_balance - v_running_balance;

            IF v_current_drawdown_start IS NULL THEN
                v_current_drawdown_start := v_trade.trade_date;
            END IF;

            -- Check for max drawdown
            IF v_current_drawdown > v_max_drawdown THEN
                v_max_drawdown := v_current_drawdown;
                v_max_drawdown_percent := (v_current_drawdown / v_peak_balance) * 100;
                v_trough_balance := v_running_balance;
                v_drawdown_start := v_current_drawdown_start;
                v_drawdown_end := v_trade.trade_date;
            END IF;
        END IF;
    END LOOP;

    RETURN QUERY SELECT
        v_max_drawdown,
        ROUND(v_max_drawdown_percent, 4),
        v_peak_balance,
        v_trough_balance,
        v_drawdown_start,
        v_drawdown_end;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION calculate_hyperrsi_mdd IS 'Calculate Maximum Drawdown for a given user and period';


-- =====================================================
-- 5. Function: Calculate Sharpe Ratio
-- =====================================================

CREATE OR REPLACE FUNCTION calculate_hyperrsi_sharpe_ratio(
    p_okx_uid VARCHAR(50),
    p_symbol VARCHAR(50) DEFAULT NULL,
    p_start_date DATE DEFAULT NULL,
    p_end_date DATE DEFAULT NULL,
    p_risk_free_rate NUMERIC DEFAULT 0.02,  -- 2% annual risk-free rate
    p_periods_per_year NUMERIC DEFAULT 252   -- trading days per year
)
RETURNS NUMERIC AS $$
DECLARE
    v_avg_return NUMERIC;
    v_std_return NUMERIC;
    v_daily_risk_free NUMERIC;
    v_sharpe_ratio NUMERIC;
BEGIN
    -- Calculate daily risk-free rate
    v_daily_risk_free := p_risk_free_rate / p_periods_per_year;

    -- Get average and standard deviation of daily returns
    SELECT
        AVG(daily_return),
        STDDEV_SAMP(daily_return)
    INTO v_avg_return, v_std_return
    FROM (
        SELECT
            trade_date,
            SUM(realized_pnl_percent) / 100.0 as daily_return
        FROM hyperrsi_trades
        WHERE okx_uid = p_okx_uid
        AND (p_symbol IS NULL OR symbol = p_symbol)
        AND (p_start_date IS NULL OR trade_date >= p_start_date)
        AND (p_end_date IS NULL OR trade_date <= p_end_date)
        GROUP BY trade_date
    ) daily_returns;

    -- Calculate Sharpe Ratio
    IF v_std_return IS NULL OR v_std_return = 0 THEN
        RETURN NULL;
    END IF;

    v_sharpe_ratio := ((v_avg_return - v_daily_risk_free) / v_std_return) * SQRT(p_periods_per_year);

    RETURN ROUND(v_sharpe_ratio, 4);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION calculate_hyperrsi_sharpe_ratio IS 'Calculate annualized Sharpe Ratio for a given user and period';


-- =====================================================
-- 6. Function: Get Comprehensive Trading Stats
-- =====================================================

CREATE OR REPLACE FUNCTION get_hyperrsi_trading_stats(
    p_okx_uid VARCHAR(50),
    p_symbol VARCHAR(50) DEFAULT NULL,
    p_start_date DATE DEFAULT NULL,
    p_end_date DATE DEFAULT NULL,
    p_initial_balance NUMERIC DEFAULT 10000
)
RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
    v_mdd_result RECORD;
    v_sharpe NUMERIC;
BEGIN
    -- Get MDD
    SELECT * INTO v_mdd_result
    FROM calculate_hyperrsi_mdd(p_okx_uid, p_symbol, p_start_date, p_end_date, p_initial_balance);

    -- Get Sharpe Ratio
    v_sharpe := calculate_hyperrsi_sharpe_ratio(p_okx_uid, p_symbol, p_start_date, p_end_date);

    -- Build comprehensive stats
    SELECT jsonb_build_object(
        'user_id', p_okx_uid,
        'symbol', COALESCE(p_symbol, 'ALL'),
        'period', jsonb_build_object(
            'start_date', COALESCE(p_start_date::TEXT, MIN(trade_date)::TEXT),
            'end_date', COALESCE(p_end_date::TEXT, MAX(trade_date)::TEXT)
        ),
        'summary', jsonb_build_object(
            'total_trades', COUNT(*),
            'winning_trades', COUNT(*) FILTER (WHERE net_pnl > 0),
            'losing_trades', COUNT(*) FILTER (WHERE net_pnl < 0),
            'breakeven_trades', COUNT(*) FILTER (WHERE net_pnl = 0),
            'win_rate', ROUND((COUNT(*) FILTER (WHERE net_pnl > 0)::NUMERIC / NULLIF(COUNT(*), 0) * 100), 2)
        ),
        'pnl', jsonb_build_object(
            'gross_pnl', ROUND(SUM(realized_pnl), 8),
            'total_fees', ROUND(SUM(total_fee), 8),
            'net_pnl', ROUND(SUM(net_pnl), 8),
            'total_wins', ROUND(COALESCE(SUM(net_pnl) FILTER (WHERE net_pnl > 0), 0), 8),
            'total_losses', ROUND(ABS(COALESCE(SUM(net_pnl) FILTER (WHERE net_pnl < 0), 0)), 8),
            'avg_pnl', ROUND(AVG(net_pnl), 8),
            'avg_win', ROUND(AVG(net_pnl) FILTER (WHERE net_pnl > 0), 8),
            'avg_loss', ROUND(AVG(net_pnl) FILTER (WHERE net_pnl < 0), 8),
            'max_win', ROUND(MAX(net_pnl), 8),
            'max_loss', ROUND(MIN(net_pnl), 8)
        ),
        'risk_metrics', jsonb_build_object(
            'profit_factor', ROUND(
                NULLIF(SUM(net_pnl) FILTER (WHERE net_pnl > 0), 0) /
                NULLIF(ABS(SUM(net_pnl) FILTER (WHERE net_pnl < 0)), 0),
                4
            ),
            'sharpe_ratio', v_sharpe,
            'max_drawdown', v_mdd_result.max_drawdown,
            'max_drawdown_percent', v_mdd_result.max_drawdown_percent,
            'drawdown_period', jsonb_build_object(
                'start', v_mdd_result.drawdown_start_date,
                'end', v_mdd_result.drawdown_end_date
            )
        ),
        'volume', jsonb_build_object(
            'total_volume', ROUND(SUM(entry_value), 8),
            'avg_trade_size', ROUND(AVG(entry_value), 8)
        ),
        'holding_time', jsonb_build_object(
            'avg_hours', ROUND(AVG(holding_seconds) / 3600.0, 2),
            'min_hours', ROUND(MIN(holding_seconds) / 3600.0, 2),
            'max_hours', ROUND(MAX(holding_seconds) / 3600.0, 2)
        ),
        'close_types', (
            SELECT jsonb_object_agg(close_type, cnt)
            FROM (
                SELECT close_type, COUNT(*) as cnt
                FROM hyperrsi_trades
                WHERE okx_uid = p_okx_uid
                AND (p_symbol IS NULL OR symbol = p_symbol)
                AND (p_start_date IS NULL OR trade_date >= p_start_date)
                AND (p_end_date IS NULL OR trade_date <= p_end_date)
                GROUP BY close_type
            ) ct
        ),
        'by_side', jsonb_build_object(
            'long', (
                SELECT jsonb_build_object(
                    'count', COUNT(*),
                    'win_rate', ROUND((COUNT(*) FILTER (WHERE net_pnl > 0)::NUMERIC / NULLIF(COUNT(*), 0) * 100), 2),
                    'net_pnl', ROUND(SUM(net_pnl), 8)
                )
                FROM hyperrsi_trades
                WHERE okx_uid = p_okx_uid
                AND side = 'long'
                AND (p_symbol IS NULL OR symbol = p_symbol)
                AND (p_start_date IS NULL OR trade_date >= p_start_date)
                AND (p_end_date IS NULL OR trade_date <= p_end_date)
            ),
            'short', (
                SELECT jsonb_build_object(
                    'count', COUNT(*),
                    'win_rate', ROUND((COUNT(*) FILTER (WHERE net_pnl > 0)::NUMERIC / NULLIF(COUNT(*), 0) * 100), 2),
                    'net_pnl', ROUND(SUM(net_pnl), 8)
                )
                FROM hyperrsi_trades
                WHERE okx_uid = p_okx_uid
                AND side = 'short'
                AND (p_symbol IS NULL OR symbol = p_symbol)
                AND (p_start_date IS NULL OR trade_date >= p_start_date)
                AND (p_end_date IS NULL OR trade_date <= p_end_date)
            )
        )
    ) INTO v_result
    FROM hyperrsi_trades
    WHERE okx_uid = p_okx_uid
    AND (p_symbol IS NULL OR symbol = p_symbol)
    AND (p_start_date IS NULL OR trade_date >= p_start_date)
    AND (p_end_date IS NULL OR trade_date <= p_end_date);

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_hyperrsi_trading_stats IS 'Get comprehensive trading statistics as JSON';
