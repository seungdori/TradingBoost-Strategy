#!/bin/bash

# 환경 변수 설정 (필요 시)
export PYTHONPATH=$PYTHONPATH:$(pwd)

# 로그 디렉토리 생성
mkdir -p logs

# 데이터 수집기 실행 (로그 파일에 출력 저장)
python -m src.data_collector.integrated_data_collector > logs/data_collector_$(date +%Y%m%d).log 2>&1 