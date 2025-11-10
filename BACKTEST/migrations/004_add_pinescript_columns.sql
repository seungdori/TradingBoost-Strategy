-- Migration: Add PineScript component columns to all timeframe tables
-- Purpose: Store CYCLE_Bull, CYCLE_Bear, BB_State for complete PineScript state
-- Created: 2025-11-09

-- Add PineScript component columns to each timeframe table
ALTER TABLE okx_candles_1m ADD COLUMN IF NOT EXISTS CYCLE_Bull BOOLEAN;
ALTER TABLE okx_candles_1m ADD COLUMN IF NOT EXISTS CYCLE_Bear BOOLEAN;
ALTER TABLE okx_candles_1m ADD COLUMN IF NOT EXISTS BB_State INTEGER;

ALTER TABLE okx_candles_3m ADD COLUMN IF NOT EXISTS CYCLE_Bull BOOLEAN;
ALTER TABLE okx_candles_3m ADD COLUMN IF NOT EXISTS CYCLE_Bear BOOLEAN;
ALTER TABLE okx_candles_3m ADD COLUMN IF NOT EXISTS BB_State INTEGER;

ALTER TABLE okx_candles_5m ADD COLUMN IF NOT EXISTS CYCLE_Bull BOOLEAN;
ALTER TABLE okx_candles_5m ADD COLUMN IF NOT EXISTS CYCLE_Bear BOOLEAN;
ALTER TABLE okx_candles_5m ADD COLUMN IF NOT EXISTS BB_State INTEGER;

ALTER TABLE okx_candles_15m ADD COLUMN IF NOT EXISTS CYCLE_Bull BOOLEAN;
ALTER TABLE okx_candles_15m ADD COLUMN IF NOT EXISTS CYCLE_Bear BOOLEAN;
ALTER TABLE okx_candles_15m ADD COLUMN IF NOT EXISTS BB_State INTEGER;

ALTER TABLE okx_candles_30m ADD COLUMN IF NOT EXISTS CYCLE_Bull BOOLEAN;
ALTER TABLE okx_candles_30m ADD COLUMN IF NOT EXISTS CYCLE_Bear BOOLEAN;
ALTER TABLE okx_candles_30m ADD COLUMN IF NOT EXISTS BB_State INTEGER;

ALTER TABLE okx_candles_1h ADD COLUMN IF NOT EXISTS CYCLE_Bull BOOLEAN;
ALTER TABLE okx_candles_1h ADD COLUMN IF NOT EXISTS CYCLE_Bear BOOLEAN;
ALTER TABLE okx_candles_1h ADD COLUMN IF NOT EXISTS BB_State INTEGER;

ALTER TABLE okx_candles_2h ADD COLUMN IF NOT EXISTS CYCLE_Bull BOOLEAN;
ALTER TABLE okx_candles_2h ADD COLUMN IF NOT EXISTS CYCLE_Bear BOOLEAN;
ALTER TABLE okx_candles_2h ADD COLUMN IF NOT EXISTS BB_State INTEGER;

ALTER TABLE okx_candles_4h ADD COLUMN IF NOT EXISTS CYCLE_Bull BOOLEAN;
ALTER TABLE okx_candles_4h ADD COLUMN IF NOT EXISTS CYCLE_Bear BOOLEAN;
ALTER TABLE okx_candles_4h ADD COLUMN IF NOT EXISTS BB_State INTEGER;

ALTER TABLE okx_candles_6h ADD COLUMN IF NOT EXISTS CYCLE_Bull BOOLEAN;
ALTER TABLE okx_candles_6h ADD COLUMN IF NOT EXISTS CYCLE_Bear BOOLEAN;
ALTER TABLE okx_candles_6h ADD COLUMN IF NOT EXISTS BB_State INTEGER;

ALTER TABLE okx_candles_12h ADD COLUMN IF NOT EXISTS CYCLE_Bull BOOLEAN;
ALTER TABLE okx_candles_12h ADD COLUMN IF NOT EXISTS CYCLE_Bear BOOLEAN;
ALTER TABLE okx_candles_12h ADD COLUMN IF NOT EXISTS BB_State INTEGER;

ALTER TABLE okx_candles_1d ADD COLUMN IF NOT EXISTS CYCLE_Bull BOOLEAN;
ALTER TABLE okx_candles_1d ADD COLUMN IF NOT EXISTS CYCLE_Bear BOOLEAN;
ALTER TABLE okx_candles_1d ADD COLUMN IF NOT EXISTS BB_State INTEGER;

