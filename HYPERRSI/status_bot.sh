#!/bin/bash

# Telegram Bot 상태 확인 스크립트
# Usage: ./status_bot.sh [--verbose]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/bot.pid"
LOG_DIR="$SCRIPT_DIR/logs"

# 색상 정의
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 상태 확인
check_status() {
    echo "=========================================="
    echo "  Telegram Bot Status"
    echo "=========================================="
    echo ""

    # PID 파일 확인
    if [ ! -f "$PID_FILE" ]; then
        echo -e "${RED}✗ Status: NOT RUNNING${NC}"
        echo -e "PID file not found at: $PID_FILE"
        return 1
    fi

    PID=$(cat "$PID_FILE")
    echo -e "${BLUE}PID File:${NC} $PID_FILE"
    echo -e "${BLUE}PID:${NC} $PID"

    # 프로세스 확인
    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo -e "${RED}✗ Status: NOT RUNNING${NC}"
        echo -e "${YELLOW}⚠️  Stale PID file detected${NC}"
        echo -e "Process $PID is not running"
        echo -e "Run './stop_bot.sh' to clean up or './start_bot.sh' to start"
        return 1
    fi

    echo -e "${GREEN}✓ Status: RUNNING${NC}"
    echo ""

    # 프로세스 정보
    echo -e "${BLUE}Process Information:${NC}"
    ps -p "$PID" -o pid,ppid,%cpu,%mem,etime,command | tail -n +2

    echo ""

    # 로그 파일 정보
    if [ -d "$LOG_DIR" ]; then
        LATEST_LOG=$(ls -t "$LOG_DIR"/bot_*.log 2>/dev/null | head -1)
        if [ -n "$LATEST_LOG" ]; then
            echo -e "${BLUE}Latest Log:${NC} $LATEST_LOG"
            LOG_SIZE=$(du -h "$LATEST_LOG" | cut -f1)
            echo -e "${BLUE}Log Size:${NC} $LOG_SIZE"

            # Verbose 모드
            if [ "$1" == "--verbose" ] || [ "$1" == "-v" ]; then
                echo ""
                echo -e "${BLUE}Last 20 log lines:${NC}"
                echo "----------------------------------------"
                tail -20 "$LATEST_LOG"
            else
                echo ""
                echo "Use './status_bot.sh --verbose' to see recent logs"
            fi
        fi
    fi

    echo ""
    echo -e "${GREEN}✓${NC} Bot is running normally"
    return 0
}

# 빠른 상태 확인 (스크립트에서 사용)
quick_check() {
    if [ ! -f "$PID_FILE" ]; then
        exit 1
    fi

    PID=$(cat "$PID_FILE")
    if ! ps -p "$PID" > /dev/null 2>&1; then
        exit 1
    fi

    exit 0
}

# Main
main() {
    if [ "$1" == "--quick" ]; then
        quick_check
    else
        check_status "$1"
    fi
}

main "$@"
