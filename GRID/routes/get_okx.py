from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from HYPERRSI.src.services.timescale_service import TimescaleUserService

app = FastAPI()


class OkxApiResponse(BaseModel):
    okx_uid: str
    api_key: str
    api_secret: str


class EmailRequest(BaseModel):
    email: str


@app.post("/get_okx_api", response_model=OkxApiResponse)
async def get_okx_api(request: EmailRequest) -> OkxApiResponse:
    """
    이메일로 사용자의 OKX API 정보를 조회합니다.

    TimescaleDB의 app_users 및 okx_api_info 테이블을 조회합니다.
    """
    try:
        # TimescaleDB에서 이메일로 사용자 검색
        # fetch_user는 email을 identifier로 받을 수 있음
        record = await TimescaleUserService.fetch_user(request.email)

        if record is None:
            raise HTTPException(status_code=404, detail="User not found")

        # API 정보 확인
        if record.api is None:
            raise HTTPException(status_code=404, detail="OKX API info not found")

        api_info = record.api

        # 필수 필드 확인
        if not api_info.get('okx_uid') or not api_info.get('api_key') or not api_info.get('api_secret'):
            raise HTTPException(status_code=404, detail="OKX API info incomplete")

        return OkxApiResponse(
            okx_uid=api_info['okx_uid'],
            api_key=api_info['api_key'],
            api_secret=api_info['api_secret']
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
