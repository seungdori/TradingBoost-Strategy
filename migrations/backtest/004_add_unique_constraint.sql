-- ============================================
-- 백테스트 중복 실행 방지를 위한 UNIQUE 제약 조건 추가
-- ============================================

-- 동일한 설정으로 중복 백테스트 방지
-- (user_id, symbol, timeframe, start_date, end_date, strategy_params 조합이 유일해야 함)
CREATE UNIQUE INDEX IF NOT EXISTS idx_backtest_unique
ON backtest_runs (
    COALESCE(user_id::text, 'NULL'),  -- NULL을 문자열로 변환
    symbol,
    timeframe,
    start_date,
    end_date,
    md5(strategy_params::text)  -- JSONB를 해시로 변환 (성능 향상)
);

-- 주석 추가
COMMENT ON INDEX idx_backtest_unique IS '동일 설정 중복 백테스트 방지 (ON CONFLICT 지원)';
