-- ============================================
-- timeframe enum에 '3m' 값 추가
-- ============================================
-- 실행 명령어:
-- psql -h 158.247.251.34 -p 5432 -U tradeuser -d candlesdb -f migrations/add_3m_timeframe.sql

\echo '========================================';
\echo 'Adding 3m timeframe to enum type';
\echo '========================================';
\echo '';

-- 1. 현재 enum 값 확인
\echo '1. Current timeframe enum values:';
\echo '----------------------------------------';
SELECT
    t.typname AS enum_type,
    e.enumlabel AS enum_value,
    e.enumsortorder AS sort_order
FROM pg_type t
JOIN pg_enum e ON t.oid = e.enumtypid
WHERE t.typname = 'timeframe'
ORDER BY e.enumsortorder;

\echo '';

-- 2. '3m' 값 추가 (1m 다음, 5m 이전에 위치)
\echo '2. Adding 3m value to timeframe enum...';
\echo '----------------------------------------';

-- PostgreSQL에서 enum 값을 중간에 삽입하려면 BEFORE 또는 AFTER를 사용합니다
-- '3m'을 '1m' 다음, '5m' 이전에 추가
ALTER TYPE timeframe ADD VALUE IF NOT EXISTS '3m' AFTER '1m';

\echo 'Successfully added 3m to timeframe enum!';
\echo '';

-- 3. 업데이트된 enum 값 확인
\echo '3. Updated timeframe enum values:';
\echo '----------------------------------------';
SELECT
    t.typname AS enum_type,
    e.enumlabel AS enum_value,
    e.enumsortorder AS sort_order
FROM pg_type t
JOIN pg_enum e ON t.oid = e.enumtypid
WHERE t.typname = 'timeframe'
ORDER BY e.enumsortorder;

\echo '';
\echo '========================================';
\echo 'Migration Complete!';
\echo '========================================';
\echo '';
\echo 'timeframe enum now includes: 1m, 3m, 5m, 15m, 30m, 1h, 4h, 1d, 1w';
\echo '';
