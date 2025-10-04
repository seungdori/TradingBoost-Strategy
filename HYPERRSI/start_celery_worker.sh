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

# 운영체제 확인
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo -e "${YELLOW}🍏 macOS 환경이 감지되었습니다.${NC}"
    IS_MACOS=true
else
    IS_MACOS=false
fi

# 기존 Celery 프로세스 정리
echo -e "${YELLOW}🧹 기존 Celery 프로세스 정리 중...${NC}"

# 기존 프로세스 종료 스크립트 실행
if [ -f "stop_celery_worker.sh" ]; then
    bash stop_celery_worker.sh
else
    # 프로세스 직접 종료
    if $IS_MACOS; then
        ps aux | grep -E '[c]elery|[s]rc.core.celery_task' | awk '{print $2}' | xargs kill -9 2>/dev/null || true
    else
        pkill -9 -f "celery" || true
        pkill -9 -f "src.core.celery_task" || true
    fi
    sleep 2
fi

# 임시 파일 정리
echo -e "${YELLOW}🧹 Celery 임시 파일 정리 중...${NC}"
rm -f celerybeat.pid celerybeat-schedule.db 2>/dev/null || true

# 필요한 경우 디렉토리 생성
echo -e "${YELLOW}📁 로그 디렉토리 확인 중...${NC}"
mkdir -p logs

# 현재 시간 가져오기 (로그 파일명용)
timestamp=$(date +"%Y%m%d_%H%M%S")
worker_log="logs/celery_workers_${timestamp}.log"
beat_log="logs/celery_beat_${timestamp}.log"

echo -e "${YELLOW}📝 로그 파일: ${NC}"
echo -e "   - 워커 로그: ${worker_log}"
echo -e "   - 비트 로그: ${beat_log}"

# 워커 수 정의 (CPU 코어 수에 따라 자동 조정)
if $IS_MACOS; then
    cores=$(sysctl -n hw.ncpu)
else
    cores=$(nproc)
fi

# 최대 4개까지만 사용
if [ $cores -gt 4 ]; then
    worker_count=4
else
    worker_count=$cores
fi

echo -e "${YELLOW}⚙️ $worker_count 개의 워커를 시작합니다 (CPU 코어: $cores)${NC}"

# Celery 워커 시작 (백그라운드로 실행)
echo -e "${GREEN}🚀 Celery 워커 시작 중...${NC}"

for i in $(seq 1 $worker_count); do
    echo -e "${YELLOW}🔄 워커 $i/$worker_count 시작 중...${NC}"
    celery -A src.core.celery_task worker --loglevel=info --concurrency=2 -n worker${i}@%h --purge >> "$worker_log" 2>&1 &
    
    # 프로세스 ID 저장
    worker_pid=$!
    echo "worker${i}_pid=$worker_pid" >> .celery_pids
    
    echo -e "${GREEN}✅ 워커 $i 시작됨 (PID: $worker_pid)${NC}"
    sleep 1
done

# Celery Beat 시작 (스케줄링된 작업이 필요한 경우)
echo -e "${GREEN}🚀 Celery beat 시작 중...${NC}"
celery -A src.core.celery_task beat --loglevel=info >> "$beat_log" 2>&1 &
beat_pid=$!
echo "beat_pid=$beat_pid" >> .celery_pids
echo -e "${GREEN}✅ Beat 시작됨 (PID: $beat_pid)${NC}"

echo -e "${BLUE}=============================================${NC}"
echo -e "${GREEN}✅ Celery 워커와 beat가 백그라운드에서 실행 중입니다.${NC}"
echo -e "${YELLOW}💡 다음 명령어로 프로세스를 확인할 수 있습니다: ps aux | grep celery${NC}"
echo -e "${YELLOW}💡 모든 워커를 종료하려면: bash stop_celery_worker.sh${NC}"
echo -e "${YELLOW}💡 로그 확인: tail -f $worker_log${NC}"
echo -e "${BLUE}=============================================${NC}" 