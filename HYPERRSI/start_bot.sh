#!/bin/bash

# Telegram Bot 시작 스크립트
# Usage: ./start_bot.sh [--foreground|--background]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PID_FILE="$SCRIPT_DIR/bot.pid"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/bot_$(date +%Y%m%d_%H%M%S).log"

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"

# 색상 정의
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# PID 파일 확인
check_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo -e "${YELLOW}⚠️  Bot is already running (PID: $PID)${NC}"
            echo -e "Use './stop_bot.sh' to stop it first"
            exit 1
        else
            echo -e "${YELLOW}⚠️  Removing stale PID file${NC}"
            rm -f "$PID_FILE"
        fi
    fi
}

# 가상환경 활성화
activate_venv() {
    if [ -d "$PROJECT_ROOT/.venv" ]; then
        echo -e "${GREEN}✓${NC} Activating virtual environment..."
        source "$PROJECT_ROOT/.venv/bin/activate"
    else
        echo -e "${RED}✗${NC} Virtual environment not found at $PROJECT_ROOT/.venv"
        exit 1
    fi
}

# 환경 변수 확인
check_env() {
    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        echo -e "${RED}✗${NC} .env file not found at $PROJECT_ROOT/.env"
        echo -e "Please create .env file with required configuration"
        exit 1
    fi
}

# 봇 시작 (포그라운드)
start_foreground() {
    echo -e "${GREEN}✓${NC} Starting Telegram Bot in foreground mode..."
    echo -e "Log: $LOG_FILE"
    cd "$SCRIPT_DIR"
    python bot.py 2>&1 | tee "$LOG_FILE"
}

# 봇 시작 (백그라운드)
start_background() {
    echo -e "${GREEN}✓${NC} Starting Telegram Bot in background mode..."
    echo -e "Log: $LOG_FILE"
    cd "$SCRIPT_DIR"
    nohup python bot.py > "$LOG_FILE" 2>&1 &

    # 프로세스 시작 대기
    sleep 2

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo -e "${GREEN}✓${NC} Bot started successfully (PID: $PID)"
            echo -e "Use './stop_bot.sh' to stop the bot"
            echo -e "Use 'tail -f $LOG_FILE' to view logs"
        else
            echo -e "${RED}✗${NC} Bot failed to start. Check log: $LOG_FILE"
            exit 1
        fi
    else
        echo -e "${RED}✗${NC} PID file not created. Bot may have failed to start."
        echo -e "Check log: $LOG_FILE"
        exit 1
    fi
}

# Main
main() {
    echo "=========================================="
    echo "  Telegram Bot Startup Script"
    echo "=========================================="

    check_running
    activate_venv
    check_env

    MODE="${1:-background}"

    case "$MODE" in
        --foreground|-f)
            start_foreground
            ;;
        --background|-b|*)
            start_background
            ;;
    esac
}

main "$@"
