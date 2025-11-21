-- ============================================
-- BB_State 컬럼 추가
-- ============================================
-- BB_State: Bollinger Band State (-2, -1, 0, 2)
-- - 2: 상방 확장 (Bullish expansion)
-- - 0: 중립 (Neutral)
-- - -1: 수축 (Squeeze)
-- - -2: 하방 확장 (Bearish expansion)

ALTER TABLE candle_history
ADD COLUMN IF NOT EXISTS bb_state INTEGER DEFAULT 0;

COMMENT ON COLUMN candle_history.bb_state IS 'Bollinger Band State (-2: 하방확장, -1: 수축, 0: 중립, 2: 상방확장)';

-- 인덱스 추가 (성능 최적화)
CREATE INDEX IF NOT EXISTS idx_candle_bb_state
ON candle_history (symbol, timeframe, bb_state, timestamp DESC);
