#!/bin/bash

echo "=========================================="
echo "HYPERRSI Services Test"
echo "=========================================="
echo ""

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "1. Testing FastAPI Server..."
cd /Users/seunghyun/TradingBoost-Strategy/HYPERRSI
uvicorn main:app --host 0.0.0.0 --port 8000 > /tmp/fastapi.log 2>&1 &
FASTAPI_PID=$!
sleep 3

if ps -p $FASTAPI_PID > /dev/null 2>&1; then
    echo -e "${GREEN}✅ FastAPI Server started (PID: $FASTAPI_PID)${NC}"
    kill $FASTAPI_PID 2>/dev/null
else
    echo -e "${RED}❌ FastAPI Server failed${NC}"
    tail -20 /tmp/fastapi.log
fi

echo ""
echo "2. Testing Telegram Bot..."
cd /Users/seunghyun/TradingBoost-Strategy/HYPERRSI
python bot.py > /tmp/bot.log 2>&1 &
BOT_PID=$!
sleep 2

if ps -p $BOT_PID > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Telegram Bot started (PID: $BOT_PID)${NC}"
    kill $BOT_PID 2>/dev/null
else
    echo -e "${RED}❌ Telegram Bot failed${NC}"
    tail -20 /tmp/bot.log
fi

echo ""
echo "3. Testing Celery Worker..."
cd /Users/seunghyun/TradingBoost-Strategy
celery -A HYPERRSI.src.core.celery_task worker --loglevel=warning --concurrency=1 > /tmp/celery_worker.log 2>&1 &
WORKER_PID=$!
sleep 3

if ps -p $WORKER_PID > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Celery Worker started (PID: $WORKER_PID)${NC}"
    kill $WORKER_PID 2>/dev/null
    sleep 1
else
    echo -e "${RED}❌ Celery Worker failed${NC}"
    tail -20 /tmp/celery_worker.log
fi

echo ""
echo "4. Testing Celery Beat..."
cd /Users/seunghyun/TradingBoost-Strategy
celery -A HYPERRSI.src.core.celery_task beat --loglevel=warning > /tmp/celery_beat.log 2>&1 &
BEAT_PID=$!
sleep 2

if ps -p $BEAT_PID > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Celery Beat started (PID: $BEAT_PID)${NC}"
    kill $BEAT_PID 2>/dev/null
else
    echo -e "${RED}❌ Celery Beat failed${NC}"
    tail -20 /tmp/celery_beat.log
fi

echo ""
echo "=========================================="
echo "Test Complete"
echo "=========================================="
