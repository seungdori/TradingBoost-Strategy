#!/bin/bash
# Migration 적용 스크립트
# 사용법: ./apply_migrations.sh

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}TradingBoost Migration Tool${NC}"
echo -e "${GREEN}========================================${NC}"

# .env 파일에서 DATABASE_URL 읽기
if [ -f "../.env" ]; then
    export $(grep -v '^#' ../.env | xargs)
elif [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
else
    echo -e "${RED}❌ .env 파일을 찾을 수 없습니다${NC}"
    exit 1
fi

# DATABASE_URL 파싱 (PostgreSQL 전용)
if [[ $DATABASE_URL == postgresql* ]] || [[ $DATABASE_URL == postgres* ]]; then
    # URL에서 연결 정보 추출
    DB_TYPE="postgresql"

    # psql 명령어 구성
    PSQL_CMD="psql ${DATABASE_URL}"

    echo -e "${YELLOW}📊 데이터베이스 타입: PostgreSQL${NC}"
    echo ""

    # 마이그레이션 파일 목록
    MIGRATIONS=(
        "001_create_error_logs_table.sql"
        "002_add_signal_bot_fields.sql"
    )

    echo -e "${YELLOW}📋 적용할 마이그레이션:${NC}"
    for migration in "${MIGRATIONS[@]}"; do
        echo "  - $migration"
    done
    echo ""

    # 사용자 확인
    read -p "마이그레이션을 적용하시겠습니까? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}⏸️  마이그레이션 취소됨${NC}"
        exit 0
    fi

    # 마이그레이션 적용
    for migration in "${MIGRATIONS[@]}"; do
        if [ -f "$migration" ]; then
            echo -e "${YELLOW}🔄 적용 중: $migration${NC}"

            # 마이그레이션 실행
            if $PSQL_CMD -f "$migration" 2>&1 | tee /tmp/migration_output.log; then
                # 이미 존재하는 컬럼 오류 확인
                if grep -q "already exists" /tmp/migration_output.log; then
                    echo -e "${YELLOW}⚠️  이미 적용된 마이그레이션: $migration${NC}"
                else
                    echo -e "${GREEN}✅ 완료: $migration${NC}"
                fi
            else
                # 에러 확인
                if grep -q "already exists" /tmp/migration_output.log; then
                    echo -e "${YELLOW}⚠️  이미 적용된 마이그레이션: $migration${NC}"
                else
                    echo -e "${RED}❌ 실패: $migration${NC}"
                    echo -e "${RED}로그를 확인하세요: /tmp/migration_output.log${NC}"
                    exit 1
                fi
            fi
            echo ""
        else
            echo -e "${RED}❌ 파일을 찾을 수 없습니다: $migration${NC}"
            exit 1
        fi
    done

    # 검증
    echo -e "${YELLOW}🔍 마이그레이션 검증 중...${NC}"

    VERIFY_SQL="SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'user_identifier_mappings'
AND column_name IN ('execution_mode', 'signal_bot_token', 'signal_bot_webhook_url');"

    echo "$VERIFY_SQL" | $PSQL_CMD

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✅ 모든 마이그레이션이 완료되었습니다!${NC}"
    echo -e "${GREEN}========================================${NC}"

elif [[ $DATABASE_URL == mysql* ]]; then
    echo -e "${RED}❌ MySQL은 현재 지원되지 않습니다${NC}"
    echo -e "${YELLOW}PostgreSQL로 마이그레이션하거나 수동으로 적용하세요${NC}"
    exit 1
else
    echo -e "${RED}❌ 지원되지 않는 데이터베이스 타입: $DATABASE_URL${NC}"
    exit 1
fi
