import secrets
from pydantic import BaseModel, Field
from typing import Optional

class SignupDto(BaseModel):
    user_id: str = Field(examples=["user_id"])
    exchange_name: str = Field(examples=["Exchange name"])
    api_key: str = Field(examples=["api_key"])
    secret_key: str = Field(examples=["secret_key"])
    password: Optional[str] = Field(examples=["password"])


class LoginDto(SignupDto):
    username: str = Field(examples=["sample user name"])
    password: str = Field(examples=["sample password"])
