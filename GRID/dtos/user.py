from pydantic import BaseModel, Field
from typing import List, Optional

class UserExistDto(BaseModel):
    user_exist: bool
    user_ids: Optional[List[int]] = None

class UserDto(BaseModel):
    id: int = Field(examples=[0])
    username: str = Field(examples=["sample user name"])  # int → str 수정
    password: str = Field(examples=["sample password"])


class UserCreateDto(BaseModel):
    username: str
    password: str

class UserWithoutPasswordDto(BaseModel):
    user_id: str  # user_id를 문자열로 변경

    @classmethod
    def from_user_dto(cls, user_dto: dict):
        return cls(user_id=user_dto['user_id'])