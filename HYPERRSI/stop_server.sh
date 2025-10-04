#!/bin/bash

# 모든 'grid' 프로세스 중지
echo "Stopping all grid processes..."

# grid 프로세스의 ID를 추출하고 중지
pm2 list | grep grid | awk '{print $2}' | xargs pm2 stop

# PM2 목록 표시
echo "Current PM2 process list:"
pm2 list

echo "All grid processes have been stopped."
