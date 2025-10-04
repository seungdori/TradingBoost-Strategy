"""공통 사용자 DTO

GRID와 HYPERRSI 프로젝트에서 공통으로 사용하는 사용자 관련 데이터 모델
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class UserExistDto(BaseModel):
    """사용자 존재 여부 확인 DTO"""
    user_exist: bool
    user_ids: Optional[List[int]] = None


class UserDto(BaseModel):
    """사용자 전체 정보 DTO"""
    id: int = Field(examples=[0])
    username: str = Field(examples=["sample_user"])
    password: str = Field(examples=["sample_password"])


class UserCreateDto(BaseModel):
    """사용자 생성 요청 DTO"""
    username: str
    password: str


class UserWithoutPasswordDto(BaseModel):
    """비밀번호 제외 사용자 정보 DTO"""
    user_id: str

    @classmethod
    def from_user_dto(cls, user_dto: dict):
        return cls(user_id=user_dto['user_id'])


class UserResponseDto(BaseModel):
    """사용자 응답 DTO (HYPERRSI 호환)"""
    telegram_id: str
    okx_uid: Optional[str] = None
    api_key: Optional[str] = None
    secret_key: Optional[str] = None
    passphrase: Optional[str] = None
