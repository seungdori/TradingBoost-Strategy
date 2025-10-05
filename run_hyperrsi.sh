#!/bin/bash
# HYPERRSI 전략 실행 스크립트
# 어떤 디렉토리에서든 실행 가능

cd "$(dirname "$0")/HYPERRSI"
python main.py "$@"
