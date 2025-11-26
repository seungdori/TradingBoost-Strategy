# src/api/routes/preset.py
"""
Preset API Routes - 트레이딩 프리셋 관리 API

프리셋 CRUD 엔드포인트를 제공합니다.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from HYPERRSI.src.core.models.preset import (
    TradingPreset,
    PresetSummary,
    CreatePresetRequest,
    UpdatePresetRequest,
)
from HYPERRSI.src.services.preset_service import preset_service
from shared.logging import get_logger
from shared.helpers.user_id_resolver import get_okx_uid_from_telegram

logger = get_logger(__name__)

router = APIRouter(prefix="/presets", tags=["presets"])


async def resolve_okx_uid(user_id: str) -> str:
    """
    user_id를 okx_uid로 변환.
    telegram_id인 경우 okx_uid로 변환 시도.
    """
    # 길이가 짧으면 telegram_id로 간주
    if not user_id.isdigit() or len(user_id) < 13:
        okx_uid = await get_okx_uid_from_telegram(user_id)
        if okx_uid:
            return okx_uid
    return user_id


@router.post(
    "",
    response_model=TradingPreset,
    summary="프리셋 생성",
    description="""
# 새 트레이딩 프리셋 생성

사용자가 재사용 가능한 트레이딩 설정 프리셋을 생성합니다.

## 요청 본문

- **name** (string, required): 프리셋 이름 (최대 50자)
- **description** (string, optional): 프리셋 설명 (최대 200자)
- **settings** (object, optional): 트레이딩 설정. 없으면 기본값 사용
- **is_default** (boolean, optional): 기본 프리셋으로 설정

## 쿼리 파라미터

- **user_id** (string, required): 사용자 ID (OKX UID 또는 Telegram ID)

## 반환

생성된 TradingPreset 객체
""",
    responses={
        200: {"description": "프리셋 생성 성공"},
        400: {"description": "잘못된 요청"},
        500: {"description": "서버 오류"},
    },
)
async def create_preset(
    request: CreatePresetRequest,
    user_id: str = Query(..., description="사용자 ID (OKX UID 또는 Telegram ID)"),
):
    try:
        okx_uid = await resolve_okx_uid(user_id)

        preset = await preset_service.create_preset(okx_uid, request)
        logger.info(f"[{okx_uid}] 프리셋 생성: {preset.name}")

        return preset

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"프리셋 생성 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"프리셋 생성 실패: {str(e)}")


@router.get(
    "",
    response_model=List[PresetSummary],
    summary="프리셋 목록 조회",
    description="""
# 사용자의 모든 프리셋 목록 조회

사용자가 생성한 모든 프리셋의 요약 정보를 반환합니다.
생성일 기준 최신순으로 정렬됩니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 ID (OKX UID 또는 Telegram ID)

## 반환

PresetSummary 배열 (요약 정보만 포함)
""",
    responses={
        200: {"description": "프리셋 목록 조회 성공"},
        500: {"description": "서버 오류"},
    },
)
async def list_presets(
    user_id: str = Query(..., description="사용자 ID (OKX UID 또는 Telegram ID)"),
):
    try:
        okx_uid = await resolve_okx_uid(user_id)

        presets = await preset_service.list_presets(okx_uid)
        logger.debug(f"[{okx_uid}] 프리셋 목록 조회: {len(presets)}개")

        return presets

    except Exception as e:
        logger.error(f"프리셋 목록 조회 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"프리셋 목록 조회 실패: {str(e)}")


@router.get(
    "/{preset_id}",
    response_model=TradingPreset,
    summary="프리셋 상세 조회",
    description="""
# 특정 프리셋의 상세 정보 조회

프리셋의 모든 설정 값을 포함한 상세 정보를 반환합니다.

## 경로 파라미터

- **preset_id** (string, required): 프리셋 ID

## 쿼리 파라미터

- **user_id** (string, required): 사용자 ID (OKX UID 또는 Telegram ID)

## 반환

TradingPreset 객체 (전체 설정 포함)
""",
    responses={
        200: {"description": "프리셋 조회 성공"},
        404: {"description": "프리셋을 찾을 수 없음"},
        500: {"description": "서버 오류"},
    },
)
async def get_preset(
    preset_id: str,
    user_id: str = Query(..., description="사용자 ID (OKX UID 또는 Telegram ID)"),
):
    try:
        okx_uid = await resolve_okx_uid(user_id)

        preset = await preset_service.get_preset(okx_uid, preset_id)
        if not preset:
            raise HTTPException(status_code=404, detail="프리셋을 찾을 수 없습니다")

        return preset

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"프리셋 조회 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"프리셋 조회 실패: {str(e)}")


@router.put(
    "/{preset_id}",
    response_model=TradingPreset,
    summary="프리셋 수정",
    description="""
# 프리셋 수정 및 즉시 적용

프리셋의 이름, 설명, 설정을 수정합니다.
**수정 시 해당 프리셋을 사용 중인 모든 심볼에 즉시 적용됩니다.**

## 경로 파라미터

- **preset_id** (string, required): 프리셋 ID

## 요청 본문

- **name** (string, optional): 새 프리셋 이름
- **description** (string, optional): 새 프리셋 설명
- **settings** (object, optional): 수정할 트레이딩 설정 (부분 업데이트)

