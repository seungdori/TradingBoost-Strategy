# TradingBoost-Strategy

A professional-grade cryptocurrency algorithmic trading platform implementing multiple strategies with advanced risk management, real-time market data processing, and multi-exchange support.

## Overview

TradingBoost-Strategy is a monorepo-based trading system that implements two distinct algorithmic trading strategies:

- **HYPERRSI**: Advanced RSI-based strategy combining trend analysis, momentum indicators, and dynamic position sizing
- **GRID**: Grid trading strategy with automatic rebalancing and take-profit mechanisms

Both strategies support multiple cryptocurrency exchanges (OKX, Binance, Bitget, Upbit, Bybit) and include sophisticated features like WebSocket real-time data feeds, Telegram notifications, risk management systems, and distributed task processing.

## Key Features

### Trading Strategies
- **Multiple Strategy Support**: HYPERRSI (RSI + Trend) and GRID (Price Grid) strategies
- **Multi-Exchange Integration**: OKX, Binance, Bitget, Upbit, Bybit (spot and futures)
- **Real-time Market Data**: WebSocket-based price feeds with automatic reconnection
- **Dynamic Position Sizing**: Adaptive position management based on market conditions
- **Risk Management**: Stop-loss, take-profit, custom stop mechanisms

### Technical Infrastructure
- **Asynchronous Architecture**: Built on FastAPI with async/await patterns
- **Distributed Task Processing**: Celery-based job queue with Redis backend
- **Database Layer**: PostgreSQL for production (13 tables across both strategies) ✅
- **Real-time Cache**: Redis for high-speed data access and Celery backend
- **Real-time Notifications**: Telegram bot integration for trade alerts
- **Process Management**: Multi-process architecture with graceful shutdown
- **Monitoring & Logging**: Structured logging with log rotation and error tracking

### Developer Features
- **Monorepo Structure**: Shared modules for code reuse across strategies
- **Type Safety**: Pydantic models for data validation
- **API-First Design**: RESTful APIs for all strategy operations
- **WebSocket Support**: Real-time data streaming and status updates
- **Configuration Management**: Environment-based configuration with validation

## Architecture

```
TradingBoost-Strategy/
├── HYPERRSI/                  # RSI + Trend Strategy
│   ├── src/
│   │   ├── api/              # FastAPI routes and middleware
│   │   ├── bot/              # Telegram bot handlers
│   │   ├── core/             # Core functionality (database, logging, config)
│   │   ├── trading/          # Trading logic and execution
│   │   ├── tasks/            # Celery tasks
│   │   └── utils/            # Utility functions
│   ├── websocket/            # WebSocket position monitoring
│   ├── app.py                # Application entry point
│   └── main.py               # FastAPI application
│
├── GRID/                      # Grid Trading Strategy
│   ├── api/                  # FastAPI application
│   ├── core/                 # Core functionality
│   ├── database/             # Database operations
│   ├── handlers/             # Exchange-specific handlers
│   ├── jobs/                 # Celery task management
│   ├── routes/               # API routes
│   ├── services/             # Business logic services
│   ├── strategies/           # Grid trading implementation
│   ├── trading/              # Trading execution
│   └── main.py               # Application entry point
│
└── shared/                    # Shared Modules
    ├── config/               # Configuration management
    ├── constants/            # Shared constants
    ├── database/             # Database utilities
    ├── dtos/                 # Data transfer objects
    ├── errors/               # Error handling
    ├── exchange/             # Exchange base classes
    ├── exchange_apis/        # Exchange API wrappers
    ├── helpers/              # Helper functions
    ├── indicators/           # Technical indicators
    ├── models/               # Data models
    ├── notifications/        # Notification services
    └── utils/                # Utility functions
```

## Quick Start

### Prerequisites

