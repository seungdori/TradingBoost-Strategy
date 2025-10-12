#!/bin/bash
# Start Position/Order Management Service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
cd "$SERVICE_DIR"

echo "🚀 Starting Position/Order Management Service..."

# Load environment variables
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "⚠️  .env file not found - using defaults"
fi

# Set defaults
SERVICE_HOST=${SERVICE_HOST:-0.0.0.0}
SERVICE_PORT=${SERVICE_PORT:-8020}

# Check if service is already running
if lsof -Pi :$SERVICE_PORT -sTCP:LISTEN -t >/dev/null ; then
    echo "⚠️  Service already running on port $SERVICE_PORT"
    echo "   Run 'scripts/stop.sh' to stop it first"
    exit 1
fi

# Activate virtual environment if exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Start service
echo "📌 Starting service on $SERVICE_HOST:$SERVICE_PORT..."
python main.py --host $SERVICE_HOST --port $SERVICE_PORT

echo "✅ Service started successfully"
