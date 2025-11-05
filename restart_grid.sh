#!/bin/bash

# TradingBoost-Strategy 루트에서 GRID 전략 서버 재시작

# 색상 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=============================================${NC}"
echo -e "${YELLOW}🔄 GRID 전략 서버 재시작${NC}"
echo -e "${BLUE}=============================================${NC}"

# 스크립트 위치 확인
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${YELLOW}⏸️  서버 중지 중...${NC}"
bash "$SCRIPT_DIR/stop_grid.sh"

echo ""
echo -e "${GREEN}⏳ 2초 대기...${NC}"
sleep 2

echo ""
echo -e "${GREEN}▶️  서버 시작 중...${NC}"
bash "$SCRIPT_DIR/start_grid.sh"

echo ""
echo -e "${BLUE}=============================================${NC}"
echo -e "${GREEN}✅ GRID 서버 재시작 완료!${NC}"
echo -e "${BLUE}=============================================${NC}"
