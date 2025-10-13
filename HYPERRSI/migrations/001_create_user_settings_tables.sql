-- =====================================================
-- Migration: Create user settings tables
-- Description: TimescaleDB tables for user trading settings
-- Author: TradingBoost Team
-- Date: 2025-10-13
-- =====================================================

-- =====================================================
-- 1. User Settings Table (통합 설정 테이블)
-- =====================================================
-- 사용자의 모든 트레이딩 설정을 JSONB로 저장
-- setting_type으로 구분: 'preferences', 'params', 'dual_side'

CREATE TABLE IF NOT EXISTS user_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    okx_uid TEXT NOT NULL,
    telegram_id TEXT,

    -- 설정 타입: 'preferences', 'params', 'dual_side'
    setting_type TEXT NOT NULL,

    -- 설정 데이터 (JSONB로 유연하게 저장)
    settings JSONB NOT NULL DEFAULT '{}',

    -- 메타데이터
    version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- 타임스탬프
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,

    -- Foreign key to app_users
    CONSTRAINT fk_user_settings_user
        FOREIGN KEY (user_id)
        REFERENCES app_users(id)
        ON DELETE CASCADE
);

-- =====================================================
-- 2. Indexes for Performance
-- =====================================================

-- 사용자 ID로 빠른 조회
CREATE INDEX IF NOT EXISTS idx_user_settings_user_id
    ON user_settings(user_id)
    WHERE deleted_at IS NULL;

-- OKX UID로 빠른 조회
CREATE INDEX IF NOT EXISTS idx_user_settings_okx_uid
    ON user_settings(okx_uid)
    WHERE deleted_at IS NULL;

-- Telegram ID로 빠른 조회
CREATE INDEX IF NOT EXISTS idx_user_settings_telegram_id
    ON user_settings(telegram_id)
    WHERE deleted_at IS NULL;

-- 설정 타입별 조회
CREATE INDEX IF NOT EXISTS idx_user_settings_type
    ON user_settings(user_id, setting_type)
    WHERE deleted_at IS NULL AND is_active = TRUE;

-- JSONB 설정 내부 검색을 위한 GIN 인덱스
CREATE INDEX IF NOT EXISTS idx_user_settings_jsonb
    ON user_settings USING GIN (settings);

-- 복합 유니크 인덱스: 사용자당 각 타입별로 하나의 활성 설정만 가능
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_settings_unique_active
    ON user_settings(user_id, setting_type)
    WHERE deleted_at IS NULL AND is_active = TRUE;

-- =====================================================
-- 3. Trigger for Updated_at Auto-update
-- =====================================================

CREATE OR REPLACE FUNCTION update_user_settings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_user_settings_updated_at
    BEFORE UPDATE ON user_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_user_settings_updated_at();

-- =====================================================
-- 4. Helper Functions
-- =====================================================

-- 사용자 설정 조회 함수
CREATE OR REPLACE FUNCTION get_user_settings(
    p_identifier TEXT,
    p_setting_type TEXT DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    user_id UUID,
    okx_uid TEXT,
    telegram_id TEXT,
    setting_type TEXT,
    settings JSONB,
    version INTEGER,
    is_active BOOLEAN,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        us.id,
        us.user_id,
        us.okx_uid,
        us.telegram_id,
        us.setting_type,
        us.settings,
        us.version,
        us.is_active,
        us.created_at,
        us.updated_at
    FROM user_settings us
    INNER JOIN app_users au ON us.user_id = au.id
    WHERE us.deleted_at IS NULL
      AND us.is_active = TRUE
      AND (
            au.okx_uid = p_identifier
         OR us.telegram_id = p_identifier
         OR au.telegram_id = p_identifier
         OR au.id::text = p_identifier
      )
      AND (p_setting_type IS NULL OR us.setting_type = p_setting_type)
    ORDER BY us.updated_at DESC;
END;
$$ LANGUAGE plpgsql;

-- 사용자 설정 업서트 함수
CREATE OR REPLACE FUNCTION upsert_user_settings(
    p_user_id UUID,
    p_okx_uid TEXT,
    p_telegram_id TEXT,
    p_setting_type TEXT,
    p_settings JSONB
)
RETURNS UUID AS $$
DECLARE
    v_setting_id UUID;
BEGIN
    -- 기존 설정이 있는지 확인
    SELECT id INTO v_setting_id
    FROM user_settings
    WHERE user_id = p_user_id
      AND setting_type = p_setting_type
      AND deleted_at IS NULL
      AND is_active = TRUE
    LIMIT 1;

    IF v_setting_id IS NOT NULL THEN
        -- 기존 설정 업데이트
        UPDATE user_settings
        SET settings = p_settings,
            version = version + 1,
            updated_at = NOW()
        WHERE id = v_setting_id;
    ELSE
        -- 새 설정 삽입
        INSERT INTO user_settings (
            user_id,
            okx_uid,
            telegram_id,
            setting_type,
            settings
        )
        VALUES (
            p_user_id,
            p_okx_uid,
            p_telegram_id,
            p_setting_type,
            p_settings
        )
        RETURNING id INTO v_setting_id;
    END IF;

    RETURN v_setting_id;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- 5. Comments for Documentation
-- =====================================================

COMMENT ON TABLE user_settings IS 'User trading settings and preferences stored in flexible JSONB format';
COMMENT ON COLUMN user_settings.setting_type IS 'Type of setting: preferences, params, or dual_side';
COMMENT ON COLUMN user_settings.settings IS 'JSONB data containing all setting key-value pairs';
COMMENT ON COLUMN user_settings.version IS 'Version number for tracking setting changes';
COMMENT ON COLUMN user_settings.is_active IS 'Whether this setting configuration is currently active';

-- =====================================================
-- 6. Verification Query
-- =====================================================

-- 테이블 생성 확인
SELECT
    tablename,
    schemaname,
    tableowner
FROM pg_tables
WHERE tablename = 'user_settings';

-- 인덱스 생성 확인
SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'user_settings';
