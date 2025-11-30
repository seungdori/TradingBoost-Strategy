#!/bin/bash

# 환경 변수 설정 (macOS용)
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES  # macOS에서만 필요
export GRPC_ENABLE_FORK_SUPPORT=1  # c-ares DNS resolver 경고 해결
export GRPC_DNS_RESOLVER=native  # 네이티브 DNS resolver 사용
export GRPC_VERBOSITY=ERROR  # gRPC 로깅 레벨을 ERROR로 설정하여 경고 숨김
export GRPC_TRACE=""  # gRPC 추적 비활성화

# 인코딩 설정 (한글 로그 깨짐 방지)
export LANG=ko_KR.UTF-8
export LC_ALL=ko_KR.UTF-8
export PYTHONIOENCODING=utf-8

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
rm -f "$SCRIPT_DIR/celerybeat.pid" "$SCRIPT_DIR/celerybeat-schedule.db" "$SCRIPT_DIR/.celery_pids" 2>/dev/null || true

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

# Celery 워커 시작 (foreground로 실행하여 로그 바로 출력)
echo -e "${GREEN}🚀 Celery 워커 시작 중...${NC}"

echo -e "${YELLOW}🔄 워커 시작 중...${NC}"
echo -e "${YELLOW}📝 로그가 화면에 바로 출력됩니다. Ctrl+C로 종료 가능합니다.${NC}"
echo -e "${BLUE}=============================================${NC}"

# 새 tmux 세션에서 worker와 beat 동시 실행
# --pool=solo: 단일 프로세스로 실행하여 event loop 문제 해결 (macOS asyncio 호환)
# concurrency 옵션은 solo pool에서 무시됨

# worker와 beat를 별도 프로세스로 시작
celery -A HYPERRSI.src.core.celery_task worker --loglevel=warning --pool=solo --purge &
worker_pid=$!
echo "worker_pid=$worker_pid" > "$SCRIPT_DIR/.celery_pids"

celery -A HYPERRSI.src.core.celery_task beat --loglevel=warning &
beat_pid=$!
echo "beat_pid=$beat_pid" >> "$SCRIPT_DIR/.celery_pids"

echo -e "${GREEN}✅ 워커 시작됨 (PID: $worker_pid) - solo pool mode${NC}"
echo -e "${GREEN}✅ Beat 시작됨 (PID: $beat_pid)${NC}"
echo -e "${BLUE}=============================================${NC}"
echo -e "${YELLOW}💡 프로세스 확인: ps aux | grep celery${NC}"
echo -e "${YELLOW}💡 종료: Ctrl+C (현재 스크립트 종료) 또는 bash stop_celery_worker.sh${NC}"
echo -e "${BLUE}=============================================${NC}"

# 사용자가 Ctrl+C를 누를 때까지 대기 (로그 스트리밍)
trap "echo -e '\n${YELLOW}🛑 종료 신호 수신. 프로세스를 종료합니다...${NC}'; kill $worker_pid $beat_pid 2>/dev/null; exit 0" INT TERM

# worker나 beat 중 하나라도 종료되면 스크립트 종료
wait $worker_pid $beat_pid

echo -e "${RED}⚠️ Celery 프로세스가 예기치 않게 종료되었습니다.${NC}"
echo -e "${YELLOW}💡 종료된 프로세스의 로그를 확인하세요.${NC}" 