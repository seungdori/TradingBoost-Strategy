#!/bin/bash

# Telegram Bot 종료 스크립트
# Usage: ./stop_bot.sh [--force]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/bot.pid"

# 색상 정의
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 종료 타임아웃 (초)
TIMEOUT=30

# PID 파일 확인
check_pid_file() {
    if [ ! -f "$PID_FILE" ]; then
        echo -e "${YELLOW}⚠️  No PID file found${NC}"
        echo -e "Bot may not be running"
        exit 0
    fi
}

# Graceful shutdown
graceful_shutdown() {
    PID=$(cat "$PID_FILE")

    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  Process $PID is not running${NC}"
        echo -e "Removing stale PID file..."
        rm -f "$PID_FILE"
        exit 0
    fi

    echo -e "${GREEN}✓${NC} Stopping Telegram Bot (PID: $PID)..."
    echo -e "Sending SIGTERM for graceful shutdown..."

    kill -TERM "$PID"

    # 종료 대기
    ELAPSED=0
    while ps -p "$PID" > /dev/null 2>&1; do
        if [ $ELAPSED -ge $TIMEOUT ]; then
            echo -e "${YELLOW}⚠️  Graceful shutdown timeout${NC}"
            return 1
        fi

        echo -n "."
        sleep 1
        ELAPSED=$((ELAPSED + 1))
    done

    echo ""
    echo -e "${GREEN}✓${NC} Bot stopped gracefully"

    # PID 파일 제거 (봇이 제거하지 못한 경우를 위해)
    if [ -f "$PID_FILE" ]; then
        rm -f "$PID_FILE"
    fi

    return 0
}

# 강제 종료
force_shutdown() {
    PID=$(cat "$PID_FILE")

    if ! ps -p "$PID" > /dev/null 2>&1; then
        echo -e "${YELLOW}⚠️  Process $PID is not running${NC}"
        rm -f "$PID_FILE"
        exit 0
    fi

    echo -e "${RED}⚠️  Force killing bot (PID: $PID)...${NC}"
    kill -9 "$PID"
    sleep 1

    if ps -p "$PID" > /dev/null 2>&1; then
        echo -e "${RED}✗${NC} Failed to kill process"
        exit 1
    fi

    echo -e "${GREEN}✓${NC} Bot force stopped"
    rm -f "$PID_FILE"
}

# Main
main() {
    echo "=========================================="
    echo "  Telegram Bot Shutdown Script"
    echo "=========================================="

    check_pid_file

    FORCE_MODE="${1:-}"

    case "$FORCE_MODE" in
        --force|-f)
            force_shutdown
            ;;
        *)
            if ! graceful_shutdown; then
                echo -e "${YELLOW}⚠️  Graceful shutdown failed${NC}"
                read -p "Force kill? (y/N): " -n 1 -r
                echo
                if [[ $REPLY =~ ^[Yy]$ ]]; then
                    force_shutdown
                else
                    echo -e "${RED}✗${NC} Shutdown cancelled"
                    exit 1
                fi
            fi
            ;;
    esac
}

main "$@"