ALTER TABLE okx_candles_1w ADD COLUMN IF NOT EXISTS CYCLE_Bull BOOLEAN;
ALTER TABLE okx_candles_1w ADD COLUMN IF NOT EXISTS CYCLE_Bear BOOLEAN;
ALTER TABLE okx_candles_1w ADD COLUMN IF NOT EXISTS BB_State INTEGER;

-- Add indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_okx_candles_1m_cycle_bull ON okx_candles_1m(CYCLE_Bull) WHERE CYCLE_Bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_1m_cycle_bear ON okx_candles_1m(CYCLE_Bear) WHERE CYCLE_Bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_1m_bb_state ON okx_candles_1m(BB_State) WHERE BB_State IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_okx_candles_3m_cycle_bull ON okx_candles_3m(CYCLE_Bull) WHERE CYCLE_Bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_3m_cycle_bear ON okx_candles_3m(CYCLE_Bear) WHERE CYCLE_Bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_3m_bb_state ON okx_candles_3m(BB_State) WHERE BB_State IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_okx_candles_5m_cycle_bull ON okx_candles_5m(CYCLE_Bull) WHERE CYCLE_Bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_5m_cycle_bear ON okx_candles_5m(CYCLE_Bear) WHERE CYCLE_Bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_5m_bb_state ON okx_candles_5m(BB_State) WHERE BB_State IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_okx_candles_15m_cycle_bull ON okx_candles_15m(CYCLE_Bull) WHERE CYCLE_Bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_15m_cycle_bear ON okx_candles_15m(CYCLE_Bear) WHERE CYCLE_Bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_15m_bb_state ON okx_candles_15m(BB_State) WHERE BB_State IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_okx_candles_30m_cycle_bull ON okx_candles_30m(CYCLE_Bull) WHERE CYCLE_Bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_30m_cycle_bear ON okx_candles_30m(CYCLE_Bear) WHERE CYCLE_Bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_30m_bb_state ON okx_candles_30m(BB_State) WHERE BB_State IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_okx_candles_1h_cycle_bull ON okx_candles_1h(CYCLE_Bull) WHERE CYCLE_Bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_1h_cycle_bear ON okx_candles_1h(CYCLE_Bear) WHERE CYCLE_Bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_1h_bb_state ON okx_candles_1h(BB_State) WHERE BB_State IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_okx_candles_2h_cycle_bull ON okx_candles_2h(CYCLE_Bull) WHERE CYCLE_Bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_2h_cycle_bear ON okx_candles_2h(CYCLE_Bear) WHERE CYCLE_Bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_2h_bb_state ON okx_candles_2h(BB_State) WHERE BB_State IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_okx_candles_4h_cycle_bull ON okx_candles_4h(CYCLE_Bull) WHERE CYCLE_Bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_4h_cycle_bear ON okx_candles_4h(CYCLE_Bear) WHERE CYCLE_Bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_4h_bb_state ON okx_candles_4h(BB_State) WHERE BB_State IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_okx_candles_6h_cycle_bull ON okx_candles_6h(CYCLE_Bull) WHERE CYCLE_Bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_6h_cycle_bear ON okx_candles_6h(CYCLE_Bear) WHERE CYCLE_Bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_6h_bb_state ON okx_candles_6h(BB_State) WHERE BB_State IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_okx_candles_12h_cycle_bull ON okx_candles_12h(CYCLE_Bull) WHERE CYCLE_Bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_12h_cycle_bear ON okx_candles_12h(CYCLE_Bear) WHERE CYCLE_Bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_12h_bb_state ON okx_candles_12h(BB_State) WHERE BB_State IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_okx_candles_1d_cycle_bull ON okx_candles_1d(CYCLE_Bull) WHERE CYCLE_Bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_1d_cycle_bear ON okx_candles_1d(CYCLE_Bear) WHERE CYCLE_Bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_1d_bb_state ON okx_candles_1d(BB_State) WHERE BB_State IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_okx_candles_1w_cycle_bull ON okx_candles_1w(CYCLE_Bull) WHERE CYCLE_Bull IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_1w_cycle_bear ON okx_candles_1w(CYCLE_Bear) WHERE CYCLE_Bear IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_okx_candles_1w_bb_state ON okx_candles_1w(BB_State) WHERE BB_State IS NOT NULL;

-- Add comments for documentation
COMMENT ON COLUMN okx_candles_15m.CYCLE_Bull IS 'PineScript CYCLE Bull condition (JMA/T3 + VIDYA analysis)';
COMMENT ON COLUMN okx_candles_15m.CYCLE_Bear IS 'PineScript CYCLE Bear condition (JMA/T3 + VIDYA analysis)';
COMMENT ON COLUMN okx_candles_15m.BB_State IS 'PineScript Bollinger Band Width state: -2=squeeze, 0=normal, 2=expansion';
