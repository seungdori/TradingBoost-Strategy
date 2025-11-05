#!/bin/bash

# TradingBoost-Strategy 루트에서 GRID 전략 서버 시작

# 색상 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=============================================${NC}"
echo -e "${GREEN}🚀 GRID 전략 서버 시작${NC}"
echo -e "${BLUE}=============================================${NC}"

# 스크립트 위치 확인
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRID_DIR="$SCRIPT_DIR/GRID"

# GRID 디렉토리 존재 확인
if [ ! -d "$GRID_DIR" ]; then
    echo -e "${RED}❌ 오류: GRID 디렉토리를 찾을 수 없습니다.${NC}"
    exit 1
fi

# 프로젝트 루트로 이동 (PYTHONPATH 설정 위해)
cd "$SCRIPT_DIR" || exit 1

# 기존 프로세스 확인
if [ -f "$GRID_DIR/.grid_pid" ]; then
    OLD_PID=$(cat "$GRID_DIR/.grid_pid")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  이미 실행 중인 GRID 서버가 있습니다 (PID: $OLD_PID)${NC}"
        echo -e "${YELLOW}💡 먼저 ./stop_grid.sh로 중지하세요${NC}"
        exit 1
    else
        # PID 파일은 있지만 프로세스는 없음 - 정리
        rm -f "$GRID_DIR/.grid_pid"
    fi
fi

echo -e "${YELLOW}📂 작업 디렉토리: $(pwd)${NC}"
echo -e "${YELLOW}🔧 GRID 서버 포트: 8012${NC}"
echo ""

# 로그 디렉토리 생성
mkdir -p "$GRID_DIR/logs"

# 로그 파일명 생성 (타임스탬프 포함)
timestamp=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$GRID_DIR/logs/grid_server_${timestamp}.log"

echo -e "${GREEN}🚀 GRID 서버 시작 중...${NC}"
echo -e "${YELLOW}📝 로그 파일: ${LOG_FILE}${NC}"

# GRID 서버를 백그라운드로 실행
nohup python -m GRID.main --port 8012 >> "$LOG_FILE" 2>&1 &

# PID 저장
GRID_PID=$!
echo "$GRID_PID" > "$GRID_DIR/.grid_pid"

# 서버 시작 대기
sleep 2

# 프로세스 확인
if ps -p "$GRID_PID" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ GRID 서버 시작됨 (PID: $GRID_PID)${NC}"
    echo ""
    echo -e "${BLUE}=============================================${NC}"
    echo -e "${GREEN}✅ GRID 서버가 백그라운드에서 실행 중입니다${NC}"
    echo -e "${YELLOW}💡 서버 URL: http://0.0.0.0:8012${NC}"
    echo -e "${YELLOW}💡 종료하려면: ./stop_grid.sh${NC}"
    echo -e "${YELLOW}💡 로그 확인: tail -f ${LOG_FILE}${NC}"
    echo -e "${BLUE}=============================================${NC}"
else
    echo -e "${RED}❌ GRID 서버 시작 실패${NC}"
    echo -e "${YELLOW}💡 로그 확인: cat ${LOG_FILE}${NC}"
    rm -f "$GRID_DIR/.grid_pid"
    exit 1
fi
