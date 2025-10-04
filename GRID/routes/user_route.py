from fastapi import APIRouter
from shared.dtos.response import ResponseDto
from shared.dtos.user import UserExistDto, UserWithoutPasswordDto
from services import user_service
from typing import Optional, Union
router = APIRouter(prefix="/user", tags=["user"])


@router.get("/exist")
async def check_user_exist_route(exchange_name: str) -> ResponseDto:
    user_exist_dto = await user_service.check_user_exist(exchange_name)

    return ResponseDto[UserExistDto](
        success=True,
        message="User exists" if user_exist_dto.user_exist else "User does not exist",
        data=user_exist_dto
    )



# Query param.
# e.g. URL/user/?username=sample
#@router.get("/")
#async def get_user_by_username_route(exchange_name: str, username: str) -> ResponseDto[Union[UserWithoutPasswordDto, None]]:
#    print('[USERNAME]', username)
#    user = await user_service.find_user_by_username(exchange_name, username)
#
#    if user:
#        return ResponseDto[UserWithoutPasswordDto](
#            success=True,
#            message=f"User [{username}] found",
#            data=UserWithoutPasswordDto.from_user_dto(user_dto=user)
#        )
#    else:
#        return ResponseDto[None](
#            success=False,
#            message=f"User [{username}] not found",
#            data=None
#        )


@router.get("/{user_id}")
async def get_user_by_id_route(exchange_name: str, user_id: str) -> ResponseDto[Union[UserWithoutPasswordDto, None]]:
    print('[ID]', user_id)
    user = await user_service.get_user_by_id(exchange_name, user_id)
    print('[USER]', user)
    if user:
        return ResponseDto[UserWithoutPasswordDto](
            success=True,
            message=f"User ID[{user_id}] found",
            data=UserWithoutPasswordDto.from_user_dto(user_dto=user),
        )
    else:
        return ResponseDto[None](
            success=False,
            message=f"User ID[{user_id}] not found",
            data=None
        )
