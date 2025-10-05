#!/bin/bash

# TradingBoost-Strategy 설치 스크립트
# 이 스크립트는 어떤 서버에서든 PYTHONPATH 설정 없이 작동하도록 합니다

set -e  # 에러 발생 시 중단

echo "🚀 TradingBoost-Strategy 설치 시작..."

# 가상환경 확인
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  가상환경이 활성화되지 않았습니다."
    echo "다음 명령어로 가상환경을 활성화하세요:"
    echo "  source .venv/bin/activate"
    exit 1
fi

# 의존성 설치
echo "📦 의존성 설치 중..."
pip install -r requirements.txt

# Editable 모드로 패키지 설치 (PYTHONPATH 설정 불필요하게 만듦)
echo "🔧 패키지를 editable 모드로 설치 중..."
pip install -e .

echo ""
echo "✅ 설치 완료!"
echo ""
echo "이제 PYTHONPATH 설정 없이 다음과 같이 import 할 수 있습니다:"
echo "  from GRID.strategies import strategy"
echo "  from HYPERRSI.src.core.logger import get_logger"
echo "  from shared.config import get_settings"
echo ""
echo "전략 실행:"
echo "  cd HYPERRSI && python main.py"
echo "  cd GRID && python main.py --port 8012"
