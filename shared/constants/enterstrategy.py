from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class EnterStrategy:
    long: str = "long"
    short: str = 'short'
    long_short: str = 'long-short'

