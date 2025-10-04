#!/bin/bash
source /root/TradingBackend/venv/bin/activate
export RQ_DASHBOARD_REDIS_URL="redis://:moggle_temp_3181@localhost:6379"
rq-dashboard


export REDIS_URL="redis://:moggle_temp_3181@localhost:6379"