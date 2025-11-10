-- Migration: Add trend_state column to all timeframe tables
-- Purpose: Store calculated trend_state to avoid recalculation
-- Created: 2025-01-11

-- Add trend_state column to each timeframe table
ALTER TABLE okx_candles_1m ADD COLUMN IF NOT EXISTS trend_state INTEGER;
ALTER TABLE okx_candles_3m ADD COLUMN IF NOT EXISTS trend_state INTEGER;
ALTER TABLE okx_candles_5m ADD COLUMN IF NOT EXISTS trend_state INTEGER;
ALTER TABLE okx_candles_15m ADD COLUMN IF NOT EXISTS trend_state INTEGER;
ALTER TABLE okx_candles_30m ADD COLUMN IF NOT EXISTS trend_state INTEGER;
ALTER TABLE okx_candles_1h ADD COLUMN IF NOT EXISTS trend_state INTEGER;
ALTER TABLE okx_candles_2h ADD COLUMN IF NOT EXISTS trend_state INTEGER;
ALTER TABLE okx_candles_4h ADD COLUMN IF NOT EXISTS trend_state INTEGER;
ALTER TABLE okx_candles_6h ADD COLUMN IF NOT EXISTS trend_state INTEGER;
ALTER TABLE okx_candles_12h ADD COLUMN IF NOT EXISTS trend_state INTEGER;
ALTER TABLE okx_candles_1d ADD COLUMN IF NOT EXISTS trend_state INTEGER;

-- Add index for trend_state queries (optional but recommended)
CREATE INDEX IF NOT EXISTS idx_okx_candles_1m_trend_state ON okx_candles_1m(trend_state);
CREATE INDEX IF NOT EXISTS idx_okx_candles_3m_trend_state ON okx_candles_3m(trend_state);
CREATE INDEX IF NOT EXISTS idx_okx_candles_5m_trend_state ON okx_candles_5m(trend_state);
CREATE INDEX IF NOT EXISTS idx_okx_candles_15m_trend_state ON okx_candles_15m(trend_state);
CREATE INDEX IF NOT EXISTS idx_okx_candles_30m_trend_state ON okx_candles_30m(trend_state);
CREATE INDEX IF NOT EXISTS idx_okx_candles_1h_trend_state ON okx_candles_1h(trend_state);
CREATE INDEX IF NOT EXISTS idx_okx_candles_2h_trend_state ON okx_candles_2h(trend_state);
CREATE INDEX IF NOT EXISTS idx_okx_candles_4h_trend_state ON okx_candles_4h(trend_state);
CREATE INDEX IF NOT EXISTS idx_okx_candles_6h_trend_state ON okx_candles_6h(trend_state);
CREATE INDEX IF NOT EXISTS idx_okx_candles_12h_trend_state ON okx_candles_12h(trend_state);
CREATE INDEX IF NOT EXISTS idx_okx_candles_1d_trend_state ON okx_candles_1d(trend_state);

-- Add comment for documentation (PineScript 3-level system)
COMMENT ON COLUMN okx_candles_15m.trend_state IS 'PineScript-based trend state: -2=extreme downtrend, 0=neutral, 2=extreme uptrend';
