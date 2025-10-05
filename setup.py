"""TradingBoost-Strategy Monorepo Setup"""
from setuptools import setup, find_packages

setup(
    name="tradingboost-strategy",
    version="0.9.0",
    packages=find_packages(include=['HYPERRSI*', 'GRID*', 'shared*']),
    python_requires=">=3.9",
    install_requires=[
        "fastapi>=0.109.0",
        "uvicorn[standard]>=0.25.0",
        "celery>=5.3.4",
        "redis>=5.0.1",
        "ccxt>=4.2.7",
        "pandas>=2.1.4",
        "numpy>=1.26.2",
        "python-telegram-bot>=20.7",
        "sqlalchemy>=2.0.23",
        "aiosqlite>=0.19.0",
        "pydantic>=2.5.3",
        "pydantic-settings>=2.1.0",
        "python-dotenv>=1.0.0",
        "aiohttp>=3.9.1",
        "websockets>=12.0",
        "ta>=0.11.0",
    ],
)
