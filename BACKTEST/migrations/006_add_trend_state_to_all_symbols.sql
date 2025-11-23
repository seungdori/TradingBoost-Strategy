-- Migration: Add trend_state and auto_trend_state columns to all symbol tables
-- Purpose: Store calculated trend states for trading strategy
-- Created: 2025-11-22

-- Get all symbol tables and add columns dynamically
DO $$
DECLARE
    table_name TEXT;
BEGIN
    -- Loop through all tables ending with _usdt
    FOR table_name IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
        AND tablename LIKE '%_usdt'
        ORDER BY tablename
    LOOP
        -- Add trend_state column if not exists
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS trend_state INTEGER;', table_name);

        -- Add auto_trend_state column if not exists
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS auto_trend_state INTEGER;', table_name);

        RAISE NOTICE 'Added columns to table: %', table_name;
    END LOOP;
END $$;

-- Add indexes for better query performance (optional but recommended)
DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOR table_name IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
        AND tablename LIKE '%_usdt'
        ORDER BY tablename
    LOOP
        -- Create index for trend_state
        EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%I_trend_state ON %I(trend_state) WHERE trend_state IS NOT NULL;',
                      table_name, table_name);

        -- Create index for auto_trend_state
        EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%I_auto_trend_state ON %I(auto_trend_state) WHERE auto_trend_state IS NOT NULL;',
                      table_name, table_name);

        RAISE NOTICE 'Added indexes to table: %', table_name;
    END LOOP;
END $$;

-- Add comments for documentation
COMMENT ON COLUMN btc_usdt.trend_state IS 'PineScript-based trend state: -2=extreme downtrend, 0=neutral, 2=extreme uptrend';
COMMENT ON COLUMN btc_usdt.auto_trend_state IS 'PineScript auto trend state for current timeframe: -2=extreme downtrend, 0=neutral, 2=extreme uptrend';