- Python 3.11+ (recommended 3.12)
- Redis 5.0+
- PostgreSQL 12+ (optional, for production)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/TradingBoost-Strategy.git
   cd TradingBoost-Strategy
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   # Install HYPERRSI dependencies
   cd HYPERRSI
   pip install -r requirements.txt
   cd ..

   # GRID uses the same dependencies
   ```

4. **Set up environment variables**
   ```bash
   # Copy example environment file
   cp .env.example .env

   # Edit .env with your configuration
   nano .env
   ```

5. **Install package in editable mode** (Optional but recommended)
   ```bash
   # This eliminates the need for PYTHONPATH configuration
   pip install -e .

   # Or use the install script
   ./install.sh
   ```

   > **Note**: The main.py files auto-configure paths, so this step is optional. However, editable install is recommended for production deployments.

### Running the Strategies

#### HYPERRSI Strategy

1. **Start Redis** (if not already running)
   ```bash
   redis-server
   ```

2. **Start Celery Worker**
   ```bash
   cd HYPERRSI
   celery -A HYPERRSI.src.core.celery_task worker --loglevel=INFO --concurrency=8 --purge
   ```

3. **Start Celery Beat** (for scheduled tasks)
   ```bash
   celery -A HYPERRSI.src.core.celery_task beat --loglevel=WARNING
   ```

4. **Start FastAPI Server**
   ```bash
   python app.py
   # Server runs on http://localhost:8000
   ```

5. **Optional: Start Celery Flower** (monitoring)
   ```bash
   celery -A HYPERRSI.src.core.celery_task flower --port=5555
   # Access at http://localhost:5555
   ```

#### GRID Strategy

1. **Start FastAPI Server**
   ```bash
   cd GRID
   python main.py --port 8012
   # Server runs on http://localhost:8012
   ```

### Configuration

#### Environment Variables

Create a `.env` file in the project root:

```bash
# Exchange API Keys
OKX_API_KEY=your_api_key
OKX_SECRET_KEY=your_secret_key
OKX_PASSPHRASE=your_passphrase

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=  # Optional
REDIS_DB=0

# Database Configuration
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname  # Required
# DATABASE_URL=postgresql://user:pass@host:5432/dbname  # Production

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token
OWNER_ID=your_telegram_user_id

# Application Settings
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=INFO
```

#### Strategy-Specific Configuration

Each strategy has specific configuration options:

**HYPERRSI Strategy:**
- RSI period, overbought/oversold levels
- Trend detection parameters
- Position sizing rules
- Stop-loss and take-profit settings

**GRID Strategy:**
- Grid levels and spacing
- Entry symbol count
- Leverage settings
- Rebalancing parameters

See `ARCHITECTURE.md` for detailed configuration options.

## API Documentation

### HYPERRSI API (Port 8000)

- `GET /` - Health check
- `GET /health` - Detailed health status
- `POST /api/trading/start` - Start trading
- `POST /api/trading/stop` - Stop trading
- `GET /api/trading/status` - Get trading status
- `GET /api/account/balance` - Get account balance
- `GET /api/trading/positions` - Get open positions
- `GET /api/stats` - Get trading statistics

### GRID API (Port 8012)

- `GET /test-cors` - CORS test endpoint
- `POST /api/feature/start` - Start grid trading
- `POST /api/feature/stop` - Stop grid trading
- `GET /api/bot-state` - Get bot state
- `GET /api/exchange/markets` - Get available markets
- `WebSocket /logs/ws/{user_id}` - Real-time logs

### Swagger Documentation

Both strategies provide interactive API documentation:
- HYPERRSI: http://localhost:8000/docs
- GRID: http://localhost:8012/docs

## Supported Exchanges

| Exchange | Spot | Futures | Tested |
|----------|------|---------|--------|
| OKX | ✅ | ✅ | ✅ |
| Binance | ✅ | ✅ | ✅ |
| Bitget | ✅ | ✅ | ✅ |
| Upbit | ✅ | ❌ | ✅ |
| Bybit | ✅ | ✅ | 🔄 |

## Technical Stack

### Core Technologies
- **Language**: Python 3.12
- **Web Framework**: FastAPI 0.115.6
- **Async Runtime**: uvicorn 0.34.0
- **Task Queue**: Celery 5.4.0
- **Cache/Broker**: Redis 5.2.1

### Data & Database
- **ORM**: SQLAlchemy 2.0.37
- **Database**: SQLite (dev), PostgreSQL (prod)
- **Data Processing**: pandas 2.2.3, numpy 2.2.2
- **Validation**: pydantic 2.10.5

### Exchange Integration
- **Trading Library**: ccxt 4.4.50
- **WebSocket**: websockets 13.1, aiohttp 3.10.11

### Infrastructure
- **Process Management**: multiprocessing, psutil
- **Monitoring**: Flower (Celery UI)
- **Logging**: Python logging with structured output
- **Notifications**: python-telegram-bot 21.10

### Technical Analysis
- **Indicators**: Custom implementations in `shared/indicators/`
- **Charting**: matplotlib 3.10.0, plotly 5.24.1

## Development

### Project Structure

The monorepo is organized into three main sections:

1. **HYPERRSI**: Complete trading strategy implementation
2. **GRID**: Alternative grid-based strategy
3. **shared**: Common modules used by both strategies

### Code Organization

- **Routes/API**: FastAPI endpoints for external interaction
- **Services**: Business logic layer
- **Repositories**: Data access layer
- **Models/DTOs**: Data structures and validation
- **Handlers**: Exchange-specific implementations
- **Utils**: Helper functions and utilities

### Best Practices

1. **Type Hints**: Use comprehensive type annotations
2. **Async First**: Prefer async/await for I/O operations
3. **Error Handling**: Use structured error types
4. **Logging**: Use module-level loggers
5. **Testing**: Write tests for critical paths
6. **Documentation**: Keep docstrings updated

### Adding a New Exchange

1. Create exchange handler in `GRID/handlers/` or `shared/exchange/`
2. Implement required methods (place_order, cancel_order, get_balance, etc.)
3. Add exchange-specific service in `services/`
4. Update exchange constants in `shared/constants/exchange.py`
5. Test with small positions first

### Testing

```bash
# Run unit tests
pytest tests/

