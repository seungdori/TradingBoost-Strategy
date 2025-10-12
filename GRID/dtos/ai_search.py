from typing import Optional

from pydantic import BaseModel, Field


class AiSearchProgress(BaseModel):
    exchange_name: str = Field(examples=["okx", "upbit", "bitget", "binance", "binance_spot", "bitget_spot", "okx_spot"])
    enter_strategy: str = Field(examples=["long", "short", "long-short"])
    current_progress_symbol: str = Field(examples=["BTCUSDT"])
    completed_symbol_count: int = Field(examples=[1])
    total_symbol_count: int = Field(examples=[100])
    status: str = Field(examples=["stopped", "started", "progress", "completed", "error"])
