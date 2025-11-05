"""
BACKTEST Service - TradingBoost Strategy Backtesting System

FastAPI application for backtesting trading strategies.
"""

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from BACKTEST.config import backtest_config
from shared.logging import get_logger
from shared.database.session import init_db
from shared.api.health import router as health_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.

    Replaces deprecated @app.on_event("startup") and @app.on_event("shutdown").

    Args:
        _app: FastAPI application instance (unused but required by protocol)
    """
    # Startup
    logger.info("Starting BACKTEST service...")

    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

    logger.info(f"BACKTEST service started on port {backtest_config.PORT}")

    yield  # Application runs here

    # Shutdown
    logger.info("Shutting down BACKTEST service...")


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="TradingBoost BACKTEST API",
    description="Trading strategy backtesting service",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "BACKTEST",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


# Import and include routers
from BACKTEST.api.routes import backtest, results

app.include_router(health_router, prefix="/health", tags=["health"])
app.include_router(backtest.router, prefix="/backtest", tags=["backtest"])
app.include_router(results.router, prefix="/api", tags=["results"])


def main():
    """Run the BACKTEST service."""
    uvicorn.run(
        "BACKTEST.main:app",
        host=backtest_config.HOST,
        port=backtest_config.PORT,
        reload=True,
        log_level="info"
    )


if __name__ == "__main__":
    main()
