"""User database compatibility layer.

(`GRID.services.user_service_pg`)를 그대로 노출합니다. 코드에서
`GRID.database.user_database`를 계속 사용하더라도 새로운 인프라를 통해
데이터가 처리되도록 보장합니다.
"""

from __future__ import annotations

from typing import Any, List

from GRID.services import user_service_pg as _pg

__all__: List[str] = [name for name in dir(_pg) if not name.startswith("_")]


def __getattr__(name: str) -> Any:
    if name in __all__:
        return getattr(_pg, name)
    raise AttributeError(f"module 'user_database' has no attribute '{name}'")


def __dir__() -> List[str]:
    return sorted(set(__all__ + list(globals().keys())))
