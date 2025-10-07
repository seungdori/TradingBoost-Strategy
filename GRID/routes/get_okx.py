import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
}

class OkxApiResponse(BaseModel):
    okx_uid: str
    api_key: str
    api_secret: str

class EmailRequest(BaseModel):
    email: str

@app.post("/get_okx_api", response_model=OkxApiResponse)
async def get_okx_api(request: EmailRequest) -> OkxApiResponse:
    try:
        # users 테이블에서 이메일로 사용자 검색
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/users?email=eq.{request.email}",
            headers=HEADERS
        )
        if response.status_code != 200 or not response.json():
            raise HTTPException(status_code=404, detail="User not found")

        user_id = response.json()[0]['id']

        # okx_api_info 테이블에서 사용자 API 정보 검색
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/okx_api_info?user_id=eq.{user_id}&deleted_at=is.null",
            headers=HEADERS
        )
        if response.status_code != 200 or not response.json():
            raise HTTPException(status_code=404, detail="OKX API info not found")

        api_info = response.json()[0]

        return OkxApiResponse(
            okx_uid=api_info['okx_uid'],
            api_key=api_info['api_key'],
            api_secret=api_info['api_secret']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
