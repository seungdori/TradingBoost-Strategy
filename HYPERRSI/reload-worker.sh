# reload-worker.sh
#!/bin/bash

echo "Reloading Celery worker..."
sudo systemctl stop celery-worker
sudo systemctl daemon-reload
sudo systemctl start celery-worker
echo "Waiting for service to start..."
sleep 2
sudo systemctl status celery-worker