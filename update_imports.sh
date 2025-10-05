#!/bin/bash

# Import 경로 일괄 업데이트 스크립트

echo "🔄 HYPERRSI import 경로 업데이트 시작..."

# HYPERRSI - order_helper imports 업데이트
echo "  📦 order_helper imports 업데이트 중..."
find HYPERRSI -name "*.py" -type f -exec sed -i '' \
    's/from HYPERRSI\.src\.helpers\.order_helper import contracts_to_qty/from shared.utils import contracts_to_qty/g' {} +

find HYPERRSI -name "*.py" -type f -exec sed -i '' \
    's/from HYPERRSI\.src\.helpers\.order_helper import get_perpetual_instruments/from shared.utils import get_perpetual_instruments/g' {} +

find HYPERRSI -name "*.py" -type f -exec sed -i '' \
    's/from HYPERRSI\.src\.helpers\.order_helper import get_lot_sizes/from shared.utils import get_lot_sizes/g' {} +

find HYPERRSI -name "*.py" -type f -exec sed -i '' \
    's/from HYPERRSI\.src\.helpers\.order_helper import round_to_qty/from shared.utils import round_to_qty/g' {} +

find HYPERRSI -name "*.py" -type f -exec sed -i '' \
    's/from HYPERRSI\.src\.helpers\.order_helper import split_contracts/from shared.utils import split_contracts/g' {} +

# HYPERRSI - logger imports 업데이트
echo "  📝 logger imports 업데이트 중..."
find HYPERRSI -name "*.py" -type f -exec sed -i '' \
    's/from HYPERRSI\.src\.core\.logger import get_logger/from shared.logging import get_logger/g' {} +

find HYPERRSI -name "*.py" -type f -exec sed -i '' \
    's/from HYPERRSI\.src\.core\.logger import log_order/from shared.logging import log_order/g' {} +

find HYPERRSI -name "*.py" -type f -exec sed -i '' \
    's/from HYPERRSI\.src\.core\.logger import alert_log/from shared.logging import alert_log/g' {} +

find HYPERRSI -name "*.py" -type f -exec sed -i '' \
    's/from HYPERRSI\.src\.core\.logger import log_debug/from shared.logging import log_debug/g' {} +

find HYPERRSI -name "*.py" -type f -exec sed -i '' \
    's/from HYPERRSI\.src\.core\.logger import log_bot_start/from shared.logging import log_bot_start/g' {} +

find HYPERRSI -name "*.py" -type f -exec sed -i '' \
    's/from HYPERRSI\.src\.core\.logger import log_bot_stop/from shared.logging import log_bot_stop/g' {} +

find HYPERRSI -name "*.py" -type f -exec sed -i '' \
    's/from HYPERRSI\.src\.core\.logger import log_bot_error/from shared.logging import log_bot_error/g' {} +

echo "🔄 GRID import 경로 업데이트 시작..."

# GRID - quantity.py imports 업데이트
echo "  📦 trading utils imports 업데이트 중..."
find GRID -name "*.py" -type f -exec sed -i '' \
    's/from GRID\.trading\.get_minimum_qty import get_perpetual_instruments/from shared.utils import get_perpetual_instruments/g' {} +

find GRID -name "*.py" -type f -exec sed -i '' \
    's/from GRID\.trading\.get_minimum_qty import get_lot_sizes/from shared.utils import get_lot_sizes/g' {} +

find GRID -name "*.py" -type f -exec sed -i '' \
    's/from GRID\.utils\.quantity import calculate_order_quantity/from GRID.utils.quantity import calculate_order_quantity/g' {} +

echo "✅ Import 경로 업데이트 완료!"
echo ""
echo "📋 변경된 파일 확인:"
git diff --name-only | head -20
echo ""
echo "💡 변경사항을 확인하려면: git diff"
