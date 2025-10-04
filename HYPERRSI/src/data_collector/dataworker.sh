# Worker 스크립트
echo '#!/bin/bash
cd /root/HyperRSI
source .venv/bin/activate
celery -A src.data_collector.tasks worker -l info
' > start_worker.sh

# Beat 스크립트
echo '#!/bin/bash
cd /root/HyperRSI
source .venv/bin/activate
celery -A src.data_collector.tasks beat -l warning
' > start_beat.sh

# 실행 권한 부여
chmod +x start_worker.sh start_beat.sh

# PM2로 등록
pm2 start ./start_worker.sh --name data_worker
pm2 start ./start_beat.sh --name data_beat