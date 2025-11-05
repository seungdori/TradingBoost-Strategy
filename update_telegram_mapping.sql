-- 텔레그램 ID를 서브 계정에서 메인 계정으로 변경

-- 1. 먼저 서브 계정의 텔레그램 ID를 NULL로 변경
UPDATE app_users
SET telegram_id = NULL,
    updated_at = NOW()
WHERE okx_uid = '587662504768345929';

-- 2. 메인 계정이 없으면 생성, 있으면 업데이트
INSERT INTO app_users (okx_uid, telegram_id, created_at, updated_at)
VALUES ('586156710277369942', '1709556958', NOW(), NOW())
ON CONFLICT (okx_uid)
DO UPDATE SET
    telegram_id = '1709556958',
    updated_at = NOW();

-- 3. 확인
SELECT okx_uid, telegram_id, updated_at
FROM app_users
WHERE okx_uid IN ('586156710277369942', '587662504768345929');