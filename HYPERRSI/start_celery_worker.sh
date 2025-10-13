#!/bin/bash

# 환경 변수 설정 (macOS용)
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES  # macOS에서만 필요

# 색상 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=============================================${NC}"
echo -e "${GREEN}🚀 Celery 워커 시작 스크립트${NC}"
echo -e "${BLUE}=============================================${NC}"

# 프로젝트 루트로 이동 (HYPERRSI가 있는 상위 디렉토리)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT" || exit 1

echo -e "${YELLOW}📁 작업 디렉토리: $(pwd)${NC}"
echo -e "${YELLOW}📁 HYPERRSI 경로: $SCRIPT_DIR${NC}"

# 운영체제 확인
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo -e "${YELLOW}🍏 macOS 환경이 감지되었습니다.${NC}"
    IS_MACOS=true
else
    IS_MACOS=false
fi

# 기존 Celery 프로세스 정리
echo -e "${YELLOW}🧹 기존 Celery 프로세스 정리 중...${NC}"

# 프로세스 직접 종료 (stop_celery_worker.sh 호출 시 무한 루프 방지)
if $IS_MACOS; then
    # macOS: Celery worker와 beat 프로세스만 종료
    celery_pids=$(ps aux | grep -E 'celery.*worker|celery.*beat' | grep 'HYPERRSI.src.core.celery_task' | grep -v "grep" | awk '{print $2}')
    if [ -n "$celery_pids" ]; then
        echo -e "${YELLOW}🔍 기존 Celery 프로세스 발견. 종료 중...${NC}"
        echo "$celery_pids" | xargs kill -9 2>/dev/null || true
        sleep 2
    fi
else
    # Linux
    pkill -9 -f "celery.*worker.*HYPERRSI" || true
    pkill -9 -f "celery.*beat.*HYPERRSI" || true
    sleep 2
fi

# 확인
remaining=$(ps aux | grep -E 'celery.*worker|celery.*beat' | grep 'HYPERRSI.src.core.celery_task' | grep -v "grep" | wc -l)
if [ "$remaining" -eq 0 ]; then
    echo -e "${GREEN}✅ 기존 프로세스 정리 완료${NC}"
else
    echo -e "${RED}⚠️ 일부 프로세스가 남아있습니다. 계속 진행...${NC}"
fi

# 임시 파일 정리 (HYPERRSI 디렉토리)
echo -e "${YELLOW}🧹 Celery 임시 파일 정리 중...${NC}"
rm -f "$SCRIPT_DIR/celerybeat.pid" "$SCRIPT_DIR/celerybeat-schedule.db" 2>/dev/null || true

# 필요한 경우 디렉토리 생성 (HYPERRSI/logs 디렉토리)
echo -e "${YELLOW}📁 로그 디렉토리 확인 중...${NC}"
mkdir -p "$SCRIPT_DIR/logs"

# 현재 시간 가져오기 (로그 파일명용)
timestamp=$(date +"%Y%m%d_%H%M%S")
worker_log="$SCRIPT_DIR/logs/celery_workers_${timestamp}.log"
beat_log="$SCRIPT_DIR/logs/celery_beat_${timestamp}.log"

echo -e "${YELLOW}📝 로그 파일: ${NC}"
echo -e "   - 워커 로그: ${worker_log}"
echo -e "   - 비트 로그: ${beat_log}"

# 워커 수 정의 (고정: 1개로 안정적으로 운영)
worker_count=1

if $IS_MACOS; then
    cores=$(sysctl -n hw.ncpu)
else
    cores=$(nproc)
fi

echo -e "${YELLOW}⚙️ $worker_count 개의 워커를 시작합니다 (CPU 코어: $cores, concurrency=2)${NC}"

# Celery 워커 시작 (백그라운드로 실행)
echo -e "${GREEN}🚀 Celery 워커 시작 중...${NC}"

echo -e "${YELLOW}🔄 워커 시작 중...${NC}"
# --pool=solo: 단일 프로세스로 실행하여 event loop 문제 해결 (macOS asyncio 호환)
# concurrency 옵션은 solo pool에서 무시됨
celery -A HYPERRSI.src.core.celery_task worker --loglevel=warning --pool=solo --purge >> "$worker_log" 2>&1 &

# 프로세스 ID 저장
worker_pid=$!
echo "worker_pid=$worker_pid" >> "$SCRIPT_DIR/.celery_pids"

echo -e "${GREEN}✅ 워커 시작됨 (PID: $worker_pid) - solo pool mode${NC}"
sleep 2

# Celery Beat 시작 (스케줄링된 작업이 필요한 경우)
echo -e "${GREEN}🚀 Celery beat 시작 중...${NC}"
celery -A HYPERRSI.src.core.celery_task beat --loglevel=warning >> "$beat_log" 2>&1 &
beat_pid=$!
echo "beat_pid=$beat_pid" >> "$SCRIPT_DIR/.celery_pids"
echo -e "${GREEN}✅ Beat 시작됨 (PID: $beat_pid)${NC}"

echo -e "${BLUE}=============================================${NC}"
echo -e "${GREEN}✅ Celery 워커와 beat가 백그라운드에서 실행 중입니다.${NC}"
echo -e "${YELLOW}💡 다음 명령어로 프로세스를 확인할 수 있습니다: ps aux | grep celery${NC}"
echo -e "${YELLOW}💡 모든 워커를 종료하려면: bash stop_celery_worker.sh${NC}"
echo -e "${YELLOW}💡 로그 확인: tail -f $worker_log${NC}"
echo -e "${BLUE}=============================================${NC}" 