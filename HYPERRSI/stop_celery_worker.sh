#!/bin/bash

# 현재 스크립트의 PID를 저장 (자기 자신은 제외하기 위함)
SELF_PID=$$
SCRIPT_PATH=$(realpath "$0")

# Celery 프로세스 종료 스크립트 (강화 버전)
echo "============================================="
echo "🛑 Celery 워커 및 비트 종료 프로세스 시작..."
echo "============================================="

# 운영체제 확인
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "🍏 macOS 환경이 감지되었습니다."
    IS_MACOS=true
else
    IS_MACOS=false
fi

# 단계 1: 모든 Celery 프로세스 찾기 (자기 자신 제외)
echo "📊 실행 중인 Celery 프로세스 확인 중..."

# macOS와 Linux 모두 호환되도록 프로세스 찾기
if $IS_MACOS; then
    # 자기 자신(현재 스크립트)과 grep 명령어 제외
    celery_pids=$(ps aux | grep -E '[c]elery|[s]rc.core.celery_task' | grep -v "bash.*stop_celery_worker.sh" | awk '{print $2}')
else
    # 자기 자신(현재 스크립트) 제외
    celery_pids=$(pgrep -f "celery\|src.core.celery_task" | grep -v "$SELF_PID")
fi

if [ -z "$celery_pids" ]; then
    echo "✅ 실행 중인 Celery 프로세스가 없습니다."
    exit 0
fi

echo "🔍 다음 Celery 프로세스들이 실행 중입니다:"
if $IS_MACOS; then
    ps aux | grep -E 'celery|src.core.celery_task' | grep -v "grep" | grep -v "bash.*stop_celery_worker.sh"
else
    ps aux | grep -E 'celery|src.core.celery_task' | grep -v "grep" | grep -v "$SELF_PID"
fi

# 단계 2: 정상 종료 시도 (SIGTERM)
echo "🔄 Celery 프로세스 정상 종료 시도 중... (SIGTERM)"

# 여러 프로세스 패턴을 확인하여 종료
for pattern in "celery worker" "celery beat" "src.core.celery_task"; do
    echo "🔍 '$pattern' 패턴의 프로세스 종료 중..."
    if $IS_MACOS; then
        ps aux | grep "$pattern" | grep -v "grep" | grep -v "bash.*stop_celery_worker.sh" | awk '{print $2}' | xargs kill -15 2>/dev/null || true
    else
        pids=$(ps aux | grep "$pattern" | grep -v "grep" | grep -v "$SELF_PID" | awk '{print $2}')
        [ -n "$pids" ] && kill -15 $pids 2>/dev/null || true
    fi
done

echo "⏳ 프로세스가 종료되기를 기다리는 중... (5초)"
sleep 5

# 단계 3: 남아있는 프로세스 확인 (자기 자신 제외)
if $IS_MACOS; then
    remaining_pids=$(ps aux | grep -E '[c]elery|[s]rc.core.celery_task' | grep -v "bash.*stop_celery_worker.sh" | awk '{print $2}')
else
    remaining_pids=$(pgrep -f "celery\|src.core.celery_task" | grep -v "$SELF_PID")
fi

if [ -z "$remaining_pids" ]; then
    echo "✅ 모든 Celery 프로세스가 정상적으로 종료되었습니다."
    
    # 임시 파일 정리
    echo "🧹 Celery 임시 파일 정리 중..."
    rm -f celerybeat.pid celerybeat-schedule.db 2>/dev/null || true
    
    echo "============================================="
    echo "🏁 Celery 종료 프로세스 완료!"
    echo "============================================="
    exit 0
else
    echo "⚠️ 일부 Celery 프로세스가 아직 실행 중입니다. 강제 종료를 시도합니다."
    if $IS_MACOS; then
        ps aux | grep -E 'celery|src.core.celery_task' | grep -v "grep" | grep -v "bash.*stop_celery_worker.sh"
    else
        ps aux | grep -E 'celery|src.core.celery_task' | grep -v "grep" | grep -v "$SELF_PID"
    fi
fi

# 단계 4: 강제 종료 시도 (SIGKILL)
echo "🔄 Celery 프로세스 강제 종료 시도 중... (SIGKILL)"

# 여러 프로세스 패턴을 확인하여 강제 종료
for pattern in "celery worker" "celery beat" "src.core.celery_task"; do
    echo "🔍 '$pattern' 패턴의 프로세스 강제 종료 중..."
    if $IS_MACOS; then
        ps aux | grep "$pattern" | grep -v "grep" | grep -v "bash.*stop_celery_worker.sh" | awk '{print $2}' | xargs kill -9 2>/dev/null || true
    else
        pids=$(ps aux | grep "$pattern" | grep -v "grep" | grep -v "$SELF_PID" | awk '{print $2}')
        [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
    fi
done

echo "⏳ 프로세스 종료 확인 중... (3초)"
sleep 3

# 단계 5: 최종 확인 (자기 자신 제외)
if $IS_MACOS; then
    final_pids=$(ps aux | grep -E '[c]elery|[s]rc.core.celery_task' | grep -v "bash.*stop_celery_worker.sh" | awk '{print $2}')
else
    final_pids=$(pgrep -f "celery\|src.core.celery_task" | grep -v "$SELF_PID")
fi

if [ -z "$final_pids" ]; then
    echo "✅ 모든 Celery 프로세스가 성공적으로 종료되었습니다."
else
    echo "❌ 일부 Celery 프로세스를 종료하지 못했습니다."
    echo "💡 다음 명령어를 사용해보세요: sudo $SCRIPT_PATH"
    echo "남아있는 프로세스:"
    if $IS_MACOS; then
        ps aux | grep -E 'celery|src.core.celery_task' | grep -v "grep" | grep -v "bash.*stop_celery_worker.sh"
    else
        ps aux | grep -E 'celery|src.core.celery_task' | grep -v "grep" | grep -v "$SELF_PID"
    fi
    
    # 관리자 권한으로 다시 시도 제안
    read -p "💬 관리자 권한으로 다시 시도할까요? (y/n): " choice
    if [ "$choice" = "y" ] || [ "$choice" = "Y" ]; then
        echo "🔄 관리자 권한으로 다시 시도합니다..."
        sudo "$SCRIPT_PATH"
        exit $?
    fi
fi

# 단계 6: 피드 파일 정리
echo "🧹 Celery 임시 파일 정리 중..."
rm -f celerybeat.pid celerybeat-schedule.db 2>/dev/null || true
rm -f .celery_pids 2>/dev/null || true

echo "============================================="
echo "🏁 Celery 종료 프로세스 완료!"
echo "=============================================" 