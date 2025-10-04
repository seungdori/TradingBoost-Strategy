#!/bin/bash

# Python 및 스크립트 경로 설정
PYTHON_PATH="/root/TradingBackend/venv/bin/python3"
SCRIPT_PATH="/root/TradingBackend/main.py"

# 시작 포트와 끝 포트 설정
START_PORT=8000
END_PORT=8015

# 각 서버 시작 사이의 지연 시간 (초)
DELAY=0.5

# 각 포트에 대해 서버를 시작하고 PM2로 관리
for PORT in $(seq $START_PORT $END_PORT)
do
    echo "Starting server on port $PORT"
    pm2 start $PYTHON_PATH --name "grid$PORT" -- $SCRIPT_PATH --port $PORT
    echo "Waiting for $DELAY seconds before starting the next server..."
    sleep $DELAY
done

# PM2 목록 표시
pm2 list

echo "All servers have been started and are being managed by PM2."