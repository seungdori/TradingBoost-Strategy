-- ============================================
-- 백테스트 테이블에서 user_id 외래 키 제약 조건 제거
-- ============================================

-- 외래 키 제약 조건 제거 (존재하는 경우만)
ALTER TABLE backtest_runs
DROP CONSTRAINT IF EXISTS backtest_runs_user_id_fkey;

-- user_id를 NULLABLE로 변경
ALTER TABLE backtest_runs
ALTER COLUMN user_id DROP NOT NULL;

-- 주석 추가
COMMENT ON COLUMN backtest_runs.user_id IS '사용자 ID (선택사항: 백테스트는 실제 사용자 없이도 실행 가능)';
