-- Migration: Add Signal Bot execution mode fields
-- Date: 2025-11-05
-- Description: Add execution_mode, signal_bot_token, signal_bot_webhook_url to user_identifier_mappings

-- Step 1: Add execution_mode column (default: api_direct)
ALTER TABLE user_identifier_mappings
ADD COLUMN execution_mode VARCHAR(20) DEFAULT 'api_direct' NOT NULL;

-- Step 2: Add signal_bot_token column (nullable, for Signal Bot authentication)
ALTER TABLE user_identifier_mappings
ADD COLUMN signal_bot_token VARCHAR(255) DEFAULT NULL;

-- Step 3: Add signal_bot_webhook_url column (nullable, OKX-provided webhook URL)
ALTER TABLE user_identifier_mappings
ADD COLUMN signal_bot_webhook_url VARCHAR(512) DEFAULT NULL;

-- Step 4: Create index on execution_mode for faster filtering
CREATE INDEX idx_execution_mode ON user_identifier_mappings(execution_mode);

-- Step 5: Add comments (PostgreSQL only, comment out for SQLite)
-- COMMENT ON COLUMN user_identifier_mappings.execution_mode IS '주문 실행 방식 (api_direct | signal_bot)';
-- COMMENT ON COLUMN user_identifier_mappings.signal_bot_token IS 'OKX Signal Bot Token (보안 주의: 암호화 저장 권장)';
-- COMMENT ON COLUMN user_identifier_mappings.signal_bot_webhook_url IS 'OKX Signal Bot Webhook URL';

-- Verification query (기존 유저 확인)
-- SELECT user_id, execution_mode, signal_bot_token IS NOT NULL as has_token
-- FROM user_identifier_mappings;
