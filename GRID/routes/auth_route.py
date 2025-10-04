from fastapi import APIRouter
from shared.dtos.auth import LoginDto, SignupDto
from shared.dtos.response import ResponseDto
from shared.dtos.user import UserWithoutPasswordDto
from services import auth_service
import user_database
from fastapi import HTTPException
router = APIRouter(prefix="/auth", tags=["auth"])

#@router.post("/login")
#async def login(dto: LoginDto) -> ResponseDto[UserWithoutPasswordDto | None]:
#    user = await auth_service.login(dto)
#
#    if user:
#        return ResponseDto[UserWithoutPasswordDto](
#            success=True,
#            message=f"[{dto.username}] 로그인에 성공했습니다.",
#            data=user
#        )
#    else:
#        return ResponseDto[None](
#            success=False,
#            message=f"입력한 [{dto.username}] 사용자 정보가 올바르지 않습니다. 아이디 또는 비밀번호를 확인해주세요.",
#            data=None
#        )


@router.post("/signup")
async def signup(dto: SignupDto) -> dict:
    print('[SIGN UP]', dto)
    user_id = dto.user_id
    exchange_name = dto.exchange_name
    api_key = dto.api_key
    api_secret = dto.secret_key
    password = dto.password
    try:
        user = await user_database.insert_user(user_id, exchange_name, api_key, api_secret, password)
        if user:
            return {
                "success": True,
                "message": f"[{user}]의 사용자 정보를 등록했습니다.",
                "data": user
            }
        else:
            return {
                "success": False,
                "message": "사용자 정보 등록을 실패했습니다.",
                "data": None
            }
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            raise HTTPException(status_code=400, detail=f"사용자 ID '{user_id}'는 이미 존재합니다.")
        return {
            "success": False,
            "message": f"사용자 정보 등록을 실패했습니다. {e}",
            "data": None
        }