## 쿼리 파라미터

- **user_id** (string, required): 사용자 ID

## 즉시 적용

프리셋 수정 시 Redis PUB/SUB를 통해 사용 중인 심볼의 Task에 알림이 전송됩니다.
Task는 다음 사이클에서 새 설정을 로드합니다.

## 반환

수정된 TradingPreset 객체
""",
    responses={
        200: {"description": "프리셋 수정 성공"},
        404: {"description": "프리셋을 찾을 수 없음"},
        400: {"description": "잘못된 요청"},
        500: {"description": "서버 오류"},
    },
)
async def update_preset(
    preset_id: str,
    request: UpdatePresetRequest,
    user_id: str = Query(..., description="사용자 ID (OKX UID 또는 Telegram ID)"),
):
    try:
        okx_uid = await resolve_okx_uid(user_id)

        preset = await preset_service.update_preset(okx_uid, preset_id, request)
        if not preset:
            raise HTTPException(status_code=404, detail="프리셋을 찾을 수 없습니다")

        logger.info(f"[{okx_uid}] 프리셋 수정: {preset.name}")
        return preset

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"프리셋 수정 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"프리셋 수정 실패: {str(e)}")


@router.delete(
    "/{preset_id}",
    summary="프리셋 삭제",
    description="""
# 프리셋 삭제

프리셋을 삭제합니다.
**사용 중인 심볼이 있으면 삭제할 수 없습니다.**

## 경로 파라미터

- **preset_id** (string, required): 프리셋 ID

## 쿼리 파라미터

- **user_id** (string, required): 사용자 ID

## 제약 조건

- 사용 중인 심볼이 있으면 409 Conflict 반환
- 먼저 해당 심볼의 트레이딩을 중지하거나 다른 프리셋으로 변경해야 합니다.

## 반환

삭제 성공 메시지
""",
    responses={
        200: {"description": "프리셋 삭제 성공"},
        404: {"description": "프리셋을 찾을 수 없음"},
        409: {"description": "사용 중인 심볼이 있어 삭제 불가"},
        500: {"description": "서버 오류"},
    },
)
async def delete_preset(
    preset_id: str,
    user_id: str = Query(..., description="사용자 ID (OKX UID 또는 Telegram ID)"),
):
    try:
        okx_uid = await resolve_okx_uid(user_id)

        success = await preset_service.delete_preset(okx_uid, preset_id)
        if not success:
            raise HTTPException(status_code=404, detail="프리셋을 찾을 수 없습니다")

        logger.info(f"[{okx_uid}] 프리셋 삭제: {preset_id}")
        return {"status": "success", "message": "프리셋이 삭제되었습니다"}

    except HTTPException:
        raise
    except ValueError as e:
        # 사용 중인 심볼이 있는 경우
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"프리셋 삭제 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"프리셋 삭제 실패: {str(e)}")


@router.post(
    "/{preset_id}/default",
    summary="기본 프리셋 설정",
    description="""
# 기본 프리셋 설정

특정 프리셋을 기본 프리셋으로 설정합니다.
새 심볼 트레이딩 시작 시 프리셋을 지정하지 않으면 기본 프리셋이 사용됩니다.

## 경로 파라미터

- **preset_id** (string, required): 기본으로 설정할 프리셋 ID

## 쿼리 파라미터

- **user_id** (string, required): 사용자 ID

## 반환

설정 성공 메시지
""",
    responses={
        200: {"description": "기본 프리셋 설정 성공"},
        404: {"description": "프리셋을 찾을 수 없음"},
        500: {"description": "서버 오류"},
    },
)
async def set_default_preset(
    preset_id: str,
    user_id: str = Query(..., description="사용자 ID (OKX UID 또는 Telegram ID)"),
):
    try:
        okx_uid = await resolve_okx_uid(user_id)

        success = await preset_service.set_default_preset(okx_uid, preset_id)
        if not success:
            raise HTTPException(status_code=404, detail="프리셋을 찾을 수 없습니다")

        logger.info(f"[{okx_uid}] 기본 프리셋 설정: {preset_id}")
        return {"status": "success", "message": "기본 프리셋이 설정되었습니다"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"기본 프리셋 설정 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"기본 프리셋 설정 실패: {str(e)}")


@router.get(
    "/default",
    response_model=Optional[TradingPreset],
    summary="기본 프리셋 조회",
    description="""
# 기본 프리셋 조회

사용자의 기본 프리셋을 조회합니다.
기본 프리셋이 설정되지 않은 경우 null을 반환합니다.

## 쿼리 파라미터

- **user_id** (string, required): 사용자 ID

## 반환

기본 TradingPreset 또는 null
""",
    responses={
        200: {"description": "기본 프리셋 조회 성공"},
        500: {"description": "서버 오류"},
    },
)
async def get_default_preset(
    user_id: str = Query(..., description="사용자 ID (OKX UID 또는 Telegram ID)"),
):
    try:
        okx_uid = await resolve_okx_uid(user_id)

        preset = await preset_service.get_default_preset(okx_uid)
        return preset

    except Exception as e:
        logger.error(f"기본 프리셋 조회 오류: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"기본 프리셋 조회 실패: {str(e)}")
