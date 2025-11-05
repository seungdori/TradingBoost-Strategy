#!/bin/bash

# TradingBoost-Strategy 루트에서 HYPERRSI Celery 워커 중지

# 색상 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=============================================${NC}"
echo -e "${YELLOW}🛑 HYPERRSI Celery 워커 중지${NC}"
echo -e "${BLUE}=============================================${NC}"

# 스크립트 위치 확인
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HYPERRSI_DIR="$SCRIPT_DIR/HYPERRSI"

# HYPERRSI 디렉토리 존재 확인
if [ ! -d "$HYPERRSI_DIR" ]; then
    echo -e "${RED}❌ 오류: HYPERRSI 디렉토리를 찾을 수 없습니다.${NC}"
    exit 1
fi

# HYPERRSI 디렉토리로 이동하여 스크립트 실행
cd "$HYPERRSI_DIR" || exit 1

echo -e "${YELLOW}📂 작업 디렉토리: $(pwd)${NC}"
echo ""

# Celery 워커 중지 스크립트 실행
bash ./stop_celery_worker.sh

echo ""
echo -e "${BLUE}=============================================${NC}"
echo -e "${GREEN}✅ 워커 중지 완료!${NC}"
echo -e "${BLUE}=============================================${NC}"
