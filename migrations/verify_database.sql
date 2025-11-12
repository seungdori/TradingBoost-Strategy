-- 데이터베이스 상태 검증 스크립트
-- 사용법: psql $DATABASE_URL -f verify_database.sql

\echo '========================================';
\echo 'Database Schema Verification';
\echo '========================================';
\echo '';

-- 1. user_identifier_mappings 테이블 구조 확인
\echo '1. user_identifier_mappings 테이블 컬럼 목록:';
\echo '----------------------------------------';
SELECT
    column_name,
    data_type,
    character_maximum_length,
    column_default,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'user_identifier_mappings'
ORDER BY ordinal_position;

\echo '';
\echo '2. execution_mode 관련 컬럼 상세:';
\echo '----------------------------------------';
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'user_identifier_mappings'
AND column_name IN ('execution_mode', 'signal_bot_token', 'signal_bot_webhook_url');

\echo '';
\echo '3. 인덱스 목록:';
\echo '----------------------------------------';
SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'user_identifier_mappings'
ORDER BY indexname;

\echo '';
\echo '4. 테이블 데이터 샘플 (민감 정보 제외):';
\echo '----------------------------------------';
SELECT
    id,
    user_id,
    telegram_id,
    okx_uid IS NOT NULL as has_okx_uid,
    execution_mode,
    signal_bot_token IS NOT NULL as has_signal_token,
    signal_bot_webhook_url IS NOT NULL as has_webhook_url,
    is_active,
    created_at
FROM user_identifier_mappings
LIMIT 5;

\echo '';
\echo '========================================';
\echo 'Verification Complete';
\echo '========================================';
