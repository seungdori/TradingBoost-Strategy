#!/bin/bash

# 환경 변수 설정
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export GRPC_ENABLE_FORK_SUPPORT=1
export GRPC_DNS_RESOLVER=native
export GRPC_VERBOSITY=ERROR
export GRPC_TRACE=""
export LANG=ko_KR.UTF-8
export LC_ALL=ko_KR.UTF-8
export PYTHONIOENCODING=utf-8

# 프로젝트 루트로 이동
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT" || exit 1

echo "Starting Celery worker from $(pwd)"

# Celery worker 시작 (solo pool for asyncio compatibility)
/root/trading/.venv/bin/celery -A HYPERRSI.src.core.celery_task worker \
    --loglevel=warning \
    --pool=solo \
    --purge