# Run with coverage
pytest --cov=HYPERRSI --cov=GRID --cov=shared tests/

# Run specific test file
pytest tests/test_indicators.py
```

## Monitoring & Operations

### Logging

Logs are organized by type:
- `HYPERRSI/logs/errors/` - Error logs
- `HYPERRSI/logs/orders/` - Order execution logs
- `HYPERRSI/logs/alerts/` - Alert notifications
- `HYPERRSI/logs/debug/` - Debug information

### Celery Monitoring

Access Flower UI for task monitoring:
```bash
celery -A HYPERRSI.src.core.celery_task flower --port=5555
```
Visit: http://localhost:5555

### Redis Monitoring

```bash
# Connect to Redis CLI
redis-cli

# Monitor all commands
MONITOR

# Check memory usage
INFO memory

# List all keys
KEYS *
```

## Deployment

### Production Considerations

1. **Environment**: Set `ENVIRONMENT=production` in `.env`
2. **Database**: Use PostgreSQL instead of SQLite
3. **Redis**: Configure persistence and backup
4. **Process Manager**: Use PM2 or systemd
5. **Reverse Proxy**: Configure Nginx/Apache
6. **SSL**: Enable HTTPS for APIs
7. **Monitoring**: Set up application monitoring (Sentry, etc.)
8. **Secrets**: Use environment variables or secrets manager
9. **Backups**: Regular database and configuration backups
10. **Rate Limiting**: Implement API rate limiting

### Docker Deployment (Future)

Docker support is planned for easier deployment.

## Troubleshooting

### Common Issues

**Redis Connection Error**
```bash
# Check if Redis is running
redis-cli ping
# Should return: PONG

# Restart Redis
sudo systemctl restart redis
```

**Import Errors**
```bash
# Ensure PYTHONPATH is set
export PYTHONPATH=/path/to/TradingBoost-Strategy:$PYTHONPATH

# Verify imports
python -c "from shared.config import settings; print(settings)"
```

**Celery Worker Not Starting**
```bash
# Clear Celery tasks
celery -A HYPERRSI.src.core.celery_task purge

# Check Redis connectivity
celery -A HYPERRSI.src.core.celery_task inspect ping
```

**Database Migration Issues**
```bash
# For SQLite
rm HYPERRSI/trading.db
python -c "from HYPERRSI.src.core.database import init_db; import asyncio; asyncio.run(init_db())"
```

## Security Considerations

1. **API Keys**: Never commit API keys to version control
2. **Environment Files**: Add `.env` to `.gitignore`
3. **Credentials**: Store sensitive data in environment variables
4. **CORS**: Configure appropriate CORS policies for production
5. **Rate Limiting**: Implement rate limiting on public endpoints
6. **Input Validation**: All user inputs are validated using Pydantic
7. **Database**: Use parameterized queries (SQLAlchemy handles this)

## Performance Optimization

1. **Connection Pooling**: Redis and database connections are pooled
2. **Async Operations**: I/O operations are non-blocking
3. **Caching**: Frequently accessed data is cached in Redis
4. **Task Queue**: Heavy operations are offloaded to Celery workers
5. **WebSocket**: Real-time data uses efficient WebSocket connections

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Code Style

- Follow PEP 8 guidelines
- Use type hints for all functions
- Write docstrings for public APIs
- Keep functions focused and small
- Add tests for new features

## License

This project is proprietary software. All rights reserved.

## Support

For issues, questions, or contributions:
- Create an issue on GitHub
- Contact: [Your contact information]

## Acknowledgments

- ccxt library for exchange integration
- FastAPI framework for modern async APIs
- Celery for distributed task processing
- Trading community for strategy insights

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and updates.

---

**Disclaimer**: This software is for educational purposes only. Trading cryptocurrencies carries significant risk. Use at your own risk.
