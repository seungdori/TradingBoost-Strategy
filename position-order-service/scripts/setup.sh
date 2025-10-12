#!/bin/bash
# Position/Order Management Service - Setup Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
cd "$SERVICE_DIR"

echo "🚀 Setting up Position/Order Management Service..."

# 1. Check Python version
echo "📌 Checking Python version..."
python_version=$(python --version 2>&1 | awk '{print $2}')
required_version="3.9"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "❌ Python $required_version or higher is required. Found: $python_version"
    exit 1
fi
echo "✅ Python version: $python_version"

# 2. Create virtual environment (optional)
if [ ! -d "venv" ]; then
    echo "📌 Creating virtual environment..."
    python -m venv venv
    echo "✅ Virtual environment created"
fi

# 3. Activate virtual environment
echo "📌 Activating virtual environment..."
source venv/bin/activate

# 4. Install dependencies
echo "📌 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✅ Dependencies installed"

# 5. Create .env file if not exists
if [ ! -f ".env" ]; then
    echo "📌 Creating .env file from template..."
    cp .env.example .env
    echo "✅ .env file created - Please configure it"
    echo "⚠️  Edit .env file and set your configuration!"
else
    echo "✅ .env file already exists"
fi

# 6. Create log directory
echo "📌 Creating log directory..."
mkdir -p logs
chmod 755 logs
echo "✅ Log directory created"

# 7. Check Redis connection
echo "📌 Checking Redis connection..."
if command -v redis-cli &> /dev/null; then
    if redis-cli ping > /dev/null 2>&1; then
        echo "✅ Redis is running"
    else
        echo "⚠️  Redis is not responding - please start Redis"
    fi
else
    echo "⚠️  redis-cli not found - please install Redis"
fi

# 8. Check PostgreSQL connection (optional)
echo "📌 Checking PostgreSQL connection..."
if command -v psql &> /dev/null; then
    echo "✅ PostgreSQL client found"
    echo "   Run 'scripts/init_db.sh' to initialize database"
else
    echo "ℹ️  PostgreSQL client not found (optional - service can run without it)"
fi

echo ""
echo "🎉 Setup completed successfully!"
echo ""
echo "Next steps:"
echo "  1. Edit .env file and configure your settings"
echo "  2. If using PostgreSQL: Run 'scripts/init_db.sh'"
echo "  3. Start the service: 'python main.py'"
echo ""
