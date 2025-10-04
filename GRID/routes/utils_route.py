from fastapi import APIRouter
from version import __version__

router = APIRouter(prefix="/utils", tags=["utils"])


@router.get("/ping")
async def health_check() -> str:
    return "pong"


@router.get("/version")
async def version_check() -> str:
    return __version__
