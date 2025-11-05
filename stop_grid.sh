#!/bin/bash

# TradingBoost-Strategy 루트에서 GRID 전략 서버 중지

# 색상 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=============================================${NC}"
echo -e "${YELLOW}🛑 GRID 전략 서버 중지${NC}"
echo -e "${BLUE}=============================================${NC}"

# 스크립트 위치 확인
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRID_DIR="$SCRIPT_DIR/GRID"

# GRID 디렉토리 존재 확인
if [ ! -d "$GRID_DIR" ]; then
    echo -e "${RED}❌ 오류: GRID 디렉토리를 찾을 수 없습니다.${NC}"
    exit 1
fi

echo -e "${YELLOW}📂 작업 디렉토리: $(pwd)${NC}"
echo ""

# PID 파일 확인
if [ ! -f "$GRID_DIR/.grid_pid" ]; then
    echo -e "${YELLOW}⚠️  실행 중인 GRID 서버를 찾을 수 없습니다${NC}"

    # 혹시 PID 파일 없이 실행 중인 프로세스 확인
    GRID_PIDS=$(ps aux | grep "python.*GRID.main" | grep -v grep | awk '{print $2}')

    if [ -n "$GRID_PIDS" ]; then
        echo -e "${YELLOW}🔍 PID 파일 없이 실행 중인 GRID 프로세스 발견:${NC}"
        echo "$GRID_PIDS"
        echo -e "${YELLOW}💡 강제 종료 중...${NC}"
        echo "$GRID_PIDS" | xargs kill -TERM 2>/dev/null || true
        sleep 2

        # 아직 살아있으면 강제 종료
        REMAINING=$(ps aux | grep "python.*GRID.main" | grep -v grep | awk '{print $2}')
        if [ -n "$REMAINING" ]; then
            echo -e "${YELLOW}💡 일부 프로세스가 남아있어 강제 종료(KILL)...${NC}"
            echo "$REMAINING" | xargs kill -9 2>/dev/null || true
        fi

        echo -e "${GREEN}✅ GRID 프로세스 정리 완료${NC}"
    fi

    exit 0
fi

# PID 읽기
GRID_PID=$(cat "$GRID_DIR/.grid_pid")

# 프로세스 확인
if ! ps -p "$GRID_PID" > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  GRID 서버가 이미 중지되어 있습니다${NC}"
    rm -f "$GRID_DIR/.grid_pid"
    exit 0
fi

echo -e "${YELLOW}🛑 GRID 서버 중지 중... (PID: $GRID_PID)${NC}"

# Graceful shutdown (SIGTERM)
kill -TERM "$GRID_PID" 2>/dev/null

# 프로세스가 종료될 때까지 최대 10초 대기
for i in {1..10}; do
    if ! ps -p "$GRID_PID" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ GRID 서버가 정상적으로 종료되었습니다${NC}"
        rm -f "$GRID_DIR/.grid_pid"
        echo ""
        echo -e "${BLUE}=============================================${NC}"
        echo -e "${GREEN}✅ GRID 서버 중지 완료!${NC}"
        echo -e "${BLUE}=============================================${NC}"
        exit 0
    fi
    sleep 1
done

# 10초 후에도 종료되지 않으면 강제 종료
echo -e "${YELLOW}⚠️  정상 종료되지 않아 강제 종료합니다...${NC}"
kill -9 "$GRID_PID" 2>/dev/null || true
rm -f "$GRID_DIR/.grid_pid"

echo -e "${GREEN}✅ GRID 서버가 강제 종료되었습니다${NC}"
echo ""
echo -e "${BLUE}=============================================${NC}"
echo -e "${GREEN}✅ GRID 서버 중지 완료!${NC}"
echo -e "${BLUE}=============================================${NC}"
