-- ============================================
-- DCA 및 Partial Exit 기능 추가 마이그레이션
-- ============================================
-- 작성일: 2025-01-05
-- 설명: backtest_trades 테이블에 DCA 및 부분 익절 관련 컬럼 추가

-- backtest_trades 테이블에 DCA 관련 컬럼 추가
ALTER TABLE backtest_trades
ADD COLUMN IF NOT EXISTS dca_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS entry_history JSONB,
ADD COLUMN IF NOT EXISTS total_investment NUMERIC(20, 8),
ADD COLUMN IF NOT EXISTS is_partial_exit BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS tp_level INTEGER,
ADD COLUMN IF NOT EXISTS exit_ratio NUMERIC(5, 2),
ADD COLUMN IF NOT EXISTS remaining_quantity NUMERIC(20, 8),
ADD COLUMN IF NOT EXISTS tp1_price NUMERIC(20, 8),
ADD COLUMN IF NOT EXISTS tp2_price NUMERIC(20, 8),
ADD COLUMN IF NOT EXISTS tp3_price NUMERIC(20, 8);

-- 컬럼 설명 추가
COMMENT ON COLUMN backtest_trades.dca_count IS 'DCA 진입 횟수 (0 = 초기 진입만)';
COMMENT ON COLUMN backtest_trades.entry_history IS 'DCA 진입 이력 (JSON 배열: [{price, quantity, investment, timestamp, reason, dca_count}])';
COMMENT ON COLUMN backtest_trades.total_investment IS '총 투자금 (초기 + 모든 DCA)';
COMMENT ON COLUMN backtest_trades.is_partial_exit IS '부분 익절 여부';
COMMENT ON COLUMN backtest_trades.tp_level IS 'TP 레벨 (1, 2, 3)';
COMMENT ON COLUMN backtest_trades.exit_ratio IS '청산 비율 (0-1)';
COMMENT ON COLUMN backtest_trades.remaining_quantity IS '부분 익절 후 남은 수량';
COMMENT ON COLUMN backtest_trades.tp1_price IS 'TP1 가격';
COMMENT ON COLUMN backtest_trades.tp2_price IS 'TP2 가격';
COMMENT ON COLUMN backtest_trades.tp3_price IS 'TP3 가격';

-- 인덱스 추가 (DCA 분석용)
CREATE INDEX IF NOT EXISTS idx_btrade_dca_count ON backtest_trades(backtest_id, dca_count) WHERE dca_count > 0;
CREATE INDEX IF NOT EXISTS idx_btrade_partial_exit ON backtest_trades(backtest_id, is_partial_exit) WHERE is_partial_exit = TRUE;

-- entry_history JSON 구조 예시:
-- [
--   {
--     "price": 50000.0,
--     "quantity": 0.1,
--     "investment": 5000.0,
--     "timestamp": "2024-01-01T10:00:00Z",
--     "reason": "initial_entry",
--     "dca_count": 0
--   },
--   {
--     "price": 49500.0,
--     "quantity": 0.05,
--     "investment": 2475.0,
--     "timestamp": "2024-01-01T11:00:00Z",
--     "reason": "dca_entry",
--     "dca_count": 1
--   }
-- ]
