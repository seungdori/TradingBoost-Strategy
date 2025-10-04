from typing import List

from pydantic import BaseModel, Field, field_validator, validator, root_validator


class AccessListDto(BaseModel):
    exchange_name: str = Field(..., example="okx", description="Name of the exchange")
    user_id: int = Field(..., example=1234, description="User ID")
    type: str = Field(..., example="blacklist", description="Type of the list, either 'blacklist' or 'whitelist'")
    symbols: List[str] = Field(..., example=["BTC", "ETH"], description="List of symbols to be added or deleted")

    #@validator('symbols')
    #def ensure_unique_symbols(cls, v: List[str]):
    #    if len(v) != len(set(v)):
    #        raise ValueError("Duplicate symbols are not allowed")
    #    return v


class SymbolAccessDto(BaseModel):
    exchange_name: str = Field(... ,description="Name of the exchange")
    user_id: int = Field(..., description="User ID")
    type: str = Field(..., description="Type of the list, either 'blacklist' or 'whitelist'")
    symbols: List[str] = Field(..., description="List of symbols to be added")

    @root_validator(pre=True)
    def ensure_unique_symbols(cls, v: List[str]):
        if len(v) != len(set(v)):
            raise ValueError("Duplicate symbols are not allowed")
        return v