"""
Backtest Results API Routes

Provides endpoints for saving, retrieving, and managing backtest results.
"""

from typing import Dict, Any, AsyncGenerator
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from BACKTEST.models.result import BacktestResult
from BACKTEST.storage.backtest_repository import BacktestRepository
from shared.database.session import DatabaseConfig
from shared.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/results", tags=["Backtest Results"])


# FastAPI-compatible database dependency
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for FastAPI dependency injection."""
    session_factory = DatabaseConfig.get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


@router.post("/save", status_code=201)
async def save_backtest_result(
    result: BacktestResult,
    db: AsyncSession = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    백테스트 결과를 저장합니다.

    - **result**: 백테스트 결과 (거래 내역, 성과 지표, 통계 및 차트)

    Returns:
        성공 메시지 및 백테스트 ID
    """
    try:
        logger.info(f"저장 중: Saving backtest result: user={result.user_id}, symbol={result.symbol}")

        repository = BacktestRepository(db)
        backtest_id = await repository.save(result)

        return {
            "success": True,
            "backtest_id": str(backtest_id),
            "message": "백테스트 결과가 성공적으로 저장되었습니다."
        }

    except Exception as e:
        logger.error(f"실패: Failed to save backtest result: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"백테스트 결과 저장 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/{backtest_id}")
async def get_backtest_result(
    backtest_id: UUID,
    db: AsyncSession = Depends(get_db_session)
) -> BacktestResult:
    """
    특정 백테스트 결과를 조회합니다 (전체 상세 정보 포함).

    - **backtest_id**: 백테스트 고유 ID

    Returns:
        전체 백테스트 결과 (성과 지표, 통계 및 차트 포함)
    """
    try:
        logger.info(f"조회 중: Retrieving backtest result: {backtest_id}")

        repository = BacktestRepository(db)
        result = await repository.get_by_id(backtest_id)

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"백테스트 결과를 찾을 수 없습니다: {backtest_id}"
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"실패: Failed to retrieve backtest result: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"백테스트 결과 조회 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/list/{user_id}")
async def list_backtest_results(
    user_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_stats: bool = Query(default=False),
    db: AsyncSession = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    사용자 백테스트 결과 목록을 조회합니다.

    - **user_id**: 사용자 ID
    - **limit**: 최대 결과 수 (기본값: 20, 최대: 100)
    - **offset**: 오프셋 (기본값: 0)
    - **include_stats**: 통계 포함 여부 (기본값: false)

    Returns:
        백테스트 목록 및 페이지네이션 정보
    """
    try:
        logger.info(f"목록 조회: Listing backtests: user={user_id}, limit={limit}, offset={offset}")

        repository = BacktestRepository(db)

        # Get backtest list
        backtests = await repository.list_by_user(user_id, limit, offset)

        # Build response
        response: Dict[str, Any] = {
            "backtests": backtests,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "count": len(backtests)
            }
        }

        # Include stats if requested
        if include_stats:
            stats = await repository.get_stats(user_id)
            response["stats"] = stats

        return response

    except Exception as e:
        logger.error(f"실패: Failed to list backtests: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"백테스트 목록 조회 중 오류가 발생했습니다: {str(e)}"
        )


@router.delete("/{backtest_id}")
async def delete_backtest_result(
    backtest_id: UUID,
    user_id: UUID = Query(..., description="사용자 ID (권한 확인용)"),
    db: AsyncSession = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    백테스트 결과를 삭제합니다 (CASCADE).

    - **backtest_id**: 백테스트 고유 ID
    - **user_id**: 사용자 ID (권한 확인용)

    Returns:
        성공 메시지
    """
    try:
        logger.info(f"삭제 중: Deleting backtest: id={backtest_id}, user={user_id}")

        repository = BacktestRepository(db)
        deleted = await repository.delete(backtest_id, user_id)

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="백테스트 결과를 찾을 수 없거나 권한이 없습니다."
            )

        return {
            "success": True,
            "message": "백테스트 결과가 성공적으로 삭제되었습니다."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"실패: Failed to delete backtest: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"백테스트 결과 삭제 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/stats/{user_id}")
async def get_user_stats(
    user_id: UUID,
    db: AsyncSession = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    사용자별 백테스트 통계를 조회합니다.

    - **user_id**: 사용자 ID

    Returns:
        백테스트 통계 (총 횟수, 평균 수익률 등)
    """
    try:
        logger.info(f"통계 조회: Getting stats for user: {user_id}")

        repository = BacktestRepository(db)
        stats = await repository.get_stats(user_id)

        return stats

    except Exception as e:
        logger.error(f"실패: Failed to get stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"통계 조회 중 오류가 발생했습니다: {str(e)}"
        )
