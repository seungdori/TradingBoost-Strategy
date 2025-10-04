from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class Exchange:
    binance: str = "binance"
    upbit: str = 'upbit'
    bitget: str = 'bitget'
    okx: str = 'okx'
    binance_spot: str = 'binance_spot'
    bitget_spot: str = 'bitget_spot'
    okx_spot: str = 'okx_spot'
    
